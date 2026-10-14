"""Actions (services) for the Silo integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, service

from .api import SiloApiError, SiloError

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_CONTENT_ID,
    ATTR_FROM_START,
    ATTR_PROFILE_ID,
    ATTR_SCOPE_ID,
    ATTR_SKIP_IF_PLAYING,
    ATTR_TASK_KEY,
    DOMAIN,
    SERVICE_PLAY,
    SERVICE_RUN_TASK,
    SERVICE_SHUFFLE,
)

PLAY_SCHEMA = {
    vol.Required(ATTR_CONTENT_ID): cv.string,
    vol.Optional(ATTR_FROM_START, default=False): cv.boolean,
    vol.Optional(ATTR_SKIP_IF_PLAYING, default=False): cv.boolean,
    vol.Optional(ATTR_PROFILE_ID): cv.string,
}

SHUFFLE_SCHEMA = {
    vol.Required(ATTR_SCOPE_ID): cv.string,
    vol.Optional(ATTR_FROM_START, default=False): cv.boolean,
    vol.Optional(ATTR_SKIP_IF_PLAYING, default=False): cv.boolean,
    vol.Optional(ATTR_PROFILE_ID): cv.string,
}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register silo.play and silo.shuffle against Silo media players."""
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_PLAY,
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema=PLAY_SCHEMA,
        func="async_silo_play",
        supports_response=SupportsResponse.OPTIONAL,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SHUFFLE,
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema=SHUFFLE_SCHEMA,
        func="async_silo_shuffle",
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RUN_TASK,
        _async_run_task,
        schema=RUN_TASK_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )


RUN_TASK_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TASK_KEY): cv.string,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)


async def _async_run_task(call: ServiceCall) -> ServiceResponse:
    """Start a Silo background task by its key, e.g. scan_libraries."""
    entries = call.hass.config_entries.async_loaded_entries(DOMAIN)
    wanted = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if wanted:
        entries = [e for e in entries if e.entry_id == wanted]
    if not entries:
        raise ServiceValidationError("No loaded Silo server matches that config entry")
    try:
        result = await entries[0].runtime_data.client.run_task(call.data[ATTR_TASK_KEY])
    except SiloApiError as err:
        if err.status == 404:
            raise ServiceValidationError(
                f"Silo has no task called {call.data[ATTR_TASK_KEY]}"
            ) from err
        raise HomeAssistantError(f"Silo: {err}") from err
    except SiloError as err:
        raise HomeAssistantError(f"Silo: {err}") from err
    return {"task": result or {}}
