"""Polls Silo for live playback sessions."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SiloApiError, SiloAuthError, SiloClient, SiloError
from .const import DOMAIN, SCAN_INTERVAL

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


@dataclass
class SiloData:
    """Runtime data stored on the config entry."""

    client: SiloClient
    coordinator: SiloSessionCoordinator
    server_id: str
    profiles: dict[str, str] = field(default_factory=dict)


class SiloSessionCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Fetch the server's live playback sessions."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: SiloClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} sessions",
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        # False when the API key can't read sessions (not an admin key).
        self.sessions_supported = True

    async def _async_update_data(self) -> list[dict[str, Any]]:
        if not self.sessions_supported:
            return []
        try:
            return await self.client.sessions()
        except SiloAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SiloApiError as err:
            if err.status == 403:
                _LOGGER.warning(
                    "This Silo API key can't read live sessions (needs an admin key); "
                    "now-playing state and pause/resume/stop are disabled"
                )
                self.sessions_supported = False
                return []
            raise UpdateFailed(str(err)) from err
        except SiloError as err:
            raise UpdateFailed(str(err)) from err
