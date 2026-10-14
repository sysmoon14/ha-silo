"""The Silo media server integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import SiloAuthError, SiloClient, SiloError
from .const import DOMAIN
from .coordinator import SiloData, SiloServerCoordinator, SiloSessionCoordinator
from .services import async_setup_services

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.MEDIA_PLAYER, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type SiloConfigEntry = ConfigEntry[SiloData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions once."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SiloConfigEntry) -> bool:
    """Set up Silo from a config entry."""
    client = SiloClient(
        async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_API_KEY]
    )
    try:
        identity = await client.identity()
        profiles = await client.profiles()
    except SiloAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except SiloError as err:
        raise ConfigEntryNotReady(str(err)) from err

    version = None
    libraries: list = []
    try:
        version = (await client.system_info()).get("server_version")
    except SiloError:
        pass
    try:
        libraries = await client.all_libraries()
    except SiloError:
        pass  # not an admin key: no per-library scan buttons

    sessions = SiloSessionCoordinator(hass, entry, client)
    server = SiloServerCoordinator(hass, entry, client)
    await sessions.async_config_entry_first_refresh()
    await server.async_config_entry_first_refresh()

    server_id = identity.get("server_id") or entry.unique_id or entry.entry_id
    entry.runtime_data = SiloData(
        client=client,
        coordinator=sessions,
        server=server,
        server_id=server_id,
        version=version,
        libraries=libraries,
        profiles={p["id"]: p.get("name", p["id"]) for p in profiles},
    )
    # Register the server device first so TV players can hang off it.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        **server_device_info(entry),
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


def server_device_info(entry: SiloConfigEntry) -> dict:
    """Device info for the Silo server itself."""
    data = entry.runtime_data
    return {
        "identifiers": {(DOMAIN, data.server_id)},
        "name": "Silo server",
        "manufacturer": "Silo",
        "model": "Media server",
        "sw_version": data.version,
        "configuration_url": entry.data[CONF_URL],
        "entry_type": dr.DeviceEntryType.SERVICE,
    }


async def async_unload_entry(hass: HomeAssistant, entry: SiloConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: SiloConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
