"""Native MyAnimeList tools for Hermes (registered via plugins/mal)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from hermes_cli.config import get_hermes_home
from plugins.mal.client import (
    MALAPIError,
    MALAuthRequiredError,
    MALClient,
    MALError,
)
from tools.registry import tool_error, tool_result


def _check_mal_available() -> bool:
    try:
        tokens_path = get_hermes_home() / "mal" / "tokens.json"
        if not tokens_path.exists():
            return False
        with open(tokens_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return bool(data.get("access_token"))
    except Exception:
        return False


def _mal_client() -> MALClient:
    return MALClient()


def _mal_tool_error(exc: Exception) -> str:
    if isinstance(exc, (MALError, MALAuthRequiredError)):
        return tool_error(str(exc))
    if isinstance(exc, MALAPIError):
        return tool_error(str(exc), status_code=exc.status_code)
    return tool_error(f"MyAnimeList tool failed: {type(exc).__name__}: {exc}")


def _coerce_int(raw: Any, default: int, minimum: int = 1, maximum: int = 100) -> int:
    try:
        val = int(raw)
        return max(minimum, min(maximum, val))
    except Exception:
        return default


def _current_year_and_season() -> tuple[int, str]:
    now = datetime.now()
    month = now.month
    if month in (1, 2, 3):
        season = "winter"
    elif month in (4, 5, 6):
        season = "spring"
    elif month in (7, 8, 9):
        season = "summer"
    else:
        season = "fall"
    return now.year, season


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def _handle_mal_anime_search(args: dict, **kw) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        return tool_error("query is required for anime search")
    limit = _coerce_int(args.get("limit"), default=10, minimum=1, maximum=50)
    offset = max(0, int(args.get("offset") or 0))
    fields = args.get("fields")

    client = _mal_client()
    try:
        result = client.search_anime(query, limit=limit, offset=offset, fields=fields)
        return tool_result(result)
    except Exception as exc:
        return _mal_tool_error(exc)


def _handle_mal_user_animelist(args: dict, **kw) -> str:
    username = str(args.get("username") or "@me").strip()
    status = args.get("status")
    if status:
        status = str(status).strip().lower()
        allowed_status = {"watching", "completed", "on_hold", "dropped", "plan_to_watch"}
        if status not in allowed_status:
            return tool_error(f"status must be one of: {', '.join(sorted(allowed_status))}")

    sort = args.get("sort")
    limit = _coerce_int(args.get("limit"), default=20, minimum=1, maximum=100)
    offset = max(0, int(args.get("offset") or 0))
    fields = args.get("fields")

    client = _mal_client()
    try:
        result = client.get_user_animelist(
            username=username,
            status=status,
            sort=sort,
            limit=limit,
            offset=offset,
            fields=fields,
        )
        return tool_result(result)
    except Exception as exc:
        return _mal_tool_error(exc)


def _handle_mal_anime_details(args: dict, **kw) -> str:
    anime_id_raw = args.get("anime_id")
    if anime_id_raw is None:
        return tool_error("anime_id is required")
    try:
        anime_id = int(anime_id_raw)
    except Exception:
        return tool_error("anime_id must be an integer")

    fields = args.get("fields")
    client = _mal_client()
    try:
        result = client.get_anime_details(anime_id, fields=fields)
        return tool_result(result)
    except Exception as exc:
        return _mal_tool_error(exc)


def _handle_mal_update_animelist(args: dict, **kw) -> str:
    anime_id_raw = args.get("anime_id")
    if anime_id_raw is None:
        return tool_error("anime_id is required")
    try:
        anime_id = int(anime_id_raw)
    except Exception:
        return tool_error("anime_id must be an integer")

    status = args.get("status")
    if status is not None:
        status = str(status).strip().lower()

    num_watched_episodes = args.get("num_watched_episodes")
    if num_watched_episodes is not None:
        try:
            num_watched_episodes = int(num_watched_episodes)
        except Exception:
            return tool_error("num_watched_episodes must be an integer")

    score = args.get("score")
    if score is not None:
        try:
            score = int(score)
            if score < 0 or score > 10:
                return tool_error("score must be between 0 and 10")
        except Exception:
            return tool_error("score must be an integer between 0 and 10")

    is_rewatching = args.get("is_rewatching")
    if is_rewatching is not None:
        is_rewatching = bool(is_rewatching)

    priority = args.get("priority")
    if priority is not None:
        try:
            priority = int(priority)
        except Exception:
            return tool_error("priority must be an integer (0, 1, or 2)")

    tags = args.get("tags")
    comments = args.get("comments")

    client = _mal_client()
    try:
        result = client.update_user_animelist(
            anime_id=anime_id,
            status=status,
            is_rewatching=is_rewatching,
            score=score,
            num_watched_episodes=num_watched_episodes,
            priority=priority,
            tags=tags,
            comments=comments,
        )
        return tool_result(result)
    except Exception as exc:
        return _mal_tool_error(exc)


def _handle_mal_seasonal_anime(args: dict, **kw) -> str:
    current_year, current_season = _current_year_and_season()

    year_raw = args.get("year")
    year = int(year_raw) if year_raw is not None else current_year

    season = str(args.get("season") or current_season).strip().lower()
    allowed_seasons = {"winter", "spring", "summer", "fall"}
    if season not in allowed_seasons:
        return tool_error(f"season must be one of: {', '.join(sorted(allowed_seasons))}")

    sort = str(args.get("sort") or "anime_score").strip()
    limit = _coerce_int(args.get("limit"), default=20, minimum=1, maximum=100)
    offset = max(0, int(args.get("offset") or 0))
    fields = args.get("fields")

    client = _mal_client()
    try:
        result = client.get_seasonal_anime(
            year=year,
            season=season,
            sort=sort,
            limit=limit,
            offset=offset,
            fields=fields,
        )
        return tool_result(result)
    except Exception as exc:
        return _mal_tool_error(exc)


def _handle_mal_delete_animelist(args: dict, **kw) -> str:
    anime_id_raw = args.get("anime_id")
    if anime_id_raw is None:
        return tool_error("anime_id is required")
    try:
        anime_id = int(anime_id_raw)
    except Exception:
        return tool_error("anime_id must be an integer")

    client = _mal_client()
    try:
        result = client.delete_user_animelist(anime_id=anime_id)
        return tool_result(result)
    except Exception as exc:
        return _mal_tool_error(exc)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

MAL_ANIME_SEARCH_SCHEMA = {
    "name": "mal_anime_search",
    "description": "Search MyAnimeList anime database by title or keyword. Returns anime IDs, titles, scores, episode counts, airing status, and user's current list status.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Anime title, romaji name, or search keyword (e.g. 'Bocchi the Rock', 'Frieren').",
            },
            "limit": {
                "type": "integer",
                "description": "Number of results to return (default 10, max 50).",
            },
            "offset": {
                "type": "integer",
                "description": "Pagination offset (default 0).",
            },
            "fields": {
                "type": "string",
                "description": "Optional comma-separated MAL fields.",
            },
        },
        "required": ["query"],
    },
}

MAL_USER_ANIMELIST_SCHEMA = {
    "name": "mal_user_animelist",
    "description": "Fetch user's anime list from MyAnimeList with status, episodes watched, and score. Defaults to authenticated user (@me).",
    "parameters": {
        "type": "object",
        "properties": {
            "username": {
                "type": "string",
                "description": "MAL username, or '@me' for Master's list (default '@me').",
            },
            "status": {
                "type": "string",
                "enum": ["watching", "completed", "on_hold", "dropped", "plan_to_watch"],
                "description": "Filter by watch status.",
            },
            "sort": {
                "type": "string",
                "enum": ["list_score", "list_updated_at", "anime_title", "anime_start_date"],
                "description": "Sort order.",
            },
            "limit": {
                "type": "integer",
                "description": "Number of entries to return (default 20, max 100).",
            },
            "offset": {
                "type": "integer",
                "description": "Pagination offset (default 0).",
            },
            "fields": {
                "type": "string",
                "description": "Optional comma-separated fields to return.",
            },
        },
    },
}

MAL_ANIME_DETAILS_SCHEMA = {
    "name": "mal_anime_details",
    "description": "Get detailed information about a specific anime from MyAnimeList (synopsis, studios, genres, score, episodes, broadcast, etc.).",
    "parameters": {
        "type": "object",
        "properties": {
            "anime_id": {
                "type": "integer",
                "description": "The MyAnimeList Anime ID.",
            },
            "fields": {
                "type": "string",
                "description": "Optional comma-separated fields.",
            },
        },
        "required": ["anime_id"],
    },
}

MAL_UPDATE_ANIMELIST_SCHEMA = {
    "name": "mal_update_animelist",
    "description": "Add or update an anime in Master's MyAnimeList (update watched episodes, change status, set rating score 1-10, comments).",
    "parameters": {
        "type": "object",
        "properties": {
            "anime_id": {
                "type": "integer",
                "description": "The MyAnimeList Anime ID to update or add.",
            },
            "status": {
                "type": "string",
                "enum": ["watching", "completed", "on_hold", "dropped", "plan_to_watch"],
                "description": "Watch status.",
            },
            "num_watched_episodes": {
                "type": "integer",
                "description": "Number of episodes watched so far.",
            },
            "score": {
                "type": "integer",
                "description": "User rating score (0 to 10; 0 means unrated).",
            },
            "is_rewatching": {
                "type": "boolean",
                "description": "Whether the user is rewatching this anime.",
            },
            "priority": {
                "type": "integer",
                "enum": [0, 1, 2],
                "description": "List priority: 0 (Low), 1 (Medium), 2 (High).",
            },
            "tags": {
                "type": "string",
                "description": "Comma-separated tags.",
            },
            "comments": {
                "type": "string",
                "description": "User notes or comments for this anime.",
            },
        },
        "required": ["anime_id"],
    },
}

MAL_SEASONAL_ANIME_SCHEMA = {
    "name": "mal_seasonal_anime",
    "description": "Browse seasonal anime from MyAnimeList for a specific year and season.",
    "parameters": {
        "type": "object",
        "properties": {
            "year": {
                "type": "integer",
                "description": "Year (defaults to current year).",
            },
            "season": {
                "type": "string",
                "enum": ["winter", "spring", "summer", "fall"],
                "description": "Season (defaults to current season).",
            },
            "sort": {
                "type": "string",
                "enum": ["anime_score", "anime_num_list_users"],
                "description": "Sort order (default 'anime_score').",
            },
            "limit": {
                "type": "integer",
                "description": "Number of entries to return (default 20, max 100).",
            },
            "offset": {
                "type": "integer",
                "description": "Pagination offset.",
            },
        },
    },
}

MAL_DELETE_ANIMELIST_SCHEMA = {
    "name": "mal_delete_animelist",
    "description": "Delete an anime from Master's MyAnimeList.",
    "parameters": {
        "type": "object",
        "properties": {
            "anime_id": {
                "type": "integer",
                "description": "The MyAnimeList Anime ID to remove from user list.",
            },
        },
        "required": ["anime_id"],
    },
}
