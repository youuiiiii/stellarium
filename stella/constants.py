"""Constants and defaults for Stella / Stellarium core architecture."""

import os
import sys
from pathlib import Path


def get_default_stella_home() -> Path:
    """Return platform-default Stella home path (e.g. %LOCALAPPDATA%/stella or ~/.stella)."""
    env_stella = os.environ.get("STELLA_HOME", "").strip()
    if env_stella:
        # Keep the lexical path here. Resolving before the profile manager
        # checks it would follow a junction/reparse point and erase the
        # boundary evidence that the manager is meant to reject.
        return Path(os.path.abspath(os.fspath(Path(env_stella).expanduser())))

    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
        return Path(os.path.abspath(os.fspath(base / "stella")))
    return Path(os.path.abspath(os.fspath(Path.home() / ".stella")))


STELLA_PROFILES_DIR_NAME = "profiles"
STELLA_SHARED_DIR_NAME = "shared"
STELLA_CACHE_DIR_NAME = "cache"

PROFILE_METADATA_FILE = "profile.json"
MIGRATION_MANIFEST_FILE = "migration_manifest.json"
STELLA_ACTIVE_PROFILE_FILE = "active_profile"

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
