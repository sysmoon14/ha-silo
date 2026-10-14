"""Small async client for the Silo server API (v2)."""

from __future__ import annotations

from json import loads as json_loads
import time
import uuid
from typing import Any
from urllib.parse import quote

import aiohttp

API = "/api/v2"
TIMEOUT = aiohttp.ClientTimeout(total=15)


class SiloError(Exception):
    """Base error for Silo API failures."""


class SiloConnectionError(SiloError):
    """The server could not be reached."""


class SiloAuthError(SiloError):
    """The API key was missing, malformed or rejected."""


class SiloApiError(SiloError):
    """The server answered with an error."""

    def __init__(self, status: int, detail: str, headers: Any = None) -> None:
        super().__init__(f"Silo API error {status}: {detail}")
        self.status = status
        self.detail = detail
        self.headers = headers or {}


def content_kind(content_id: str) -> str:
    """Return the kind of a Silo content id: movie, series, season, episode..."""
    return content_id.split("-", 1)[0] if "-" in content_id else content_id


def _seg(value: str) -> str:
    return quote(str(value), safe="")


class SiloClient:
    """Thin wrapper over the endpoints the integration uses."""

    def __init__(self, session: aiohttp.ClientSession, url: str, api_key: str) -> None:
        self._session = session
        self.url = url.rstrip("/")
        self._api_key = api_key.strip()
        self._last_sequence = 0

    def absolute(self, path: str | None) -> str | None:
        """Turn a server-relative artwork path into an absolute URL."""
        if not path:
            return None
        if path.startswith(("http://", "https://")):
            return path
        return f"{self.url}{path}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        profile_id: str | None = None,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        if profile_id:
            headers["X-Profile-Id"] = profile_id
        try:
            async with self._session.request(
                method,
                f"{self.url}{API}{path}",
                headers=headers,
                params=params,
                json=json,
                timeout=TIMEOUT,
            ) as resp:
                text = await resp.text()
                if resp.status == 401:
                    raise SiloAuthError(_detail(text, resp.status))
                if resp.status >= 400:
                    raise SiloApiError(resp.status, _detail(text, resp.status), resp.headers)
                if resp.status == 204 or not text.strip():
                    return None
                return json_loads(text)
        except (TimeoutError, aiohttp.ClientError, ValueError) as err:
            raise SiloConnectionError(str(err) or type(err).__name__) from err

    # Server and account -------------------------------------------------

    async def identity(self) -> dict[str, Any]:
        return await self._request("GET", "/system/identity")

    async def profiles(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/profiles")
        return data.get("items", [])

    # Live sessions (admin) ----------------------------------------------

    async def sessions(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        params: dict[str, Any] = {"limit": 100}
        for _ in range(10):
            data = await self._request("GET", "/admin/sessions", params=params)
            items.extend(data.get("items", []))
            page = data.get("page") or {}
            if not page.get("has_more") or not page.get("next_cursor"):
                break
            params = {"limit": 100, "cursor": page["next_cursor"]}
        return items

    def _next_sequence(self) -> int:
        self._last_sequence = max(int(time.time() * 1000), self._last_sequence + 1)
        return self._last_sequence

    async def session_command(self, session_id: str, action: str) -> None:
        """Send pause, resume or stop to a live session."""
        path = f"/admin/sessions/{_seg(session_id)}/{action}"
        body = {"command_id": str(uuid.uuid4()), "sequence": self._next_sequence()}
        try:
            await self._request("POST", path, json=body)
        except SiloApiError as err:
            latest = err.headers.get("X-Silo-Latest-Sequence") if err.status == 409 else None
            if not latest:
                raise
            self._last_sequence = max(self._last_sequence, int(latest))
            body = {"command_id": str(uuid.uuid4()), "sequence": self._next_sequence()}
            await self._request("POST", path, json=body)

    # Catalog -------------------------------------------------------------

    async def libraries(self, profile_id: str | None) -> list[dict[str, Any]]:
        data = await self._request("GET", "/user/libraries", profile_id=profile_id)
        return data.get("items", [])

    async def catalog_page(
        self,
        profile_id: str | None,
        *,
        library_id: str | None = None,
        query: str | None = None,
        media_type: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
        sort: str | None = "title",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "skip_total": "true", "image_size": "small"}
        if library_id:
            params["library_id"] = library_id
        if query:
            params["q"] = query
            sort = None
        if media_type:
            params["type"] = media_type
        if sort:
            params["sort"] = sort
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/catalog", profile_id=profile_id, params=params)

    async def item(self, profile_id: str | None, content_id: str) -> dict[str, Any]:
        return await self._request(
            "GET", f"/catalog/items/{_seg(content_id)}", profile_id=profile_id
        )

    async def seasons(self, profile_id: str | None, series_id: str) -> list[dict[str, Any]]:
        data = await self._request(
            "GET", f"/catalog/series/{_seg(series_id)}/seasons", profile_id=profile_id
        )
        return data.get("items", [])

    async def episodes(
        self, profile_id: str | None, series_id: str, season: int | str
    ) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            f"/catalog/series/{_seg(series_id)}/seasons/{_seg(season)}/episodes",
            profile_id=profile_id,
        )
        return data.get("items", [])

    # Playback helpers ----------------------------------------------------

    async def shuffle_pick(self, profile_id: str | None, scope_id: str) -> dict[str, Any]:
        """Ask the server for a random playable item in a series or season."""
        kind = content_kind(scope_id)
        if kind not in ("series", "season"):
            raise SiloApiError(422, f"{scope_id} is not a series or season")
        data = await self._request(
            "POST",
            "/shuffles",
            profile_id=profile_id,
            json={"scope": {"kind": kind, "id": scope_id}},
        )
        current = (data or {}).get("current") or {}
        if not current.get("content_id"):
            raise SiloApiError(500, "shuffle returned no pick")
        # The shuffle record is only used for its first pick; tidy it away.
        if data.get("id"):
            try:
                await self._request(
                    "DELETE", f"/shuffles/{_seg(data['id'])}", profile_id=profile_id
                )
            except SiloError:
                pass
        return current

    async def mark_unwatched(self, profile_id: str | None, content_id: str) -> None:
        """Clear watched state and the resume point for a profile."""
        await self._request("DELETE", f"/watched/{_seg(content_id)}", profile_id=profile_id)


def _detail(text: str, status: int) -> str:
    try:
        data = json_loads(text)
    except ValueError:
        return text.strip()[:200] or f"HTTP {status}"
    if isinstance(data, dict):
        return str(data.get("detail") or data.get("message") or data.get("title") or data)
    return str(data)
