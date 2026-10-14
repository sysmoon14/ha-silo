"""Config flow for Silo."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_API_KEY, CONF_URL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SiloAuthError, SiloClient, SiloConnectionError, SiloError
from .const import (
    CONF_ADB_ENTITY,
    CONF_CLIENT_IP,
    CONF_NAME,
    CONF_PROFILE_ID,
    CONF_TVS,
    CONF_WAKE_DELAY,
    DEFAULT_WAKE_DELAY,
    DOMAIN,
)

ADB_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="media_player", integration="androidtv", multiple=True)
)


async def _validate(hass: HomeAssistant, url: str, api_key: str) -> tuple[str, list[dict]]:
    client = SiloClient(async_get_clientsession(hass), url, api_key)
    identity = await client.identity()
    profiles = await client.profiles()
    return identity["server_id"], profiles


def _profile_selector(profiles: list[dict[str, Any]]) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(value=p["id"], label=p.get("name", p["id"]))
                for p in profiles
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _detect_tv(hass: HomeAssistant, entity_id: str) -> dict[str, str]:
    """Work out a friendly name and the TV's IP from its androidtv entry."""
    name, host = entity_id, ""
    if (state := hass.states.get(entity_id)) is not None:
        name = state.name
    entry = er.async_get(hass).async_get(entity_id)
    if entry and entry.config_entry_id:
        if ce := hass.config_entries.async_get_entry(entry.config_entry_id):
            host = str(ce.data.get("host", ""))
    from .media_player import clean_tv_name  # noqa: PLC0415

    return {CONF_ADB_ENTITY: entity_id, CONF_NAME: clean_tv_name(name), CONF_CLIENT_IP: host}


class SiloConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a Silo server."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._profiles: list[dict[str, Any]] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].strip().rstrip("/")
            if not url.startswith(("http://", "https://")):
                url = f"http://{url}"
            try:
                server_id, self._profiles = await _validate(self.hass, url, user_input[CONF_API_KEY])
            except SiloAuthError:
                errors["base"] = "invalid_auth"
            except SiloConnectionError:
                errors["base"] = "cannot_connect"
            except (SiloError, KeyError):
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(server_id)
                self._abort_if_unique_id_configured(updates={CONF_URL: url})
                self._data = {CONF_URL: url, CONF_API_KEY: user_input[CONF_API_KEY].strip()}
                return await self.async_step_profile()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_URL): str,
                        vol.Required(CONF_API_KEY): selector.TextSelector(
                            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                        ),
                    }
                ),
                user_input,
            ),
            errors=errors,
        )

    async def async_step_profile(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            tvs = [_detect_tv(self.hass, e) for e in user_input.get(CONF_TVS, [])]
            return self.async_create_entry(
                title="Silo",
                data=self._data,
                options={
                    CONF_PROFILE_ID: user_input[CONF_PROFILE_ID],
                    CONF_TVS: tvs,
                    CONF_WAKE_DELAY: DEFAULT_WAKE_DELAY,
                },
            )
        default = next((p["id"] for p in self._profiles if p.get("is_primary")), None)
        schema: dict[Any, Any] = {
            vol.Required(CONF_PROFILE_ID, default=default): _profile_selector(self._profiles),
            vol.Optional(CONF_TVS, default=[]): ADB_SELECTOR,
        }
        return self.async_show_form(step_id="profile", data_schema=vol.Schema(schema))

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                server_id, _ = await _validate(
                    self.hass, entry.data[CONF_URL], user_input[CONF_API_KEY]
                )
            except SiloAuthError:
                errors["base"] = "invalid_auth"
            except SiloConnectionError:
                errors["base"] = "cannot_connect"
            except (SiloError, KeyError):
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(server_id)
                self._abort_if_unique_id_mismatch(reason="wrong_server")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_KEY: user_input[CONF_API_KEY].strip()}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SiloOptionsFlow()


class SiloOptionsFlow(OptionsFlow):
    """Change profile, linked TVs and wake delay."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}
        self._tvs: list[dict[str, str]] = []

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        current = self.config_entry.options
        if user_input is not None:
            self._options = {
                CONF_PROFILE_ID: user_input[CONF_PROFILE_ID],
                CONF_WAKE_DELAY: user_input[CONF_WAKE_DELAY],
            }
            existing = {tv[CONF_ADB_ENTITY]: tv for tv in current.get(CONF_TVS, [])}
            self._tvs = [
                existing.get(e) or _detect_tv(self.hass, e) for e in user_input.get(CONF_TVS, [])
            ]
            if self._tvs:
                return await self.async_step_tvs()
            return self.async_create_entry(data={**self._options, CONF_TVS: []})

        runtime = getattr(self.config_entry, "runtime_data", None)
        profiles = [
            {"id": pid, "name": name}
            for pid, name in (runtime.profiles.items() if runtime else [])
        ] or [{"id": current.get(CONF_PROFILE_ID), "name": current.get(CONF_PROFILE_ID)}]
        schema = vol.Schema(
            {
                vol.Required(CONF_PROFILE_ID, default=current.get(CONF_PROFILE_ID)): _profile_selector(
                    profiles
                ),
                vol.Optional(
                    CONF_TVS, default=[tv[CONF_ADB_ENTITY] for tv in current.get(CONF_TVS, [])]
                ): ADB_SELECTOR,
                vol.Required(
                    CONF_WAKE_DELAY, default=current.get(CONF_WAKE_DELAY, DEFAULT_WAKE_DELAY)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=15, step=0.5, unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_tvs(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm the IP each TV shows up as in Silo's session list."""
        if user_input is not None:
            for tv in self._tvs:
                tv[CONF_CLIENT_IP] = str(user_input.get(tv[CONF_ADB_ENTITY], "")).strip()
            return self.async_create_entry(data={**self._options, CONF_TVS: self._tvs})
        schema = vol.Schema(
            {
                vol.Optional(tv[CONF_ADB_ENTITY], default=tv.get(CONF_CLIENT_IP, "")): str
                for tv in self._tvs
            }
        )
        return self.async_show_form(
            step_id="tvs",
            data_schema=schema,
            description_placeholders={
                "tvs": ", ".join(tv[CONF_NAME] for tv in self._tvs)
            },
        )
