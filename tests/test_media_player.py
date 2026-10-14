"""Media player, actions and browse tests."""

from __future__ import annotations


import pytest

from homeassistant.components.media_player import BrowseError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from pytest_homeassistant_custom_component.common import async_mock_service
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .conftest import ADB, API, ROSA, SESSION, mock_silo

ENTITY = "media_player.living_room_tv"


@pytest.fixture
async def setup(hass: HomeAssistant, aioclient_mock, adb_tv, silo_entry):
    mock_silo(aioclient_mock)
    assert await hass.config_entries.async_setup(silo_entry.entry_id)
    await hass.async_block_till_done()
    # Registered after setup so they replace the real media_player services.
    adb_calls = async_mock_service(hass, "androidtv", "adb_command")
    on_calls = async_mock_service(hass, "media_player", "turn_on")
    return adb_calls, on_calls


async def test_now_playing_state(hass: HomeAssistant, setup) -> None:
    state = hass.states.get(ENTITY)
    assert state.state == "playing"
    assert state.attributes["media_title"] == "Teddy's Day Out"
    assert state.attributes["media_series_title"] == "Peppa Pig"
    assert state.attributes["media_content_id"] == "episode-tvdb-79222-2-4"
    assert state.attributes["series_id"] == "series-tvdb-79222"
    assert state.attributes["season_id"] == "season-tvdb-79222-2"
    assert state.attributes["media_duration"] == 312
    assert state.attributes["entity_picture"].startswith("/api/media_player_proxy/")


async def test_idle_and_off_without_session(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, adb_tv, silo_entry
) -> None:
    mock_silo(aioclient_mock, sessions=[])
    assert await hass.config_entries.async_setup(silo_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "idle"
    hass.states.async_set(ADB, "off")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "off"


async def test_pause_sends_session_command(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, setup
) -> None:
    aioclient_mock.post(f"{API}/admin/sessions/{SESSION['session_id']}/pause", status=202, json={})
    await hass.services.async_call("media_player", "media_pause", {"entity_id": ENTITY}, blocking=True)
    call = next(c for c in aioclient_mock.mock_calls if str(c[1]).endswith("/pause"))
    assert call[2]["sequence"] > 0 and len(call[2]["command_id"]) == 36


async def test_play_movie(hass: HomeAssistant, setup) -> None:
    adb_calls, on_calls = setup
    result = await hass.services.async_call(
        "silo", "play", {"entity_id": ENTITY, "content_id": "movie-tmdb-862"},
        blocking=True, return_response=True,
    )
    assert result[ENTITY]["content_id"] == "movie-tmdb-862"
    assert on_calls[0].data["entity_id"] == ADB
    assert adb_calls[0].data == {
        "entity_id": ADB,
        "command": "am start -a android.intent.action.VIEW -d 'silo://play/movie-tmdb-862' org.siloserver.silo",
    }


async def test_play_series_shuffles(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, setup
) -> None:
    adb_calls, _ = setup
    aioclient_mock.post(
        f"{API}/shuffles",
        status=201,
        json={"id": "shuf-1", "current": {"content_id": "episode-tvdb-353546-2-8", "title": "Daddy Dropoff"}},
    )
    aioclient_mock.delete(f"{API}/shuffles/shuf-1", status=204)
    result = await hass.services.async_call(
        "silo", "shuffle", {"entity_id": ENTITY, "scope_id": "series-tvdb-353546"},
        blocking=True, return_response=True,
    )
    assert result[ENTITY] == {"skipped": False, "content_id": "episode-tvdb-353546-2-8", "title": "Daddy Dropoff"}
    post = next(c for c in aioclient_mock.mock_calls if c[0].lower() == "post" and str(c[1]).endswith("/shuffles"))
    assert post[2] == {"scope": {"kind": "series", "id": "series-tvdb-353546"}}
    assert post[3]["X-Profile-Id"] == ROSA
    assert any(c[0].lower() == "delete" and str(c[1]).endswith("/shuffles/shuf-1") for c in aioclient_mock.mock_calls)
    assert "silo://play/episode-tvdb-353546-2-8" in adb_calls[0].data["command"]


async def test_from_start_clears_resume(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, setup
) -> None:
    adb_calls, _ = setup
    aioclient_mock.delete(f"{API}/watched/movie-tmdb-862", status=204)
    await hass.services.async_call(
        "silo", "play", {"entity_id": ENTITY, "content_id": "movie-tmdb-862", "from_start": True},
        blocking=True,
    )
    assert any(c[0].lower() == "delete" and str(c[1]).endswith("/watched/movie-tmdb-862") for c in aioclient_mock.mock_calls)
    assert len(adb_calls) == 1


async def test_skip_if_playing_series(hass: HomeAssistant, setup) -> None:
    adb_calls, _ = setup
    result = await hass.services.async_call(
        "silo", "play",
        {"entity_id": ENTITY, "content_id": "series-tvdb-79222", "skip_if_playing": True},
        blocking=True, return_response=True,
    )
    assert result[ENTITY]["skipped"] is True
    assert adb_calls == []


def test_clean_tv_name() -> None:
    from custom_components.silo.media_player import clean_tv_name

    assert clean_tv_name("Living Room TV - ADB") == "Living Room TV"
    assert clean_tv_name("Kitchen Shield (ADB)") == "Kitchen Shield"
    assert clean_tv_name("Kitchen Shield (Android TV)") == "Kitchen Shield"
    assert clean_tv_name("Bedroom TV") == "Bedroom TV"


async def test_rejects_unsafe_id(hass: HomeAssistant, setup) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "silo", "play", {"entity_id": ENTITY, "content_id": "x'; reboot; '"}, blocking=True
        )


async def test_play_media_from_browse_id(hass: HomeAssistant, aioclient_mock, setup) -> None:
    adb_calls, _ = setup
    aioclient_mock.post(f"{API}/shuffles", status=201, json={"id": "s2", "current": {"content_id": "episode-tvdb-1-1-3"}})
    aioclient_mock.delete(f"{API}/shuffles/s2", status=204)
    await hass.services.async_call(
        "media_player", "play_media",
        {"entity_id": ENTITY, "media_content_type": "season",
         "media_content_id": "silo://season/series-tvdb-1/1/season-tvdb-1-1"},
        blocking=True,
    )
    post = next(c for c in aioclient_mock.mock_calls if c[0].lower() == "post" and str(c[1]).endswith("/shuffles"))
    assert post[2]["scope"] == {"kind": "season", "id": "season-tvdb-1-1"}
    assert "episode-tvdb-1-1-3" in adb_calls[0].data["command"]


async def test_browse(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, setup) -> None:
    aioclient_mock.get(f"{API}/user/libraries", json={"items": [
        {"id": "1", "name": "Movies", "type": "movies"},
        {"id": "2", "name": "TV", "type": "series"},
        {"id": "3", "name": "Audiobooks", "type": "audiobooks"},
    ]})
    aioclient_mock.get(f"{API}/catalog?library_id=2", json={"items": [
        {"content_id": "series-tvdb-353546", "type": "series", "title": "Bluey (2018)", "poster_url": "/api/v2/a.webp"},
    ], "page": {"has_more": False}})
    aioclient_mock.get(f"{API}/catalog/series/series-tvdb-353546/seasons", json={"items": [
        {"content_id": "season-tvdb-353546-1", "season_number": 1, "title": "Series 1"},
    ]})
    aioclient_mock.get(f"{API}/catalog/series/series-tvdb-353546/seasons/1/episodes", json={"items": [
        {"content_id": "episode-tvdb-353546-1-1", "episode_number": 1, "title": "Magic Xylophone"},
    ]})
    entity = hass.data["entity_components"]["media_player"].get_entity(ENTITY)

    root = await entity.async_browse_media()
    assert [c.title for c in root.children] == ["Movies", "TV"]
    tv = await entity.async_browse_media("channels", root.children[1].media_content_id)
    show = tv.children[0]
    assert show.can_play and show.can_expand
    assert show.thumbnail == "http://silo.local:8090/api/v2/a.webp"
    seasons = await entity.async_browse_media("tvshow", show.media_content_id)
    episodes = await entity.async_browse_media("season", seasons.children[0].media_content_id)
    assert episodes.children[0].media_content_id == "episode-tvdb-353546-1-1"
    assert episodes.children[0].title == "1. Magic Xylophone"
    with pytest.raises(BrowseError):
        await entity.async_browse_media("x", "silo://nonsense")
