"""Silo server sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import SiloConfigEntry, server_device_info
from .coordinator import ServerSnapshot


def _stat(key: str) -> Callable[[ServerSnapshot], Any]:
    return lambda snap: (snap.stats or {}).get(key)


def _req(key: str) -> Callable[[ServerSnapshot], Any]:
    return lambda snap: (snap.requests or {}).get(key)


def _running(snap: ServerSnapshot) -> int:
    return sum(1 for t in snap.tasks or [] if t.get("state") not in (None, "idle"))


def _running_attrs(snap: ServerSnapshot) -> dict[str, Any]:
    return {
        "tasks": [
            {"name": t.get("name"), "key": t.get("key"), "progress": t.get("progress")}
            for t in snap.tasks or []
            if t.get("state") not in (None, "idle")
        ]
    }


def _last_scan(snap: ServerSnapshot):
    for task in snap.tasks or []:
        if task.get("key") == "scan_libraries":
            done = (task.get("last_execution") or {}).get("completed_at")
            return dt_util.parse_datetime(done) if done else None
    return None


@dataclass(frozen=True, kw_only=True)
class ServerSensorDescription(SensorEntityDescription):
    """A sensor read from the server snapshot."""

    value_fn: Callable[[ServerSnapshot], Any]
    attrs_fn: Callable[[ServerSnapshot], dict[str, Any]] | None = None
    source: str  # which part of the snapshot must exist for the sensor to be created


SERVER_SENSORS: tuple[ServerSensorDescription, ...] = (
    ServerSensorDescription(
        key="movies", translation_key="movies", source="stats",
        state_class=SensorStateClass.MEASUREMENT, value_fn=_stat("total_movies"),
    ),
    ServerSensorDescription(
        key="shows", translation_key="shows", source="stats",
        state_class=SensorStateClass.MEASUREMENT, value_fn=_stat("total_shows"),
    ),
    ServerSensorDescription(
        key="episodes", translation_key="episodes", source="stats",
        state_class=SensorStateClass.MEASUREMENT, value_fn=_stat("total_show_files"),
    ),
    ServerSensorDescription(
        key="titles", translation_key="titles", source="stats",
        state_class=SensorStateClass.MEASUREMENT, value_fn=_stat("total_items"),
        entity_registry_enabled_default=False,
    ),
    ServerSensorDescription(
        key="storage", translation_key="storage", source="stats",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.TERABYTES,
        suggested_display_precision=2,
        value_fn=_stat("total_storage_bytes"),
    ),
    ServerSensorDescription(
        key="requests_pending", translation_key="requests_pending", source="requests",
        state_class=SensorStateClass.MEASUREMENT, value_fn=_req("needs_approval"),
    ),
    ServerSensorDescription(
        key="requests_failed", translation_key="requests_failed", source="requests",
        state_class=SensorStateClass.MEASUREMENT, value_fn=_req("failed"),
        entity_registry_enabled_default=False,
    ),
    ServerSensorDescription(
        key="running_tasks", translation_key="running_tasks", source="tasks",
        state_class=SensorStateClass.MEASUREMENT, value_fn=_running, attrs_fn=_running_attrs,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    ServerSensorDescription(
        key="last_library_scan", translation_key="last_library_scan", source="tasks",
        device_class=SensorDeviceClass.TIMESTAMP, value_fn=_last_scan,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SiloConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create server sensors for whatever this API key can read."""
    data = entry.runtime_data
    snapshot = data.server.data or ServerSnapshot()
    entities: list[SensorEntity] = [
        SiloServerSensor(entry, desc)
        for desc in SERVER_SENSORS
        if getattr(snapshot, desc.source) is not None
    ]
    if data.coordinator.sessions_supported:
        entities += [SiloStreamsSensor(entry, transcodes=False), SiloStreamsSensor(entry, transcodes=True)]
    async_add_entities(entities)


class _ServerEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, entry: SiloConfigEntry, coordinator: DataUpdateCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.runtime_data.server_id}_{key}"
        self._attr_device_info = DeviceInfo(**server_device_info(entry))


class SiloServerSensor(_ServerEntity, SensorEntity):
    """A figure from the server snapshot."""

    entity_description: ServerSensorDescription

    def __init__(self, entry: SiloConfigEntry, description: ServerSensorDescription) -> None:
        super().__init__(entry, entry.runtime_data.server, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data or ServerSnapshot())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data or ServerSnapshot())


class SiloStreamsSensor(_ServerEntity, SensorEntity):
    """Live stream (or transcode) count from the session list."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: SiloConfigEntry, *, transcodes: bool) -> None:
        key = "transcodes" if transcodes else "active_streams"
        super().__init__(entry, entry.runtime_data.coordinator, key)
        self._transcodes = transcodes
        self._attr_translation_key = key

    def _sessions(self) -> list[dict[str, Any]]:
        sessions = self.coordinator.data or []
        if self._transcodes:
            sessions = [
                s for s in sessions
                if (s.get("effective_play_method") or s.get("play_method")) == "transcode"
            ]
        return sessions

    @property
    def native_value(self) -> int:
        return len(self._sessions())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "sessions": [
                {
                    "profile": s.get("profile_name"),
                    "title": " – ".join(
                        x for x in (s.get("series_name"), s.get("episode_name") or s.get("media_title")) if x
                    ),
                    "client": s.get("client_label") or s.get("client_name"),
                    "method": s.get("effective_play_method") or s.get("play_method"),
                    "paused": s.get("is_paused"),
                }
                for s in self._sessions()
            ]
        }
