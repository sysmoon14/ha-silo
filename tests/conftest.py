"""Fixtures for Silo tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import custom_components

# The test harness ships its own custom_components package; add this repo's
# folder to it so Home Assistant can discover the silo integration.
_REPO_COMPONENTS = str(Path(__file__).parents[1] / "custom_components")
if _REPO_COMPONENTS not in custom_components.__path__:
    custom_components.__path__.append(_REPO_COMPONENTS)

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

URL = "http://silo.local:8090"
API = f"{URL}/api/v2"
SERVER_ID = "8cb4eb21-a400-4839-b28b-a05e978eb55d"
ROSA = "5341fe3d-9970-48de-9e8b-94a131954eca"
ADB = "media_player.living_room_tv_adb"
TV_IP = "10.22.4.13"

PROFILES = {
    "items": [
        {"id": "e7ff7a72-de57-461b-9971-919ac054448f", "name": "Mum and Dad", "is_primary": True},
        {"id": ROSA, "name": "Rosa", "is_primary": False, "is_child": True},
    ]
}

# Trimmed from a real /api/v2/admin/sessions response.
SESSION = {
    "session_id": "c70d2e5e-2f64-4137-9d35-b3ff828e20a8",
    "profile_id": ROSA,
    "profile_name": "Rosa",
    "content_id": "episode-tvdb-79222-2-4",
    "media_title": "Peppa Pig",
    "media_type": "series",
    "series_name": "Peppa Pig",
    "episode_name": "Teddy's Day Out",
    "season_number": 2,
    "episode_number": 4,
    "poster_url": "/api/v2/artwork/tvdb/series/79222/poster/w300.webp?exp=1&sig=x",
    "play_method": "direct",
    "file_duration": 312,
    "updated_at": "2026-10-14T16:42:17.803Z",
    "position_seconds": 120.467,
    "is_paused": False,
    "has_playback_control": True,
    "client_ip": TV_IP,
    "client_label": "Silo Android TV 1.0.0",
    "effective_play_method": "direct",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
    """Enable custom integrations in all tests."""


def mock_silo(aioclient_mock: AiohttpClientMocker, sessions: list[dict] | None = None) -> None:
    """Register the endpoints Silo answers during setup."""
    aioclient_mock.get(f"{API}/system/identity", json={"server_id": SERVER_ID})
    aioclient_mock.get(f"{API}/profiles", json=PROFILES)
    aioclient_mock.get(
        f"{API}/admin/sessions",
        json={"items": sessions if sessions is not None else [SESSION], "page": {"has_more": False}},
    )


@pytest.fixture
async def adb_tv(hass: HomeAssistant) -> str:
    """An androidtv media player with a config entry that knows the TV's host."""
    entry = MockConfigEntry(domain="androidtv", data={"host": TV_IP, "port": 5555})
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "media_player",
        "androidtv",
        "shield-1",
        suggested_object_id="living_room_tv_adb",
        config_entry=entry,
    )
    hass.states.async_set(ADB, "playing", {"friendly_name": "Living Room TV"})
    return ADB


@pytest.fixture
def silo_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A configured Silo entry with one linked TV."""
    entry = MockConfigEntry(
        domain="silo",
        title="Silo",
        unique_id=SERVER_ID,
        data={"url": URL, "api_key": "sa_test"},
        options={
            "profile_id": ROSA,
            "wake_delay": 0,
            "tvs": [{"adb_entity_id": ADB, "name": "Living Room TV", "client_ip": TV_IP}],
        },
    )
    entry.add_to_hass(hass)
    return entry
