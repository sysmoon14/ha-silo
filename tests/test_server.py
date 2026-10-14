"""Server device: sensors, buttons and run_task."""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er

from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .conftest import API, SERVER_ID, mock_silo


@pytest.fixture
async def loaded(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, adb_tv, silo_entry):
    mock_silo(aioclient_mock)
    assert await hass.config_entries.async_setup(silo_entry.entry_id)
    await hass.async_block_till_done()
    return silo_entry


def _state(hass: HomeAssistant, unique_key: str, domain: str = "sensor"):
    entity_id = er.async_get(hass).async_get_entity_id(domain, "silo", f"{SERVER_ID}_{unique_key}")
    assert entity_id, unique_key
    return hass.states.get(entity_id)


async def test_server_device_and_tv_link(hass: HomeAssistant, loaded) -> None:
    devices = dr.async_get(hass)
    server = devices.async_get_device(identifiers={("silo", SERVER_ID)})
    assert server.name == "Silo server"
    assert server.sw_version == "6144c45c"
    tv = next(
        d for d in dr.async_entries_for_config_entry(devices, loaded.entry_id) if d.id != server.id
    )
    assert tv.via_device_id == server.id


async def test_server_sensors(hass: HomeAssistant, loaded) -> None:
    assert _state(hass, "movies").state == "684"
    assert _state(hass, "shows").state == "168"
    assert _state(hass, "episodes").state == "5480"
    storage = _state(hass, "storage")
    assert storage.attributes["unit_of_measurement"] == "TB"
    assert float(storage.state) == pytest.approx(24.22, abs=0.01)
    assert _state(hass, "requests_pending").state == "2"
    running = _state(hass, "running_tasks")
    assert running.state == "1"
    assert running.attributes["tasks"][0]["key"] == "refresh_metadata"
    assert _state(hass, "last_library_scan").state.startswith("2026-10-14T01:00:00")
    streams = _state(hass, "active_streams")
    assert streams.state == "1"
    assert streams.attributes["sessions"][0]["title"] == "Peppa Pig – Teddy's Day Out"
    assert _state(hass, "transcodes").state == "0"
    # Disabled by default.
    assert er.async_get(hass).async_get_entity_id("sensor", "silo", f"{SERVER_ID}_titles")
    assert hass.states.get("sensor.silo_server_titles") is None


async def test_buttons(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, loaded) -> None:
    aioclient_mock.post(f"{API}/admin/tasks/scan_libraries/run", json={"key": "scan_libraries"})
    aioclient_mock.post(f"{API}/scan", status=202, json={"status": "accepted"})
    aioclient_mock.post(f"{API}/admin/server/restart", json={"status": "restart_requested"})

    for key in ("scan_all", "scan_library_2", "restart"):
        await hass.services.async_call(
            "button", "press", {"entity_id": _state(hass, key, "button").entity_id}, blocking=True
        )
    posts = [(str(c[1]), c[2]) for c in aioclient_mock.mock_calls if c[0].lower() == "post"]
    assert (f"{API}/admin/tasks/scan_libraries/run", None) in posts
    assert (f"{API}/scan", {"library_id": "2"}) in posts
    assert any(url.endswith("/admin/server/restart") for url, _ in posts)
    assert _state(hass, "scan_library_2", "button").name == "Silo server Scan TV"


async def test_run_task(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, loaded) -> None:
    aioclient_mock.post(f"{API}/admin/tasks/database_maintenance/run", json={"key": "database_maintenance", "state": "running"})
    result = await hass.services.async_call(
        "silo", "run_task", {"task_key": "database_maintenance"}, blocking=True, return_response=True
    )
    assert result["task"]["state"] == "running"

    aioclient_mock.post(f"{API}/admin/tasks/nope/run", status=404, json={"detail": "not found"})
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("silo", "run_task", {"task_key": "nope"}, blocking=True)


async def test_non_admin_key_gets_no_admin_entities(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, adb_tv, silo_entry
) -> None:
    for path in ("admin/sessions", "admin/stats", "admin/requests/counts", "admin/tasks", "libraries"):
        aioclient_mock.get(f"{API}/{path}", status=403, json={"detail": "admin only"})
    aioclient_mock.get(f"{API}/system/identity", json={"server_id": SERVER_ID})
    aioclient_mock.get(f"{API}/profiles", json={"items": []})
    aioclient_mock.get(f"{API}/system/info", json={"server_version": "x"})
    assert await hass.config_entries.async_setup(silo_entry.entry_id)
    await hass.async_block_till_done()
    ents = er.async_entries_for_config_entry(er.async_get(hass), silo_entry.entry_id)
    assert sorted(e.domain for e in ents) == ["media_player"]
