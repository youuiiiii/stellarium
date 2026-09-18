"""Bridge Stella profile identity to Hermes' existing runtime scope."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from stella.profiles import StellaProfileInfo, StellaProfileManager


def get_active_profile(root: Optional[Path | str] = None) -> Optional[StellaProfileInfo]:
    """Return the active Stella profile, with manager-defined primary fallback."""
    manager = StellaProfileManager(root=root)
    profile_id = manager.get_active_profile_id()
    return manager.get_profile(profile_id) if profile_id else None


def resolve_profile_home(
    profile_id: str, root: Optional[Path | str] = None
) -> Path:
    """Resolve a validated Stella profile ID to its isolated Hermes home."""
    manager = StellaProfileManager(root=root)
    profile = manager.get_profile(profile_id)
    if profile is None:
        raise FileNotFoundError(f"Profile not found: '{profile_id}'")
    return profile.path


def resolve_active_profile_home(root: Optional[Path | str] = None) -> Optional[Path]:
    """Resolve the active profile home without creating or mutating profiles."""
    manager = StellaProfileManager(root=root)
    profile_id = manager.get_active_profile_id(auto_create_default=False)
    if profile_id is None:
        return None
    profile = manager.get_profile(profile_id)
    return profile.path if profile else None


def activate_profile(
    profile_id: str, root: Optional[Path | str] = None
) -> StellaProfileInfo:
    """Persist the active profile selection and return its metadata."""
    manager = StellaProfileManager(root=root)
    return manager.set_active_profile(profile_id)


@contextmanager
def runtime_scope(
    profile_id: Optional[str] = None,
    root: Optional[Path | str] = None,
) -> Iterator[StellaProfileInfo]:
    """Run Hermes work with every profile-scoped resolver pointed at Stella."""
    manager = StellaProfileManager(root=root)
    if profile_id is None:
        profile_id = manager.get_active_profile_id()
    if profile_id is None:
        raise FileNotFoundError("No Stella profile is available")
    profile = manager.get_profile(profile_id)
    if profile is None:
        raise FileNotFoundError(f"Profile not found: '{profile_id}'")

    # This is Hermes' established scope: it redirects config, sessions, state,
    # memory, skills, plugins, providers, cron, and workspace resolvers.
    from gateway.run import _profile_runtime_scope

    with _profile_runtime_scope(profile.path):
        yield profile
