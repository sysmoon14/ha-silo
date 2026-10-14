"""Media browser tree for Silo: home rows, collections and libraries."""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import BrowseError, BrowseMedia, MediaClass, MediaType

from .api import SiloClient, SiloError, content_kind
from .const import BROWSE_PREFIX

MAX_LIBRARY_ITEMS = 1000
PAGE_SIZE = 200
VIDEO_LIBRARY_TYPES = ("movies", "series")


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
    kind = item.get("type") or content_kind(item.get("content_id", ""))
    if kind == "episode":
        series = item.get("series_title")
        season, episode = item.get("season_number"), item.get("episode_number")
        code = f"S{season:02d}E{episode:02d} " if isinstance(season, int) and isinstance(episode, int) else ""
        return f"{series} – {code}{title}" if series else f"{code}{title}"
    year = item.get("year")
    return f"{title} ({year})" if year and kind == "movie" else title


def _folder(title: str, media_id: str, children=None, *, thumbnail=None,
            children_class=MediaClass.DIRECTORY) -> BrowseMedia:
    return BrowseMedia(
        title=title,
        media_class=MediaClass.DIRECTORY,
        media_content_id=media_id,
        media_content_type=MediaType.CHANNELS,
        can_play=False,
        can_expand=True,
        children=children,
        children_media_class=children_class,
        thumbnail=thumbnail,
    )


def item_node(client: SiloClient, item: dict[str, Any]) -> BrowseMedia | None:
    """A playable node for a catalog item; series and seasons also expand."""
    content_id = item.get("content_id")
    if not content_id:
        return None
    kind = item.get("type") or content_kind(content_id)
    media_class, media_type = _class_for(kind)
    thumb = client.absolute(item.get("poster_url") or item.get("still_url"))
    if kind == "series":
        return BrowseMedia(
            title=_title(item), media_class=media_class,
            media_content_id=node_id("series", content_id), media_content_type=media_type,
            can_play=True, can_expand=True, thumbnail=thumb,  # play = random episode
        )
    if kind in ("movie", "episode"):
        return BrowseMedia(
            title=_title(item), media_class=media_class,
            media_content_id=content_id, media_content_type=media_type,
            can_play=True, can_expand=False, thumbnail=thumb,
        )
    return None  # audiobooks, ebooks etc. aren't playable on the TV app this way


def _items(client: SiloClient, items: list[dict[str, Any]]) -> list[BrowseMedia]:
    return [node for item in items if (node := item_node(client, item)) is not None]


async def async_browse(
    client: SiloClient, profile_id: str | None, media_id: str | None
) -> BrowseMedia:
    """Return the browse node for media_id (None is the root)."""
    try:
        if not media_id or media_id == BROWSE_PREFIX.rstrip("/"):
            return await _root(client, profile_id)
        parts = media_id[len(BROWSE_PREFIX) :].split("/")
        match parts:
            case ["home"]:
                return await _home(client, profile_id)
            case ["section", section_id]:
                return await _section(client, profile_id, section_id)
            case ["collections"]:
                return await _collections(client, profile_id)
            case ["collection", library_id, collection_id]:
                return await _collection(client, profile_id, library_id, collection_id)
            case ["library", library_id, lib_type]:
                return await _library(client, profile_id, library_id, lib_type)
            case ["series", series_id]:
                return await _series(client, profile_id, series_id)
            case ["season", series_id, number, season_id]:
                return await _season(client, profile_id, series_id, number, season_id)
    except SiloError as err:
        raise BrowseError(f"Silo: {err}") from err
    raise BrowseError(f"Unknown Silo browse id {media_id}")


async def _root(client: SiloClient, profile_id: str | None) -> BrowseMedia:
    libraries = [
        lib for lib in await client.libraries(profile_id)
        if lib.get("type") in VIDEO_LIBRARY_TYPES
    ]
    children = [
        _folder("Home", node_id("home")),
        _folder("Collections", node_id("collections")),
    ] + [
        _folder(
            lib.get("name", lib["id"]),
            node_id("library", lib["id"], lib["type"]),
            children_class=MediaClass.MOVIE if lib["type"] == "movies" else MediaClass.TV_SHOW,
        )
        for lib in libraries
    ]
    return _folder("Silo", BROWSE_PREFIX.rstrip("/"), children)


async def _home(client: SiloClient, profile_id: str | None) -> BrowseMedia:
    sections = await client.home_sections(profile_id)
    children = []
    for section in sections:
        playable = _items(client, section.get("items") or [])
        if not playable and not section.get("total_count"):
            continue  # empty row, e.g. Continue Listening with no audiobooks
        if not playable and section.get("items"):
            continue  # row only holds things the TV can't play
        thumb = playable[0].thumbnail if playable else None
        children.append(
            _folder(section.get("title") or "Untitled", node_id("section", section["id"]),
                    thumbnail=thumb, children_class=MediaClass.VIDEO)
        )
    return _folder("Home", node_id("home"), children)


async def _section(client: SiloClient, profile_id: str | None, section_id: str) -> BrowseMedia:
    sections = await client.home_sections(profile_id)
    section = next((s for s in sections if str(s.get("id")) == section_id), None)
    if section is None:
        raise BrowseError("That home row no longer exists")
    items = section.get("items") or []
    if section.get("total_count", 0) > len(items):
        try:
            items = await client.home_section_items(profile_id, section_id) or items
        except SiloError:
            pass  # fall back to the rows already shown on the home screen
    return _folder(section.get("title") or "Untitled", node_id("section", section_id),
                   _items(client, items), children_class=MediaClass.VIDEO)


async def _collections(client: SiloClient, profile_id: str | None) -> BrowseMedia:
    children = []
    for lib in await client.libraries(profile_id):
        if lib.get("type") not in VIDEO_LIBRARY_TYPES:
            continue
        for coll in await client.library_collections(profile_id, lib["id"]):
            if not coll.get("item_count") or coll.get("visibility", "visible") != "visible":
                continue
            children.append(
                _folder(
                    coll.get("title", coll["id"]),
                    node_id("collection", lib["id"], coll["id"]),
                    thumbnail=client.absolute(coll.get("poster_url") or None),
                    children_class=MediaClass.VIDEO,
                )
            )
    return _folder("Collections", node_id("collections"), children)


async def _collection(
    client: SiloClient, profile_id: str | None, library_id: str, collection_id: str
) -> BrowseMedia:
    items = await client.collection_items(profile_id, library_id, collection_id)
    title = next(
        (c.get("title") for c in await client.library_collections(profile_id, library_id)
         if str(c.get("id")) == collection_id),
        "Collection",
    )
    return _folder(title, node_id("collection", library_id, collection_id),
                   _items(client, items), children_class=MediaClass.VIDEO)


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
    return _folder(
        "Library",
        node_id("library", library_id, lib_type),
        _items(client, items),
        children_class=MediaClass.MOVIE if lib_type == "movies" else MediaClass.TV_SHOW,
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
