"""Actions (services) for the Silo integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.core import HomeAssistant, SupportsResponse, callback
from homeassistant.helpers import config_validation as cv, service

from .const import (
    ATTR_CONTENT_ID,
    ATTR_FROM_START,
    ATTR_PROFILE_ID,
    ATTR_SCOPE_ID,
    ATTR_SKIP_IF_PLAYING,
    DOMAIN,
    SERVICE_PLAY,
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
