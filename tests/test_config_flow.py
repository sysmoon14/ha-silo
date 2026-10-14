"""Config and options flow tests."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .conftest import ADB, API, ROSA, SERVER_ID, TV_IP, URL, mock_silo


async def test_user_flow(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, adb_tv) -> None:
    mock_silo(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        "silo", context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": "silo.local:8090/", "api_key": " sa_test "}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "profile"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"profile_id": ROSA, "tvs": [ADB]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.unique_id == SERVER_ID
    assert entry.data == {"url": URL, "api_key": "sa_test"}
    assert entry.options["profile_id"] == ROSA
    assert entry.options["tvs"] == [
        {"adb_entity_id": ADB, "name": "Living Room TV", "client_ip": TV_IP}
    ]
    # The key is sent as a bearer token.
    headers = aioclient_mock.mock_calls[0][3]
    assert headers["Authorization"] == "Bearer sa_test"


async def test_user_flow_bad_key(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(
        f"{API}/system/identity", status=401, json={"detail": "Authentication is required."}
    )
    result = await hass.config_entries.flow.async_init(
        "silo", context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": URL, "api_key": "nope"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_options_flow(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, adb_tv, silo_entry
) -> None:
    mock_silo(aioclient_mock)
    assert await hass.config_entries.async_setup(silo_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(silo_entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"profile_id": ROSA, "tvs": [ADB], "wake_delay": 3}
    )
    assert result["step_id"] == "tvs"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {ADB: "10.0.0.9"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert silo_entry.options["wake_delay"] == 3
    assert silo_entry.options["tvs"][0]["client_ip"] == "10.0.0.9"
