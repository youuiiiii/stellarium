"""``stella connect`` / ``hermes connect`` subcommand parser."""

from __future__ import annotations

from typing import Callable


def build_connect_parser(subparsers, *, cmd_connect: Callable) -> None:
    """Attach the ``connect`` subcommand to ``subparsers``."""
    connect_parser = subparsers.add_parser(
        "connect",
        help="Connect external services (Spotify, MyAnimeList) with zero manual config",
        description="Intuitive OAuth & account connector for Stella services",
    )
    connect_parser.add_argument(
        "target",
        nargs="?",
        choices=["spotify", "mal", "myanimelist", "music", "status"],
        default="status",
        help="Service to connect (spotify, mal, or status)",
    )
    connect_parser.add_argument(
        "--client-id",
        help="Custom OAuth Client ID (optional; defaults are bundled)",
    )
    connect_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not auto-open the browser (print URL only)",
    )
    connect_parser.set_defaults(func=cmd_connect)
