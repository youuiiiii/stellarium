"""Constants and defaults for Stella / Stellarium core architecture."""

import os
import sys
from pathlib import Path


def get_default_stella_home() -> Path:
    """Return platform-default Stella home path (e.g. %LOCALAPPDATA%/stella or ~/.stella)."""
    env_stella = os.environ.get("STELLA_HOME", "").strip()
    if env_stella:
        return Path(env_stella).expanduser().resolve()

    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
        return (base / "stella").resolve()
    return (Path.home() / ".stella").resolve()


STELLA_PROFILES_DIR_NAME = "profiles"
STELLA_SHARED_DIR_NAME = "shared"
STELLA_CACHE_DIR_NAME = "cache"

PROFILE_METADATA_FILE = "profile.json"
MIGRATION_MANIFEST_FILE = "migration_manifest.json"

DEFAULT_PRIMARY_PROFILE_ID = "stella"
DEFAULT_PRIMARY_PROFILE_NAME = "Stella"

STANDARD_PROFILE_SUBDIRS = [
    "memories",
    "sessions",
    "skills",
    "cron",
    "workspace",
    "logs",
]

SUPPORTED_MIGRATION_COMPONENTS = frozenset([
    "config",
    "soul",
    "memories",
    "skills",
    "cron",
    "sessions",
])
