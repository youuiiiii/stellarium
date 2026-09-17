"""Stella / Stellarium Core Architecture Package.

Provides:
- StellaProfileManager: Nested profile architecture under profiles/<id>/
- StellaProfileInfo: Profile metadata (display_name, id, is_primary, etc.)
- HermesMigrationEngine: 1-click, read-only, selective, rollback-safe Hermes -> Stella migration
"""

from stella.constants import (
    DEFAULT_PRIMARY_PROFILE_ID,
    DEFAULT_PRIMARY_PROFILE_NAME,
    MIGRATION_MANIFEST_FILE,
    PROFILE_METADATA_FILE,
    STANDARD_PROFILE_SUBDIRS,
    SUPPORTED_MIGRATION_COMPONENTS,
    get_default_stella_home,
)
from stella.migration import (
    ComponentPreview,
    HermesInstallationInfo,
    HermesMigrationEngine,
    MigrationManifest,
    MigrationPreview,
)
from stella.profiles import (
    StellaProfileInfo,
    StellaProfileManager,
    sanitize_profile_id,
    validate_profile_id,
)
from stella.filesystem import (
    assert_no_link_or_reparse,
    is_link_or_reparse,
)
from stella.runtime import (
    activate_profile,
    get_active_profile,
    resolve_active_profile_home,
    resolve_profile_home,
    runtime_scope,
)

__all__ = [
    "StellaProfileManager",
    "StellaProfileInfo",
    "HermesMigrationEngine",
    "HermesInstallationInfo",
    "MigrationPreview",
    "ComponentPreview",
    "MigrationManifest",
    "sanitize_profile_id",
    "validate_profile_id",
    "get_default_stella_home",
    "DEFAULT_PRIMARY_PROFILE_ID",
    "DEFAULT_PRIMARY_PROFILE_NAME",
    "PROFILE_METADATA_FILE",
    "MIGRATION_MANIFEST_FILE",
    "STANDARD_PROFILE_SUBDIRS",
    "SUPPORTED_MIGRATION_COMPONENTS",
    "assert_no_link_or_reparse",
    "is_link_or_reparse",
    "activate_profile",
    "get_active_profile",
    "resolve_active_profile_home",
    "resolve_profile_home",
    "runtime_scope",
]
