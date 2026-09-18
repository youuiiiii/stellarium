"""Stella nested profile management architecture.

Layout:
  <stella_home>/
  ├── profiles/
  │   ├── <profile_id>/
  │   │   ├── profile.json       # display_name, created_at, avatar, etc.
  │   │   ├── config.yaml
  │   │   ├── SOUL.md
  │   │   ├── memories/
  │   │   ├── sessions/
  │   │   ├── skills/
  │   │   ├── cron/
  │   │   ├── workspace/
  │   │   └── logs/
  │   └── <another_profile_id>/
  ├── shared/
  └── cache/

Profile IDs are internal, immutable, and filesystem-safe (e.g. 'stella', 'p_01a7', 'gaming').
Display names are user-facing and mutable at any time without renaming directories.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from stella.constants import (
    DEFAULT_PRIMARY_PROFILE_ID,
    DEFAULT_PRIMARY_PROFILE_NAME,
    PROFILE_METADATA_FILE,
    STANDARD_PROFILE_SUBDIRS,
    STELLA_ACTIVE_PROFILE_FILE,
    STELLA_CACHE_DIR_NAME,
    STELLA_PROFILES_DIR_NAME,
    STELLA_SHARED_DIR_NAME,
    get_default_stella_home,
)
from stella.filesystem import assert_no_link_or_reparse, is_link_or_reparse

logger = logging.getLogger(__name__)

_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SLUG_SANITIZE_RE = re.compile(r"[^a-z0-9_-]+")


def sanitize_profile_id(raw_id: str) -> str:
    """Normalize input into a safe lowercase alphanumeric profile ID."""
    cleaned = _SLUG_SANITIZE_RE.sub("-", raw_id.strip().lower()).strip("-_")
    if not cleaned:
        cleaned = f"p_{int(time.time() * 1000) % 1000000:06x}"
    return cleaned[:64]


def validate_profile_id(profile_id: str) -> None:
    """Ensure profile_id is valid and prevents directory traversal."""
    if not isinstance(profile_id, str) or not _SAFE_ID_RE.fullmatch(profile_id):
        raise ValueError(
            f"Invalid profile ID {profile_id!r}. Must be 1-64 characters matching [a-z0-9][a-z0-9_-]*"
        )


@dataclass
class StellaProfileInfo:
    """Metadata representing a Stella profile."""

    id: str
    display_name: str
    path: Path
    is_primary: bool = False
    description: str = ""
    avatar: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    model: Optional[str] = None
    provider: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any], path: Path) -> "StellaProfileInfo":
        return cls(
            # The directory name is the immutable identity. Metadata is
            # user-editable and must never be allowed to retarget a profile.
            id=path.name,
            display_name=data.get("display_name", path.name.capitalize()),
            path=path,
            is_primary=bool(data.get("is_primary", False)),
            description=data.get("description", ""),
            avatar=data.get("avatar", ""),
            created_at=data.get(
                "created_at", datetime.now(timezone.utc).isoformat()
            ),
            updated_at=data.get(
                "updated_at", datetime.now(timezone.utc).isoformat()
            ),
            model=data.get("model"),
            provider=data.get("provider"),
            tags=list(data.get("tags") or []),
            metadata=dict(data.get("metadata") or {}),
        )


class StellaProfileManager:
    """Manager for Stella's nested profile directory layout."""

    @staticmethod
    def _is_link_or_reparse(path: Path) -> bool:
        """Detect symlinks and Windows junction/reparse points."""
        return is_link_or_reparse(path)

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.resolve(strict=False).relative_to(root.resolve(strict=False))
            return True
        except ValueError:
            return False

    def _assert_safe_directory(
        self, directory: Path, parent: Optional[Path] = None
    ) -> None:
        """Reject a directory that follows a link or leaves its parent."""
        assert_no_link_or_reparse(directory, "Stella directory")
        if directory.exists() and not directory.is_dir():
            raise ValueError(f"Stella path is not a directory: {directory}")
        if parent is not None and not self._is_within(directory, parent):
            raise ValueError(f"Stella directory escapes its root: {directory}")

    def __init__(self, root: Optional[Path | str] = None) -> None:
        raw_root = Path(root).expanduser() if root else get_default_stella_home()
        assert_no_link_or_reparse(raw_root, "Stella home")
        self.root = raw_root.resolve()
        self.profiles_dir = self.root / STELLA_PROFILES_DIR_NAME
        self.shared_dir = self.root / STELLA_SHARED_DIR_NAME
        self.cache_dir = self.root / STELLA_CACHE_DIR_NAME

    def ensure_root_layout(
        self, auto_create_default: bool = True
    ) -> StellaProfileInfo | None:
        """Create root directories (profiles/, shared/, cache/) and default profile if empty."""
        if self._is_link_or_reparse(self.root):
            raise ValueError(f"Stella home may not be a symlink or junction: {self.root}")
        self.root.mkdir(parents=True, exist_ok=True)
        for directory in (self.profiles_dir, self.shared_dir, self.cache_dir):
            self._assert_safe_directory(directory, parent=self.root)
            directory.mkdir(parents=True, exist_ok=True)
            self._assert_safe_directory(directory, parent=self.root)

        if auto_create_default:
            profiles = self.list_profiles()
            if not profiles:
                return self.create_profile(
                    profile_id=DEFAULT_PRIMARY_PROFILE_ID,
                    display_name=DEFAULT_PRIMARY_PROFILE_NAME,
                    description="Default primary workspace for Stella",
                    is_primary=True,
                )
        return None

    def get_profile_dir(self, profile_id: str) -> Path:
        """Get absolute path for a profile ID; enforces path safety."""
        validate_profile_id(profile_id)
        return self.profiles_dir / profile_id

    def list_profiles(self) -> List[StellaProfileInfo]:
        """Scan profiles/ directory and load metadata for all active profiles."""
        self._assert_safe_directory(self.profiles_dir, parent=self.root)
        if not self.profiles_dir.is_dir():
            return []

        results: List[StellaProfileInfo] = []
        for entry in sorted(self.profiles_dir.iterdir()):
            if (
                not entry.is_dir()
                or entry.name.startswith((".", "_"))
                or self._is_link_or_reparse(entry)
            ):
                if self._is_link_or_reparse(entry):
                    logger.warning("Ignoring linked profile entry: %s", entry)
                continue
            meta_file = entry / PROFILE_METADATA_FILE
            if self._is_link_or_reparse(meta_file):
                logger.warning("Ignoring linked profile metadata: %s", meta_file)
                continue
            if not _SAFE_ID_RE.fullmatch(entry.name):
                logger.warning("Ignoring profile with unsafe directory name: %s", entry)
                continue
            if meta_file.is_file():
                try:
                    meta_data = json.loads(meta_file.read_text(encoding="utf-8"))
                    results.append(
                        StellaProfileInfo.from_dict(meta_data, path=entry)
                    )
                    continue
                except Exception as exc:
                    logger.warning(
                        "Unreadable metadata in %s: %s", meta_file, exc
                    )

            # Fallback if profile.json missing: synthesize entry
            if _SAFE_ID_RE.fullmatch(entry.name):
                synthesized = StellaProfileInfo(
                    id=entry.name,
                    display_name=entry.name.capitalize(),
                    path=entry,
                    is_primary=(entry.name == DEFAULT_PRIMARY_PROFILE_ID),
                )
                results.append(synthesized)

        return results

    def get_profile(self, profile_id: str) -> Optional[StellaProfileInfo]:
        """Retrieve profile by its unique ID."""
        validate_profile_id(profile_id)
        self._assert_safe_directory(self.profiles_dir, parent=self.root)
        pdir = self.get_profile_dir(profile_id)
        self._assert_safe_directory(pdir, parent=self.profiles_dir)
        if not pdir.is_dir():
            return None

        meta_file = pdir / PROFILE_METADATA_FILE
        if self._is_link_or_reparse(meta_file):
            raise ValueError(f"Profile metadata may not be a symlink or junction: {meta_file}")
        if meta_file.is_file():
            try:
                meta_data = json.loads(meta_file.read_text(encoding="utf-8"))
                return StellaProfileInfo.from_dict(meta_data, path=pdir)
            except Exception as exc:
                logger.warning("Unreadable profile metadata for %s: %s", profile_id, exc)

        return StellaProfileInfo(
            id=profile_id,
            display_name=profile_id.capitalize(),
            path=pdir,
            is_primary=(profile_id == DEFAULT_PRIMARY_PROFILE_ID),
        )

    def get_primary_profile(
        self, auto_create_default: bool = True
    ) -> Optional[StellaProfileInfo]:
        """Return the profile marked as primary, or the first profile if none explicitly marked."""
        if auto_create_default:
            self.ensure_root_layout(auto_create_default=True)
        profiles = self.list_profiles()
        for p in profiles:
            if p.is_primary:
                return p
        return profiles[0] if profiles else None

    def get_active_profile_id(
        self, auto_create_default: bool = True
    ) -> Optional[str]:
        """Return sticky active profile ID, falling back to primary profile."""
        if auto_create_default:
            self.ensure_root_layout(auto_create_default=True)
        elif not self.root.exists():
            return None
        else:
            self._assert_safe_directory(self.root)

        active_file = self.root / STELLA_ACTIVE_PROFILE_FILE
        if self._is_link_or_reparse(active_file):
            raise ValueError(
                f"Active profile marker may not be a symlink or junction: {active_file}"
            )
        if active_file.is_file():
            try:
                candidate = active_file.read_text(encoding="utf-8").strip()
                if candidate and self.get_profile(candidate) is not None:
                    return candidate
            except Exception:
                pass
        primary = self.get_primary_profile(auto_create_default=False)
        return primary.id if primary else None

    def set_active_profile(self, profile_id: str) -> StellaProfileInfo:
        """Set sticky active profile ID."""
        profile = self.get_profile(profile_id)
        if profile is None:
            raise FileNotFoundError(f"Profile not found: '{profile_id}'")
        self._assert_safe_directory(self.root)
        active_file = self.root / STELLA_ACTIVE_PROFILE_FILE
        tmp_file = self.root / f".{STELLA_ACTIVE_PROFILE_FILE}.tmp"
        if self._is_link_or_reparse(active_file) or self._is_link_or_reparse(tmp_file):
            raise ValueError("Active profile marker may not be a symlink or junction")
        tmp_file.write_text(profile.id + "\n", encoding="utf-8")
        tmp_file.replace(active_file)
        return profile

    def create_profile(
        self,
        display_name: str,
        profile_id: Optional[str] = None,
        description: str = "",
        avatar: str = "",
        is_primary: bool = False,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> StellaProfileInfo:
        """Create a new nested profile with standard subdirectories and profile.json."""
        self.ensure_root_layout(auto_create_default=False)

        if profile_id is None:
            final_id = sanitize_profile_id(display_name)
        else:
            validate_profile_id(profile_id)
            final_id = profile_id
        validate_profile_id(final_id)
        pdir = self.get_profile_dir(final_id)

        if pdir.exists() or pdir.is_symlink():
            raise FileExistsError(
                f"Profile directory already exists: {pdir} (ID: '{final_id}')"
            )

        # Snapshot before creating the directory.  Otherwise list_profiles()
        # sees the directory we just created and the first profile is not
        # promoted to primary.
        existing = self.list_profiles()
        if not existing:
            is_primary = True

        # If this is marked primary, demote any previous primary profile.
        if is_primary:
            self._demote_current_primary()

        # Create standard layout
        pdir.mkdir(parents=True, exist_ok=False)
        for sub in STANDARD_PROFILE_SUBDIRS:
            (pdir / sub).mkdir(parents=True, exist_ok=False)

        now_iso = datetime.now(timezone.utc).isoformat()

        info = StellaProfileInfo(
            id=final_id,
            display_name=display_name.strip() or final_id.capitalize(),
            path=pdir,
            is_primary=is_primary,
            description=description,
            avatar=avatar,
            created_at=now_iso,
            updated_at=now_iso,
            model=model,
            provider=provider,
            tags=list(tags or []),
        )

        self._save_profile_metadata(info)

        # Seed default SOUL.md if missing
        soul_file = pdir / "SOUL.md"
        if not soul_file.exists():
            soul_file.write_text(
                f"# {info.display_name}\n\nDedicated personal assistant profile for Stella.\n",
                encoding="utf-8",
            )

        # Seed minimal config.yaml if missing
        cfg_file = pdir / "config.yaml"
        if not cfg_file.exists():
            cfg_file.write_text(
                f"# Configuration for profile: {info.display_name} ({info.id})\n",
                encoding="utf-8",
            )

        return info

    def update_profile(
        self,
        profile_id: str,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        avatar: Optional[str] = None,
        is_primary: Optional[bool] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StellaProfileInfo:
        """Update profile metadata in profile.json without modifying directory paths."""
        info = self.get_profile(profile_id)
        if not info:
            raise FileNotFoundError(f"Profile not found: '{profile_id}'")

        if display_name is not None and display_name.strip():
            info.display_name = display_name.strip()
        if description is not None:
            info.description = description
        if avatar is not None:
            info.avatar = avatar
        if model is not None:
            info.model = model
        if provider is not None:
            info.provider = provider
        if tags is not None:
            info.tags = list(tags)
        if metadata is not None:
            info.metadata.update(metadata)

        if is_primary is True and not info.is_primary:
            self._demote_current_primary()
            info.is_primary = True
        elif is_primary is False and info.is_primary:
            info.is_primary = False

        info.updated_at = datetime.now(timezone.utc).isoformat()
        self._save_profile_metadata(info)
        return info

    def delete_profile(
        self, profile_id: str, force: bool = False, archive: bool = True
    ) -> bool:
        """Safely delete a profile. By default moves to profiles/.deleted/."""
        validate_profile_id(profile_id)
        info = self.get_profile(profile_id)
        if not info:
            return False

        if info.is_primary and not force:
            raise ValueError(
                f"Cannot delete primary profile '{profile_id}' without force=True"
            )

        pdir = info.path
        self._assert_safe_directory(pdir, parent=self.profiles_dir)
        if archive:
            deleted_dir = self.profiles_dir / ".deleted"
            self._assert_safe_directory(deleted_dir, parent=self.profiles_dir)
            deleted_dir.mkdir(parents=True, exist_ok=True)
            self._assert_safe_directory(deleted_dir, parent=self.profiles_dir)
            timestamp = int(time.time())
            archive_target = deleted_dir / f"{profile_id}_{timestamp}"
            if archive_target.exists() or archive_target.is_symlink():
                raise FileExistsError(f"Archive target already exists: {archive_target}")
            shutil.move(str(pdir), str(archive_target))
        else:
            shutil.rmtree(pdir)

        # If primary was deleted, promote another profile if one exists
        if info.is_primary:
            remaining = self.list_profiles()
            if remaining:
                self.update_profile(remaining[0].id, is_primary=True)

        return True

    def _demote_current_primary(self) -> None:
        """Unset is_primary from any existing primary profile."""
        for p in self.list_profiles():
            if p.is_primary:
                p.is_primary = False
                p.updated_at = datetime.now(timezone.utc).isoformat()
                self._save_profile_metadata(p)

    def _save_profile_metadata(self, info: StellaProfileInfo) -> None:
        """Write profile metadata to profile.json atomically."""
        self._assert_safe_directory(info.path, parent=self.profiles_dir)
        meta_file = info.path / PROFILE_METADATA_FILE
        tmp_file = info.path / f".{PROFILE_METADATA_FILE}.tmp"
        if self._is_link_or_reparse(meta_file) or self._is_link_or_reparse(tmp_file):
            raise ValueError("Profile metadata may not be a symlink or junction")
        payload = info.to_dict()
        del payload["path"]  # path is dynamic / relative to root
        tmp_file.write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        os.replace(str(tmp_file), str(meta_file))
