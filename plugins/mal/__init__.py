"""MyAnimeList integration plugin for Hermes — bundled, auto-loaded."""

from __future__ import annotations

from plugins.mal.tools import (
    MAL_ANIME_DETAILS_SCHEMA,
    MAL_ANIME_SEARCH_SCHEMA,
    MAL_DELETE_ANIMELIST_SCHEMA,
    MAL_SEASONAL_ANIME_SCHEMA,
    MAL_UPDATE_ANIMELIST_SCHEMA,
    MAL_USER_ANIMELIST_SCHEMA,
    _check_mal_available,
    _handle_mal_anime_details,
    _handle_mal_anime_search,
    _handle_mal_delete_animelist,
    _handle_mal_seasonal_anime,
    _handle_mal_update_animelist,
    _handle_mal_user_animelist,
)

_TOOLS = (
    ("mal_anime_search", MAL_ANIME_SEARCH_SCHEMA, _handle_mal_anime_search, "🔎"),
    ("mal_user_animelist", MAL_USER_ANIMELIST_SCHEMA, _handle_mal_user_animelist, "📜"),
    ("mal_anime_details", MAL_ANIME_DETAILS_SCHEMA, _handle_mal_anime_details, "ℹ️"),
    ("mal_update_animelist", MAL_UPDATE_ANIMELIST_SCHEMA, _handle_mal_update_animelist, "✍️"),
    ("mal_seasonal_anime", MAL_SEASONAL_ANIME_SCHEMA, _handle_mal_seasonal_anime, "🍁"),
    ("mal_delete_animelist", MAL_DELETE_ANIMELIST_SCHEMA, _handle_mal_delete_animelist, "🗑️"),
)


def register(ctx) -> None:
    """Register all MyAnimeList tools. Called once by the plugin loader."""
    for name, schema, handler, emoji in _TOOLS:
        ctx.register_tool(
            name=name,
            toolset="mal",
            schema=schema,
            handler=handler,
            check_fn=_check_mal_available,
            emoji=emoji,
        )
