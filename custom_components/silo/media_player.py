"""Silo media player: one entity per linked Android TV."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.const import STATE_OFF, STATE_STANDBY, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, ServiceResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import SiloConfigEntry
from .api import SiloError, content_kind
from .browse_media import async_browse, playable_id
from .const import (
    ANDROID_PACKAGE,
    CONF_ADB_ENTITY,
    CONF_CLIENT_IP,
    CONF_NAME,
    CONF_PROFILE_ID,
    CONF_TVS,
    CONF_WAKE_DELAY,
    DEFAULT_WAKE_DELAY,
    DOMAIN,
)
from .coordinator import SiloSessionCoordinator

_LOGGER = logging.getLogger(__name__)

# Silo content ids are like movie-tmdb-123 or episode-tvdb-1-2-3. Anything
# outside this set is refused so nothing odd reaches the adb shell command.
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$")
EPISODE_ID = re.compile(r"^episode-(?P<src>[a-z0-9]+)-(?P<id>[^-]+)-(?P<s>\d+)-(?P<e>\d+)$")
OFF_STATES = (STATE_OFF, STATE_STANDBY, STATE_UNAVAILABLE, STATE_UNKNOWN)

FEATURES = (
    MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
)
CONTROL_FEATURES = (
    MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.STOP
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SiloConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create a media player for every linked TV."""
    async_add_entities(
        SiloTvPlayer(entry, tv) for tv in entry.options.get(CONF_TVS, [])
    )


def series_id_of(content_id: str | None) -> str | None:
    """episode-tvdb-79222-2-4 -> series-tvdb-79222."""
    match = EPISODE_ID.match(content_id or "")
    return f"series-{match['src']}-{match['id']}" if match else None


def season_id_of(content_id: str | None) -> str | None:
    """episode-tvdb-79222-2-4 -> season-tvdb-79222-2."""
    match = EPISODE_ID.match(content_id or "")
    return f"season-{match['src']}-{match['id']}-{match['s']}" if match else None


class SiloTvPlayer(CoordinatorEntity[SiloSessionCoordinator], MediaPlayerEntity):
    """A TV running the Silo Android TV app, launched over ADB."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_media_image_remotely_accessible = False

    def __init__(self, entry: SiloConfigEntry, tv: dict[str, Any]) -> None:
        data = entry.runtime_data
        super().__init__(data.coordinator)
        self._entry = entry
        self._client = data.client
        self._adb_entity: str = tv[CONF_ADB_ENTITY]
        self._client_ip: str | None = tv.get(CONF_CLIENT_IP) or None
        self._attr_unique_id = f"{data.server_id}_{self._adb_entity}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=tv.get(CONF_NAME) or self._adb_entity,
            manufacturer="Silo",
            model="Silo Android TV",
            via_device=(DOMAIN, data.server_id),
        )

    # Helpers -------------------------------------------------------------

    @property
    def _profile_id(self) -> str | None:
        return self._entry.options.get(CONF_PROFILE_ID)

    @property
    def _session(self) -> dict[str, Any] | None:
        if not self._client_ip or not self.coordinator.data:
            return None
        matches = [s for s in self.coordinator.data if s.get("client_ip") == self._client_ip]
        if not matches:
            return None
        return max(matches, key=lambda s: s.get("updated_at") or "")

    @property
    def _adb_state(self) -> str | None:
        state = self.hass.states.get(self._adb_entity)
        return state.state if state else None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def _adb_changed(_: Event[EventStateChangedData]) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(self.hass, [self._adb_entity], _adb_changed)
        )

    # State ---------------------------------------------------------------

    @property
    def state(self) -> MediaPlayerState:
        session = self._session
        if session:
            return MediaPlayerState.PAUSED if session.get("is_paused") else MediaPlayerState.PLAYING
        if self._adb_state in OFF_STATES:
            return MediaPlayerState.OFF
        return MediaPlayerState.IDLE

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        if self._session and self._session.get("has_playback_control", True):
            return FEATURES | CONTROL_FEATURES
        return FEATURES

    @property
    def media_content_id(self) -> str | None:
        return (self._session or {}).get("content_id")

    @property
    def media_content_type(self) -> str | None:
        session = self._session
        if not session:
            return None
        return MediaType.EPISODE if session.get("episode_name") or series_id_of(
            session.get("content_id")
        ) else MediaType.MOVIE

    @property
    def media_title(self) -> str | None:
        session = self._session or {}
        return session.get("episode_name") or session.get("media_title")

    @property
    def media_series_title(self) -> str | None:
        return (self._session or {}).get("series_name")

    @property
    def media_season(self) -> str | None:
        value = (self._session or {}).get("season_number")
        return None if value is None else str(value)

    @property
    def media_episode(self) -> str | None:
        value = (self._session or {}).get("episode_number")
        return None if value is None else str(value)

    @property
    def media_duration(self) -> int | None:
        return (self._session or {}).get("file_duration")

    @property
    def media_position(self) -> int | None:
        value = (self._session or {}).get("position_seconds")
        return None if value is None else int(value)

    @property
    def media_position_updated_at(self):
        value = (self._session or {}).get("updated_at")
        return dt_util.parse_datetime(value) if value else None

    @property
    def media_image_url(self) -> str | None:
        return self._client.absolute((self._session or {}).get("poster_url"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        session = self._session
        attrs: dict[str, Any] = {"adb_entity_id": self._adb_entity, "client_ip": self._client_ip}
        if session:
            content_id = session.get("content_id")
            attrs.update(
                {
                    "series_id": series_id_of(content_id),
                    "season_id": season_id_of(content_id),
                    "profile_name": session.get("profile_name"),
                    "session_id": session.get("session_id"),
                    "client": session.get("client_label"),
                    "play_method": session.get("effective_play_method")
                    or session.get("play_method"),
                }
            )
        return attrs

    # Controls ------------------------------------------------------------

    async def _session_command(self, action: str) -> None:
        session = self._session
        if not session:
            raise HomeAssistantError("Nothing is playing in Silo on this TV")
        try:
            await self._client.session_command(session["session_id"], action)
        except SiloError as err:
            raise HomeAssistantError(f"Silo couldn't {action}: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_media_pause(self) -> None:
        await self._session_command("pause")

    async def async_media_play(self) -> None:
        await self._session_command("resume")

    async def async_media_stop(self) -> None:
        await self._session_command("stop")

    async def async_turn_on(self) -> None:
        await self.hass.services.async_call(
            "media_player", "turn_on", {"entity_id": self._adb_entity}, blocking=True
        )

    async def async_turn_off(self) -> None:
        await self.hass.services.async_call(
            "media_player", "turn_off", {"entity_id": self._adb_entity}, blocking=True
        )

    # Playback ------------------------------------------------------------

    async def async_play_media(self, media_type: str, media_id: str, **kwargs: Any) -> None:
        extra = kwargs.get("extra") or {}
        await self.async_silo_play(
            content_id=playable_id(media_id),
            from_start=bool(extra.get("from_start", False)),
            skip_if_playing=bool(extra.get("skip_if_playing", False)),
        )

    async def async_silo_shuffle(self, scope_id: str, **kwargs: Any) -> ServiceResponse:
        if content_kind(scope_id) not in ("series", "season"):
            raise ServiceValidationError(f"{scope_id} is not a Silo series or season id")
        return await self.async_silo_play(content_id=scope_id, **kwargs)

    async def async_silo_play(
        self,
        content_id: str,
        from_start: bool = False,
        skip_if_playing: bool = False,
        profile_id: str | None = None,
    ) -> ServiceResponse:
        """Play a movie or episode, or a random episode of a series/season."""
        content_id = content_id.strip()
        if not SAFE_ID.match(content_id):
            raise ServiceValidationError(f"'{content_id}' doesn't look like a Silo content id")
        profile = profile_id or self._profile_id
        kind = content_kind(content_id)

        if skip_if_playing and self._is_playing(content_id, kind):
            return {"skipped": True, "content_id": self.media_content_id, "title": self.media_title}

        target, title = content_id, None
        try:
            if kind in ("series", "season"):
                pick = await self._client.shuffle_pick(profile, content_id)
                target = pick["content_id"]
                title = pick.get("title")
            if from_start:
                await self._client.mark_unwatched(profile, target)
        except SiloError as err:
            raise HomeAssistantError(f"Silo: {err}") from err
        if not SAFE_ID.match(target):
            raise HomeAssistantError(f"Silo returned an unexpected id: {target}")

        await self._launch(target)
        return {"skipped": False, "content_id": target, "title": title}

    def _is_playing(self, content_id: str, kind: str) -> bool:
        current = self.media_content_id
        if not current or self.state not in (MediaPlayerState.PLAYING, MediaPlayerState.PAUSED):
            return False
        if kind == "series":
            return series_id_of(current) == content_id
        if kind == "season":
            return season_id_of(current) == content_id
        return current == content_id

    async def _launch(self, content_id: str) -> None:
        was_off = self._adb_state in OFF_STATES
        await self.async_turn_on()
        if was_off:
            await asyncio.sleep(
                float(self._entry.options.get(CONF_WAKE_DELAY, DEFAULT_WAKE_DELAY))
            )
        await self.hass.services.async_call(
            "androidtv",
            "adb_command",
            {
                "entity_id": self._adb_entity,
                "command": (
                    "am start -a android.intent.action.VIEW "
                    f"-d 'silo://play/{content_id}' {ANDROID_PACKAGE}"
                ),
            },
            blocking=True,
        )
        self._entry.async_create_background_task(
            self.hass, self._refresh_soon(), "silo_refresh_after_play"
        )

    async def _refresh_soon(self) -> None:
        await asyncio.sleep(3)
        await self.coordinator.async_request_refresh()

    async def async_browse_media(
        self, media_content_type: str | None = None, media_content_id: str | None = None
    ) -> BrowseMedia:
        return await async_browse(self._client, self._profile_id, media_content_id)
