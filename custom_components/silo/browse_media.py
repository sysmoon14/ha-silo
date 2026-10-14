"""Media browser tree for Silo libraries."""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import BrowseError, BrowseMedia, MediaClass, MediaType

from .api import SiloClient, SiloError, content_kind
from .const import BROWSE_PREFIX

MAX_LIBRARY_ITEMS = 1000
PAGE_SIZE = 200


def node_id(*parts: str) -> str:
    """Build a browse id like silo://library/2."""
    return BROWSE_PREFIX + "/".join(str(p) for p in parts)


def playable_id(media_id: str) -> str:
    """Map any browse id or raw content id to the Silo content id to play."""
    if not media_id.startswith(BROWSE_PREFIX):
        return media_id
    parts = media_id[len(BROWSE_PREFIX) :].split("/")
    if parts[0] == "series" and len(parts) == 2:
        return parts[1]
    if parts[0] == "season" and len(parts) == 4:
        return parts[3]
    raise BrowseError(f"{media_id} can't be played")


def _class_for(kind: str) -> tuple[MediaClass, str]:
    return {
        "movie": (MediaClass.MOVIE, MediaType.MOVIE),
        "series": (MediaClass.TV_SHOW, MediaType.TVSHOW),
        "season": (MediaClass.SEASON, MediaType.SEASON),
        "episode": (MediaClass.EPISODE, MediaType.EPISODE),
    }.get(kind, (MediaClass.VIDEO, MediaType.VIDEO))


def _title(item: dict[str, Any]) -> str:
    title = item.get("title") or item.get("content_id", "?")
    year = item.get("year")
    return f"{title} ({year})" if year and item.get("type") == "movie" else title


async def async_browse(
    client: SiloClient, profile_id: str | None, media_id: str | None
) -> BrowseMedia:
    """Return the browse node for media_id (None is the root)."""
    try:
        if not media_id or media_id == BROWSE_PREFIX.rstrip("/"):
            return await _root(client, profile_id)
        parts = media_id[len(BROWSE_PREFIX) :].split("/")
        if parts[0] == "library" and len(parts) == 3:
            return await _library(client, profile_id, parts[1], parts[2])
        if parts[0] == "series" and len(parts) == 2:
            return await _series(client, profile_id, parts[1])
        if parts[0] == "season" and len(parts) == 4:
            return await _season(client, profile_id, parts[1], parts[2], parts[3])
    except SiloError as err:
        raise BrowseError(f"Silo: {err}") from err
    raise BrowseError(f"Unknown Silo browse id {media_id}")


async def _root(client: SiloClient, profile_id: str | None) -> BrowseMedia:
    libraries = await client.libraries(profile_id)
    children = [
        BrowseMedia(
            title=lib.get("name", lib["id"]),
            media_class=MediaClass.DIRECTORY,
            media_content_id=node_id("library", lib["id"], lib.get("type", "")),
            media_content_type=MediaType.CHANNELS,
            can_play=False,
            can_expand=True,
            children_media_class=(
                MediaClass.MOVIE if lib.get("type") == "movies" else MediaClass.TV_SHOW
            ),
        )
        for lib in libraries
        if lib.get("type") in ("movies", "series")
    ]
    return BrowseMedia(
        title="Silo",
        media_class=MediaClass.DIRECTORY,
        media_content_id=BROWSE_PREFIX.rstrip("/"),
        media_content_type=MediaType.CHANNELS,
        can_play=False,
        can_expand=True,
        children=children,
        children_media_class=MediaClass.DIRECTORY,
    )


async def _library(
    client: SiloClient, profile_id: str | None, library_id: str, lib_type: str
) -> BrowseMedia:
    items: list[dict[str, Any]] = []
    cursor = None
    while len(items) < MAX_LIBRARY_ITEMS:
        page = await client.catalog_page(
            profile_id, library_id=library_id, cursor=cursor, limit=PAGE_SIZE
        )
        items.extend(page.get("items", []))
        nxt = page.get("page") or {}
        cursor = nxt.get("next_cursor")
        if not nxt.get("has_more") or not cursor:
            break

    children = []
    for item in items:
        kind = item.get("type") or content_kind(item["content_id"])
        media_class, media_type = _class_for(kind)
        if kind == "series":
            children.append(
                BrowseMedia(
                    title=_title(item),
                    media_class=media_class,
                    media_content_id=node_id("series", item["content_id"]),
                    media_content_type=media_type,
                    can_play=True,  # plays a random episode
                    can_expand=True,
                    thumbnail=client.absolute(item.get("poster_url")),
                )
            )
        else:
            children.append(
                BrowseMedia(
                    title=_title(item),
                    media_class=media_class,
                    media_content_id=item["content_id"],
                    media_content_type=media_type,
                    can_play=True,
                    can_expand=False,
                    thumbnail=client.absolute(item.get("poster_url")),
                )
            )
    return BrowseMedia(
        title="Library",
        media_class=MediaClass.DIRECTORY,
        media_content_id=node_id("library", library_id, lib_type),
        media_content_type=MediaType.CHANNELS,
        can_play=False,
        can_expand=True,
        children=children,
        children_media_class=MediaClass.MOVIE if lib_type == "movies" else MediaClass.TV_SHOW,
    )


async def _series(client: SiloClient, profile_id: str | None, series_id: str) -> BrowseMedia:
    seasons = await client.seasons(profile_id, series_id)
    children = [
        BrowseMedia(
            title=season.get("title") or f"Season {season['season_number']}",
            media_class=MediaClass.SEASON,
            media_content_id=node_id(
                "season", series_id, season["season_number"], season["content_id"]
            ),
            media_content_type=MediaType.SEASON,
            can_play=True,  # plays a random episode of the season
            can_expand=True,
            thumbnail=client.absolute(season.get("poster_url")),
        )
        for season in seasons
    ]
    return BrowseMedia(
        title="Seasons",
        media_class=MediaClass.TV_SHOW,
        media_content_id=node_id("series", series_id),
        media_content_type=MediaType.TVSHOW,
        can_play=True,
        can_expand=True,
        children=children,
        children_media_class=MediaClass.SEASON,
    )


async def _season(
    client: SiloClient, profile_id: str | None, series_id: str, number: str, season_id: str
) -> BrowseMedia:
    episodes = await client.episodes(profile_id, series_id, number)
    children = [
        BrowseMedia(
            title=f"{ep.get('episode_number', '?')}. {ep.get('title', '')}".strip(),
            media_class=MediaClass.EPISODE,
            media_content_id=ep["content_id"],
            media_content_type=MediaType.EPISODE,
            can_play=True,
            can_expand=False,
            thumbnail=client.absolute(ep.get("still_url")),
        )
        for ep in episodes
    ]
    return BrowseMedia(
        title=f"Season {number}",
        media_class=MediaClass.SEASON,
        media_content_id=node_id("season", series_id, number, season_id),
        media_content_type=MediaType.SEASON,
        can_play=True,
        can_expand=True,
        children=children,
        children_media_class=MediaClass.EPISODE,
    )
