"""Shared entity helpers."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.entity import Entity

from .api import SiloClient
from .const import DATA_TARGETS, DOMAIN


class SessionTarget(Entity):
    """An entity that silo.send_message and silo.stop_playback can target.

    Subclasses return the live Silo sessions they stand for: a TV player its
    current session, a profile sensor every session of that profile.
    """

    silo_client: SiloClient

    def silo_sessions(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        targets: set[SessionTarget] = self.hass.data.setdefault(DOMAIN, {}).setdefault(
            DATA_TARGETS, set()
        )
        targets.add(self)
        self.async_on_remove(lambda: targets.discard(self))
