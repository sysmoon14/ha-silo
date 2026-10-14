"""Profile sensors, send_message / stop_playback, search and the artwork proxy."""

from __future__ import annotations

from http import HTTPStatus

import pytest

from homeassistant.components.media_player import MediaClass, SearchMediaQuery
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .conftest import API, ROSA, SERVER_ID, SESSION, URL, mock_silo

TV = "media_player.living_room_tv"
PHONE_SESSION = {
    **SESSION,
    "session_id": "phone-1",
    "client_ip": "10.22.2.246",
    "client_label": "Silo Android 1.0.0",
    "content_id": "movie-tmdb-10192",
    "media_title": "Shrek Forever After",
    "series_name": None,
    "episode_name": None,
    "season_number": None,
    "episode_number": None,
    "is_paused": True,
    "position_seconds": 4537.2,
    "file_duration": 5615,
    "updated_at": "2026-10-14T16:00:00Z",
}


@pytest.fixture
async def loaded(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, adb_tv, silo_entry):
    mock_silo(aioclient_mock, sessions=[SESSION, PHONE_SESSION])
    assert await hass.config_entries.async_setup(silo_entry.entry_id)
    await hass.async_block_till_done()
    return silo_entry


def _profile_entity(hass: HomeAssistant, profile_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", "silo", f"{SERVER_ID}_profile_{profile_id}"
    )
    assert entity_id
    return entity_id


async def test_profile_sensors(hass: HomeAssistant, loaded) -> None:
    rosa = hass.states.get(_profile_entity(hass, ROSA))
    # One session playing (TV) and one paused (phone): playing wins.
    assert rosa.state == "playing"
    assert rosa.name == "Silo server Rosa watching"
    assert rosa.attributes["sessions"] == 2
    assert rosa.attributes["media_title"] == "Teddy's Day Out"
    assert rosa.attributes["media_series_title"] == "Peppa Pig"
    assert rosa.attributes["progress"] == 39

    adults = hass.states.get(_profile_entity(hass, "e7ff7a72-de57-461b-9971-919ac054448f"))
    assert adults.state == "idle"
    assert adults.attributes["sessions"] == 0


async def test_send_message_to_tv(hass: HomeAssistant, aioclient_mock, loaded) -> None:
    aioclient_mock.post(f"{API}/admin/sessions/{SESSION['session_id']}/message", status=202, json={})
    result = await hass.services.async_call(
        "silo", "send_message",
        {"entity_id": TV, "title": "Bedtime", "message": "Five more minutes!"},
        blocking=True, return_response=True,
    )
    assert result == {"sessions": 1}
    call = next(c for c in aioclient_mock.mock_calls if str(c[1]).endswith("/message"))
    assert call[2]["title"] == "Bedtime" and call[2]["message"] == "Five more minutes!"
    assert len(call[2]["command_id"]) == 36 and call[2]["sequence"] > 0


async def test_stop_profile_everywhere(hass: HomeAssistant, aioclient_mock, loaded) -> None:
    for sid in (SESSION["session_id"], "phone-1"):
        aioclient_mock.post(f"{API}/admin/sessions/{sid}/stop", status=202, json={})
    # Targeting the TV and Rosa's sensor reaches the TV session only once.
    result = await hass.services.async_call(
        "silo", "stop_playback",
        {"entity_id": [TV, _profile_entity(hass, ROSA)]},
        blocking=True, return_response=True,
    )
    assert result == {"sessions": 2}
    stops = sorted(str(c[1]) for c in aioclient_mock.mock_calls if str(c[1]).endswith("/stop"))
    assert stops == [
        f"{API}/admin/sessions/{SESSION['session_id']}/stop",
        f"{API}/admin/sessions/phone-1/stop",
    ]


async def test_nothing_playing_is_not_an_error(hass: HomeAssistant, loaded) -> None:
    result = await hass.services.async_call(
        "silo", "stop_playback",
        {"entity_id": _profile_entity(hass, "e7ff7a72-de57-461b-9971-919ac054448f")},
        blocking=True, return_response=True,
    )
    assert result == {"sessions": 0}


async def test_search(hass: HomeAssistant, aioclient_mock, loaded) -> None:
    aioclient_mock.get(f"{API}/catalog?q=bluey&type=video", json={"items": [
        {"content_id": "series-tvdb-353546", "type": "series", "title": "Bluey (2018)",
         "poster_url": "/api/v2/artwork/tvdb/series/353546/poster/w300.webp?exp=1&sig=a"},
    ], "page": {"has_more": False}})
    aioclient_mock.get(f"{API}/catalog?q=toy&type=movie", json={"items": [
        {"content_id": "movie-tmdb-862", "type": "movie", "title": "Toy Story", "year": 1995},
    ], "page": {"has_more": False}})
    entity = hass.data["entity_components"]["media_player"].get_entity(TV)

    result = await entity.async_search_media(SearchMediaQuery(search_query="bluey"))
    assert [r.media_content_id for r in result.result] == ["silo://series/series-tvdb-353546"]
    # Signed Silo artwork goes through Home Assistant's media proxy.
    assert result.result[0].thumbnail.startswith(f"/api/media_player_proxy/{TV}/browse_media/image/artwork")

    movies = await entity.async_search_media(
        SearchMediaQuery(search_query="toy", media_filter_classes=[MediaClass.MOVIE])
    )
    assert [r.title for r in movies.result] == ["Toy Story (1995)"]


async def test_artwork_proxy(hass: HomeAssistant, hass_client, aioclient_mock, loaded) -> None:
    path = "/api/v2/artwork/tvdb/series/353546/poster/w300.webp?exp=1&sig=a"
    aioclient_mock.get(f"{URL}{path}", content=b"RIFFwebp", headers={"Content-Type": "image/webp"})
    entity = hass.data["entity_components"]["media_player"].get_entity(TV)

    client = await hass_client()
    resp = await client.get(entity.get_browse_image_url("image", "artwork", path))
    assert resp.status == HTTPStatus.OK
    assert await resp.read() == b"RIFFwebp"
    # The artwork request never carries the API key.
    art_call = next(c for c in aioclient_mock.mock_calls if "/artwork/" in str(c[1]))
    assert not (art_call[3] or {}).get("Authorization")

    # Anything outside Silo's artwork path is refused.
    for bad in ("/api/v2/profiles", "/api/v2/artwork/../profiles", "http://evil/x.png"):
        assert await entity.async_get_browse_image("image", "artwork", bad) == (None, None)
