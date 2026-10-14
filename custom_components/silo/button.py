"""Silo server buttons: library scans, metadata refresh and restart."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SiloConfigEntry, server_device_info
from .api import SiloClient, SiloError


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SiloConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create buttons when the API key has admin access."""
    data = entry.runtime_data
    if data.server.data is None or data.server.data.tasks is None:
        return  # not an admin key
    client = data.client
    entities: list[SiloButton] = [
        SiloButton(entry, "scan_all", lambda: client.run_task("scan_libraries"),
                   translation_key="scan_all"),
        SiloButton(entry, "refresh_metadata", lambda: client.run_task("refresh_metadata"),
                   translation_key="refresh_metadata"),
        SiloButton(entry, "restart", client.restart_server,
                   device_class=ButtonDeviceClass.RESTART,
                   entity_category=EntityCategory.CONFIG),
    ]
    for lib in data.libraries:
        entities.append(_library_button(entry, client, lib))
    async_add_entities(entities)


def _library_button(entry: SiloConfigEntry, client: SiloClient, lib: dict[str, Any]) -> SiloButton:
    lib_id = str(lib["id"])
    return SiloButton(
        entry,
        f"scan_library_{lib_id}",
        lambda: client.scan_library(lib_id),
        translation_key="scan_library",
        placeholders={"library": lib.get("name", lib_id)},
    )


class SiloButton(ButtonEntity):
    """Run a Silo server action."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: SiloConfigEntry,
        key: str,
        action: Callable[[], Awaitable[Any]],
        *,
        translation_key: str | None = None,
        placeholders: dict[str, str] | None = None,
        device_class: ButtonDeviceClass | None = None,
        entity_category: EntityCategory | None = None,
    ) -> None:
        self._action = action
        self._attr_unique_id = f"{entry.runtime_data.server_id}_{key}"
        self._attr_device_info = DeviceInfo(**server_device_info(entry))
        self._attr_translation_key = translation_key
        self._attr_translation_placeholders = placeholders or {}
        self._attr_device_class = device_class
        self._attr_entity_category = entity_category

    async def async_press(self) -> None:
        try:
            await self._action()
        except SiloError as err:
            raise HomeAssistantError(f"Silo: {err}") from err
