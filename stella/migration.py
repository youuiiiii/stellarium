"""Hermes to Stella One-Click Migration Engine.

Key Invariants:
1. STRICT READ-ONLY ON SOURCE: The source Hermes installation is NEVER mutated,
   moved, renamed, or deleted.
2. SELECTIVE & OPT-IN: The user or caller selects which components to migrate
   (config, soul, memories, skills, cron, sessions).
3. ISOLATED DESTINATION: All imported data lands strictly inside Stella's nested
   profile architecture (profiles/<id>/), never scattered into root.
4. ROLLBACK-SAFE: A migration_manifest.json records every copied file with its SHA256;
   any migration can be cleanly and reversibly rolled back.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

import yaml

from stella.constants import (
    DEFAULT_PRIMARY_PROFILE_ID,
    MIGRATION_MANIFEST_FILE,
    SUPPORTED_MIGRATION_COMPONENTS,
    get_default_stella_home,
)
from stella.filesystem import assert_no_link_or_reparse, is_link_or_reparse
from stella.profiles import (
    StellaProfileManager,
    sanitize_profile_id,
    validate_profile_id,
)

logger = logging.getLogger(__name__)


DEFAULT_MIGRATION_COMPONENTS = frozenset(
    {"config", "soul", "memories", "skills", "cron"}
)

# These names identify values that must not cross the Hermes -> Stella
# migration boundary.  Environment-variable references (foo_env / key_env)
# are safe metadata; their values are not credentials themselves.
_SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?keys?|keys?|api[_-]?tokens?|access[_-]?tokens?|"
    r"refresh[_-]?tokens?|tokens?|"
    r"auth(?:orization)?|passwords?|passwd|secrets?|credentials?|"
    r"private[_-]?keys?|client[_-]?secrets?|cookies?|webhooks?|"
    r"headers?|signature|sig|oauth[_-]?signature|env(?:ironment)?|"
    r"connection[_-]?strings?|dsn)$",
    re.IGNORECASE,
)
_ENV_REFERENCE_RE = re.compile(
    r"^(?:\$[A-Za-z_][A-Za-z0-9_]*|\$\{[A-Za-z_][A-Za-z0-9_]*\}|"
    r"env:[A-Za-z_][A-Za-z0-9_]*)$"
)
_CONNECTION_SECRET_RE = re.compile(r"://[^\s/@:]+:[^\s/@]+@")
_QUERY_SECRET_RE = re.compile(
    r"[?&](?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|"
    r"password|secret|credential|client[_-]?secret|authorization|signature|sig|"
    r"oauth[_-]?signature|x[_-]?(?:amz|goog)[_-]?signature)=([^&#\s]+)",
    re.IGNORECASE,
)
_FRAGMENT_SECRET_RE = re.compile(
    r"#(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|"
    r"secret|credential|client[_-]?secret|authorization|signature|sig|"
    r"oauth[_-]?signature|x[_-]?(?:amz|goog)[_-]?signature)=([^#\s]+)",
    re.IGNORECASE,
)
_PRIVATE_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN(?: [A-Z0-9]+)* PRIVATE KEY-----", re.IGNORECASE
)
_MIGRATION_ID_RE = re.compile(r"mig_[0-9]+_[0-9a-f]{8}")
_INTEGRITY_KEY_FILE = ".stella-migration-integrity-key"
_INTEGRITY_KEY_BYTES = 32
_MAX_INSPECTABLE_NON_CONFIG_BYTES = 16 * 1024 * 1024
_SENSITIVE_FILENAME_RE = re.compile(
    r"(?:^|[._-])(env|credentials?|secrets?|tokens?|passwords?|passwd|"
    r"api[_-]?keys?|private[_-]?keys?|auth|cookies?|webhooks?|"
    r"connection[_-]?strings?|dsn)(?:[._-]|$)",
    re.IGNORECASE,
)
_ASSIGNMENT_RE = re.compile(
    r"(?im)(?:^|[\"']?)([a-z][a-z0-9_.-]*)[\"']?\s*[:=]\s*"
    r"(\"[^\"\r\n]*\"|'[^'\r\n]*'|\$\{[^}\r\n]+\}|[^\s,}\]]+)",
)


def _normalise_sensitive_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")


def _is_env_reference(value: str) -> bool:
    value = value.strip().strip("\\\"'")
    return bool(_ENV_REFERENCE_RE.fullmatch(value))


def _component_for_excluded_file(relative_path: str) -> str:
    first = relative_path.split("/", 1)[0]
    if first in {"skills", "cron", "sessions", "memories"}:
        return first
    if first in {"SOUL.md", "system_prompt.md", "AGENTS.md"}:
        return "soul"
    if first in {"MEMORY.md", "USER.md"}:
        return "memories"
    return "config"


def _is_sensitive_non_config_file(path: Path, relative_path: str) -> bool:
    """Return True when a non-config file cannot safely cross the boundary."""
    name = Path(relative_path).name
    if name in {".env", ".env.local", ".env.production", ".env.development"}:
        return True
    if _SENSITIVE_FILENAME_RE.search(name):
        return True
    try:
        if path.stat().st_size > _MAX_INSPECTABLE_NON_CONFIG_BYTES:
            return True
        raw = path.read_bytes()
    except (OSError, UnicodeError):
        return True
    # Binary/unknown encodings cannot be inspected for credentials safely.
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return True
    if (
        _CONNECTION_SECRET_RE.search(text)
        or _QUERY_SECRET_RE.search(text)
        or _FRAGMENT_SECRET_RE.search(text)
        or _PRIVATE_KEY_BLOCK_RE.search(text)
    ):
        return True
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    if parsed is not None:
        nested_redactions: List[str] = []
        HermesMigrationEngine._sanitise_config_value(
            parsed, "", nested_redactions
        )
        if nested_redactions:
            return True
    for match in _ASSIGNMENT_RE.finditer(text):
        key = _normalise_sensitive_key(match.group(1))
        value = match.group(2).strip()
        if not key or _is_env_reference(value):
            continue
        if _SENSITIVE_KEY_RE.search(key) and value not in {"", "null", "none", "[REDACTED]"}:
            return True
    return False


@dataclass(frozen=True)
class _FilePlan:
    source: Path
    relative_path: str
    destination: Path
    component: str
    transform: Optional[str] = None


def _compute_sha256(path: Path) -> str:
    """Compute SHA256 checksum of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class HermesInstallationInfo:
    """Discovered Hermes installation candidate."""

    path: Path
    is_valid: bool
    version_hint: str = ""
    has_config: bool = False
    has_soul: bool = False
    named_profiles: List[str] = field(default_factory=list)
    memory_count: int = 0
    skill_count: int = 0
    cron_count: int = 0
    estimated_size_bytes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        return data


@dataclass
class ComponentPreview:
    """Preview summary for a single migratable component."""

    name: str
    available: bool
    file_count: int = 0
    total_bytes: int = 0
    sample_files: List[str] = field(default_factory=list)
    excluded_files: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class _SanitizedConfig:
    """Safe config payload plus an audit trail of removed key paths."""

    payload: Any
    redacted_paths: List[str] = field(default_factory=list)


@dataclass
class MigrationPreview:
    """Dry-run inspection result of a Hermes source before copying."""

    source_path: str
    target_profile_id: str
    components: Dict[str, ComponentPreview]
    conflicts: List[str] = field(default_factory=list)
    named_profiles: List[str] = field(default_factory=list)
    selected_components: List[str] = field(default_factory=list)
    excluded_files: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    can_proceed: bool = True

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        return res


@dataclass
class CopiedFileRecord:
    """Audit record of a file copied into a Stella profile."""

    relative_path: str
    size: int
    sha256: str
    copied_at: str
    destination_existed: bool = False
    backup_relative_path: Optional[str] = None
    redacted_paths: List[str] = field(default_factory=list)
    state: str = "committed"
    original_sha256: Optional[str] = None
    original_size: Optional[int] = None


@dataclass
class _RollbackConflict:
    relative_path: str
    reason: str


@dataclass
class _MigrationTransaction:
    stage_dir: Path
    backup_dir: Path
    receipt_dir: Path
    committed: List[CopiedFileRecord] = field(default_factory=list)
    backups_created: List[Path] = field(default_factory=list)


@dataclass
class MigrationManifest:
    """Persistent audit manifest for reversible rollback."""

    migration_id: str
    source_path: str
    target_profile_id: str
    created_at: str
    selected_components: List[str]
    copied_files: List[CopiedFileRecord] = field(default_factory=list)
    skipped_files: List[Dict[str, str]] = field(default_factory=list)
    excluded_files: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    child_migrations: List[Dict[str, str]] = field(default_factory=list)
    status: str = "completed"  # 'completed', 'rolled_back', 'failed', 'rollback_conflict'
    rollback_conflicts: List[Dict[str, str]] = field(default_factory=list)
    staging_relative_path: Optional[str] = None
    backup_relative_path: Optional[str] = None
    receipt_relative_path: Optional[str] = None
    parent_migration_id: Optional[str] = None
    schema_version: int = 2
    integrity_tag: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MigrationManifest":
        if not isinstance(data, dict):
            raise ValueError("manifest root must be an object")
        copied_raw = data.get("copied_files", [])
        if not isinstance(copied_raw, list):
            raise ValueError("manifest copied_files must be a list")
        copied = []
        for raw_record in copied_raw:
            if not isinstance(raw_record, dict):
                raise ValueError("manifest copied_files contains a malformed record")
            record = dict(raw_record)
            # Keep manifests written by the first implementation readable.
            record.setdefault("destination_existed", False)
            record.setdefault("backup_relative_path", None)
            record.setdefault("redacted_paths", [])
            record.setdefault("state", "committed")
            record.setdefault("original_sha256", None)
            record.setdefault("original_size", None)
            copied.append(CopiedFileRecord(**record))

        child_migrations = data.get("child_migrations", [])
        if not isinstance(child_migrations, list) or any(
            not isinstance(child, dict) for child in child_migrations
        ):
            raise ValueError("manifest child_migrations must be a list of objects")
        selected_components = data.get("selected_components", [])
        skipped_files = data.get("skipped_files", [])
        excluded_files = data.get("excluded_files", [])
        warnings = data.get("warnings", [])
        rollback_conflicts = data.get("rollback_conflicts", [])
        if not isinstance(selected_components, list) or not all(
            isinstance(item, str) for item in selected_components
        ):
            raise ValueError("manifest selected_components is malformed")
        if not isinstance(skipped_files, list) or not isinstance(excluded_files, list):
            raise ValueError("manifest file audit lists are malformed")
        if not isinstance(warnings, list) or not all(
            isinstance(item, str) for item in warnings
        ):
            raise ValueError("manifest warnings are malformed")
        if not isinstance(rollback_conflicts, list):
            raise ValueError("manifest rollback_conflicts is malformed")

        return cls(
            migration_id=data["migration_id"],
            source_path=data["source_path"],
            target_profile_id=data["target_profile_id"],
            created_at=data["created_at"],
            selected_components=selected_components,
            copied_files=copied,
            skipped_files=skipped_files,
            excluded_files=excluded_files,
            warnings=warnings,
            child_migrations=child_migrations,
            status=data.get("status", "completed"),
            rollback_conflicts=rollback_conflicts,
            staging_relative_path=data.get("staging_relative_path"),
            backup_relative_path=data.get("backup_relative_path"),
            receipt_relative_path=data.get("receipt_relative_path"),
            parent_migration_id=data.get("parent_migration_id"),
            schema_version=data.get("schema_version", 1),
            integrity_tag=data.get("integrity_tag"),
        )


class HermesMigrationEngine:
    """Engine for discovering Hermes data and safely migrating into Stella."""

    def __init__(
        self,
        stella_home: Optional[Path | str] = None,
        profile_manager: Optional[StellaProfileManager] = None,
    ) -> None:
        self.profile_mgr = (
            profile_manager or StellaProfileManager(stella_home)
        )
        self.stella_home = self.profile_mgr.root

    @staticmethod
    def _canonical_json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def _integrity_key_path(self) -> Path:
        assert_no_link_or_reparse(self.stella_home, "Stella home")
        return self.stella_home / _INTEGRITY_KEY_FILE

    def _load_integrity_key(self, create: bool = False) -> Optional[bytes]:
        key_path = self._integrity_key_path()
        if is_link_or_reparse(key_path):
            raise ValueError("Stella integrity key may not be a symlink or junction")
        if key_path.is_file():
            key = key_path.read_bytes()
            if len(key) != _INTEGRITY_KEY_BYTES:
                raise ValueError("Stella integrity key is malformed")
            return key
        if not create:
            return None
        self._ensure_safe_directory(self.stella_home, "")
        key = secrets.token_bytes(_INTEGRITY_KEY_BYTES)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        try:
            fd = os.open(os.fspath(key_path), flags, 0o600)
        except FileExistsError:
            return self._load_integrity_key(create=False)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(key)
                handle.flush()
                os.fsync(handle.fileno())
            self._fsync_parent_directory(key_path.parent)
        except Exception:
            try:
                key_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return key

    def _integrity_tag(self, payload: Mapping[str, Any], key: bytes) -> str:
        return hmac.new(
            key,
            self._canonical_json(payload).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _verify_manifest_integrity(self, manifest: MigrationManifest) -> None:
        if manifest.schema_version < 2:
            return
        if not isinstance(manifest.integrity_tag, str) or not re.fullmatch(
            r"[0-9a-f]{64}", manifest.integrity_tag
        ):
            raise ValueError("migration manifest integrity tag is missing or malformed")
        key = self._load_integrity_key(create=False)
        if key is None:
            raise ValueError("Stella integrity key is missing")
        payload = manifest.to_dict()
        payload.pop("integrity_tag", None)
        expected = self._integrity_tag(payload, key)
        if not hmac.compare_digest(expected, manifest.integrity_tag):
            raise ValueError("migration manifest integrity check failed")

    def _verify_receipt_integrity(self, payload: Mapping[str, Any]) -> None:
        tag = payload.get("integrity_tag")
        if not isinstance(tag, str) or not re.fullmatch(r"[0-9a-f]{64}", tag):
            raise ValueError("migration receipt integrity tag is missing or malformed")
        key = self._load_integrity_key(create=False)
        if key is None:
            raise ValueError("Stella integrity key is missing")
        unsigned = dict(payload)
        unsigned.pop("integrity_tag", None)
        expected = self._integrity_tag(unsigned, key)
        if not hmac.compare_digest(expected, tag):
            raise ValueError("migration receipt integrity check failed")

    @staticmethod
    def _normalise_components(
        components: Optional[Iterable[str]],
    ) -> set[str]:
        """Resolve component selection without treating an empty list as all."""
        if components is None:
            return set(DEFAULT_MIGRATION_COMPONENTS)
        if isinstance(components, (str, bytes)):
            raise ValueError("components must be a list of component names")

        selected = {str(item).strip().lower() for item in components}
        if not selected:
            raise ValueError("at least one migration component must be selected")
        unknown = selected - set(SUPPORTED_MIGRATION_COMPONENTS)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"Unknown migration component(s): {names}")
        return selected

    @staticmethod
    def _normalise_relative_path(value: str) -> str:
        """Return a portable relative path or fail closed."""
        if not isinstance(value, str) or not value.strip():
            raise ValueError("manifest path must be a non-empty string")
        raw = value.replace("\\", "/")
        posix_path = PurePosixPath(raw)
        windows_path = PureWindowsPath(raw)
        if (
            raw.startswith("/")
            or posix_path.is_absolute()
            or windows_path.is_absolute()
        ):
            raise ValueError(f"absolute migration path is not allowed: {value!r}")
        parts = tuple(part for part in raw.split("/") if part)
        if not parts or any(part in {".", ".."} for part in parts):
            raise ValueError(f"unsafe migration path: {value!r}")
        return "/".join(parts)

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.resolve(strict=False).relative_to(root.resolve(strict=False))
        except ValueError:
            return False
        return True

    @classmethod
    def _assert_no_path_overlap(cls, left: Path, right: Path) -> None:
        left_resolved = left.resolve(strict=False)
        right_resolved = right.resolve(strict=False)
        if cls._is_within(left_resolved, right_resolved) or cls._is_within(
            right_resolved, left_resolved
        ):
            raise ValueError(
                "Hermes source must be outside Stella home; "
                "source and destination must be disjoint"
            )

    def _validate_source_root(self, source_path: Path | str) -> Path:
        source_input = Path(source_path).expanduser()
        if is_link_or_reparse(source_input):
            raise ValueError("Hermes source directory may not be a symlink or junction")
        assert_no_link_or_reparse(source_input, "Hermes source")
        source = source_input.resolve(strict=False)
        if not source.is_dir():
            raise ValueError(f"Hermes source directory does not exist: {source}")
        self._assert_no_path_overlap(source, self.stella_home)
        return source

    def _validate_profile_dir(
        self,
        profile_dir: Path | str,
        expected_profile_id: Optional[str] = None,
    ) -> Path:
        """Validate a target profile and reject links/junctions outside it."""
        profile_path = Path(profile_dir).expanduser()
        if is_link_or_reparse(profile_path):
            raise ValueError("Stella profile directory may not be a symlink or junction")
        assert_no_link_or_reparse(profile_path, "Stella profile")
        profiles_root = Path(self.profile_mgr.profiles_dir).resolve(strict=False)
        resolved = profile_path.resolve(strict=False)
        try:
            relative = resolved.relative_to(profiles_root)
        except ValueError as exc:
            raise ValueError("Stella target is outside the profiles directory") from exc
        if len(relative.parts) != 1 or not relative.parts[0]:
            raise ValueError("Stella target must be one direct profile directory")
        if expected_profile_id and relative.parts[0].casefold() != expected_profile_id.casefold():
            raise ValueError("manifest target profile does not match rollback target")
        return profile_path

    def _safe_child(self, root: Path, relative_path: str, label: str) -> Path:
        """Join a relative path while rejecting traversal and every link."""
        normalised = self._normalise_relative_path(relative_path)
        candidate = root.joinpath(*normalised.split("/"))
        assert_no_link_or_reparse(root, label)
        assert_no_link_or_reparse(candidate, label)
        if not self._is_within(candidate, root):
            raise ValueError(f"{label} escapes its root: {relative_path!r}")

        cursor = root
        for part in normalised.split("/"):
            cursor = cursor / part
            if is_link_or_reparse(cursor):
                raise ValueError(f"{label} contains a symlink or junction: {relative_path!r}")
            if cursor.exists() and not self._is_within(cursor, root):
                raise ValueError(f"{label} escapes its root: {relative_path!r}")
        return candidate

    def _assert_source_entry(self, path: Path, source_root: Path) -> None:
        if is_link_or_reparse(path):
            raise ValueError(f"Hermes source contains a symlink or junction: {path}")
        assert_no_link_or_reparse(path, "Hermes source")
        if not self._is_within(path, source_root):
            raise ValueError(f"Hermes source entry escapes source root: {path}")

    def _assert_source_file(self, path: Path, source_root: Path) -> None:
        self._assert_source_entry(path, source_root)
        if not path.is_file():
            raise ValueError(f"migration source is not a regular file: {path}")

    def _iter_source_files(self, root: Path, source_root: Path) -> Iterable[Path]:
        """Walk without following symlinks, junctions, or special files."""
        if not root.exists():
            return
        if is_link_or_reparse(root):
            raise ValueError(f"Hermes source contains a symlink or junction: {root}")
        assert_no_link_or_reparse(root, "Hermes source")
        if not root.is_dir():
            raise ValueError(f"migration component is not a directory: {root}")

        for current, dirnames, filenames in os.walk(
            root, topdown=True, followlinks=False
        ):
            current_path = Path(current)
            dirnames.sort()
            filenames.sort()
            for dirname in list(dirnames):
                self._assert_source_entry(current_path / dirname, source_root)
            for filename in filenames:
                path = current_path / filename
                self._assert_source_file(path, source_root)
                yield path

    @classmethod
    def _sanitise_config_value(
        cls,
        value: Any,
        path: str,
        redacted_paths: List[str],
    ) -> Any:
        if isinstance(value, Mapping):
            safe: Dict[Any, Any] = {}
            for key, child in value.items():
                key_text = str(key)
                normalised_key = re.sub(r"[^a-z0-9]+", "_", key_text.lower()).strip("_")
                child_path = f"{path}.{key_text}" if path else key_text
                if _SENSITIVE_KEY_RE.search(normalised_key) and not (
                    isinstance(child, str) and _is_env_reference(child)
                ):
                    redacted_paths.append(child_path)
                    continue
                safe[key] = cls._sanitise_config_value(
                    child, child_path, redacted_paths
                )
            return safe
        if isinstance(value, list):
            return [
                cls._sanitise_config_value(
                    child, f"{path}[{index}]", redacted_paths
                )
                for index, child in enumerate(value)
            ]
        if isinstance(value, str) and (
            _CONNECTION_SECRET_RE.search(value)
            or _QUERY_SECRET_RE.search(value)
            or _FRAGMENT_SECRET_RE.search(value)
            or _PRIVATE_KEY_BLOCK_RE.search(value)
        ):
            redacted_paths.append(path or "<value>")
            return "[REDACTED]"
        return value

    @classmethod
    def _load_sanitised_config(
        cls, source_path: Path
    ) -> Tuple[str, List[str]]:
        try:
            parsed = yaml.safe_load(source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise ValueError(
                "refusing to copy config.yaml because it cannot be parsed safely"
            ) from exc
        redacted_paths: List[str] = []
        safe_value = cls._sanitise_config_value(parsed, "", redacted_paths)
        try:
            content = yaml.safe_dump(
                safe_value,
                sort_keys=False,
                allow_unicode=True,
                default_flow_style=False,
            )
        except yaml.YAMLError as exc:
            raise ValueError("refusing to serialize sanitized config.yaml") from exc
        return content, redacted_paths

    def _build_file_plans(
        self,
        source: Path,
        target_dir: Path,
        selected: Set[str],
    ) -> Tuple[List[_FilePlan], List[str]]:
        """Build and validate a copy plan before touching the destination."""
        plans: List[_FilePlan] = []
        excluded_files: List[str] = []
        seen_destinations: Set[str] = set()

        def add_file(
            source_file: Path,
            relative_path: str,
            component: str,
            transform: Optional[str] = None,
        ) -> None:
            self._assert_source_file(source_file, source)
            normalised = self._normalise_relative_path(relative_path)
            if transform != "sanitise_config" and _is_sensitive_non_config_file(
                source_file, normalised
            ):
                excluded_files.append(normalised)
                return
            if normalised in seen_destinations:
                raise ValueError(f"duplicate migration destination: {normalised}")
            destination = self._safe_child(target_dir, normalised, "migration destination")
            seen_destinations.add(normalised)
            plans.append(
                _FilePlan(
                    source=source_file,
                    relative_path=normalised,
                    destination=destination,
                    component=component,
                    transform=transform,
                )
            )

        def add_tree(component: str, source_dir: Path) -> None:
            if is_link_or_reparse(source_dir):
                raise ValueError(f"Hermes source component is a symlink or junction: {source_dir}")
            if not source_dir.exists():
                return
            for source_file in self._iter_source_files(source_dir, source):
                relative = source_file.relative_to(source).as_posix()
                # Hidden files are deliberately not migratable, but are still
                # inspected by _iter_source_files so links cannot hide in them.
                if any(part.startswith(".") for part in source_file.relative_to(source_dir).parts):
                    excluded_files.append(relative)
                    continue
                add_file(source_file, relative, component)

        if "config" in selected:
            config_file = source / "config.yaml"
            if is_link_or_reparse(config_file):
                raise ValueError(f"Hermes source config is a symlink or junction: {config_file}")
            if config_file.exists() and not config_file.is_dir():
                add_file(config_file, "config.yaml", "config", "sanitise_config")
            dotenv = source / ".env"
            if dotenv.exists() or is_link_or_reparse(dotenv):
                # Never inspect or copy its contents.  Recording the exclusion
                # makes the opt-in choice visible in preview/manifest output.
                excluded_files.append(".env")

        if "soul" in selected:
            for name in ("SOUL.md", "system_prompt.md", "AGENTS.md"):
                source_file = source / name
                if source_file.is_file() or is_link_or_reparse(source_file):
                    add_file(source_file, name, "soul")

        if "memories" in selected:
            for name in ("MEMORY.md", "USER.md"):
                source_file = source / name
                if source_file.is_file() or is_link_or_reparse(source_file):
                    add_file(source_file, f"memories/{name}", "memories")
            add_tree("memories", source / "memories")

        if "skills" in selected:
            add_tree("skills", source / "skills")

        if "cron" in selected:
            cron_dir = source / "cron"
            if is_link_or_reparse(cron_dir):
                raise ValueError(f"Hermes source component is a symlink or junction: {cron_dir}")
            if cron_dir.exists():
                for source_file in self._iter_source_files(cron_dir, source):
                    relative = source_file.relative_to(source).as_posix()
                    if source_file.name.endswith((".db-wal", ".db-shm")):
                        continue
                    if any(
                        part.startswith(".")
                        for part in source_file.relative_to(cron_dir).parts
                    ):
                        excluded_files.append(relative)
                        continue
                    add_file(source_file, relative, "cron")

        if "sessions" in selected:
            add_tree("sessions", source / "sessions")

        return plans, excluded_files

    # ----------------------------------------------------------------------
    # 1. DISCOVERY
    # ----------------------------------------------------------------------

    def _assert_no_reparse_tree(self, root: Path, label: str) -> None:
        """Reject any link/reparse point anywhere below a source candidate."""
        assert_no_link_or_reparse(root, label)

        def walk(directory: Path) -> None:
            try:
                with os.scandir(directory) as iterator:
                    entries = list(iterator)
            except FileNotFoundError:
                if is_link_or_reparse(directory):
                    raise ValueError(f"{label} contains a dangling reparse point")
                return
            for entry in entries:
                child = Path(entry.path)
                if is_link_or_reparse(child):
                    raise ValueError(f"{label} contains a symlink or reparse point")
                try:
                    is_directory = entry.is_dir(follow_symlinks=False)
                except OSError as exc:
                    raise ValueError(f"unable to inspect {label}") from exc
                if is_directory:
                    walk(child)

        walk(root)

    def detect_hermes_installations(
        self, extra_paths: Optional[List[Path | str]] = None
    ) -> List[HermesInstallationInfo]:
        """Scan candidate directories for existing Hermes installations."""
        candidates: List[Path] = []

        env_hermes = os.environ.get("HERMES_HOME", "").strip()
        if env_hermes:
            candidates.append(Path(env_hermes).expanduser())

        candidates.append(Path.home() / ".hermes")

        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        if local_appdata:
            candidates.append(Path(local_appdata) / "hermes")

        if extra_paths:
            for ep in extra_paths:
                candidates.append(Path(ep).expanduser())

        unique_candidates: List[Path] = []
        seen = set()
        for c in candidates:
            try:
                c = c.expanduser()
                assert_no_link_or_reparse(c, "Hermes candidate")
                if is_link_or_reparse(c):
                    continue
                resolved = c.resolve()
                stella_root = self.stella_home.resolve()
                if self._is_within(resolved, stella_root) or self._is_within(
                    stella_root, resolved
                ):
                    continue
                if resolved not in seen:
                    seen.add(resolved)
                    unique_candidates.append(resolved)
            except Exception:
                continue

        results: List[HermesInstallationInfo] = []
        for candidate in unique_candidates:
            info = self.inspect_hermes_directory(candidate)
            if info.is_valid:
                results.append(info)

        return results

    def inspect_hermes_directory(self, path: Path) -> HermesInstallationInfo:
        """Inspect a potential Hermes directory (strictly read-only)."""
        try:
            assert_no_link_or_reparse(path, "Hermes candidate")
            if is_link_or_reparse(path):
                return HermesInstallationInfo(path=path, is_valid=False)
        except (OSError, ValueError):
            return HermesInstallationInfo(path=path, is_valid=False)
        try:
            self._assert_no_reparse_tree(path, "Hermes candidate")
        except (OSError, ValueError):
            return HermesInstallationInfo(path=path, is_valid=False)
        if not path.is_dir():
            return HermesInstallationInfo(path=path, is_valid=False)

        cfg_file = path / "config.yaml"
        soul_file = path / "SOUL.md"
        profiles_dir = path / "profiles"
        memories_dir = path / "memories"
        skills_dir = path / "skills"
        cron_file = path / "cron" / "jobs.json"
        state_db = path / "state.db"

        # Valid Hermes marker check
        markers_found = sum(
            [
                cfg_file.exists(),
                soul_file.exists(),
                profiles_dir.is_dir(),
                memories_dir.is_dir(),
                skills_dir.is_dir(),
                state_db.exists(),
            ]
        )
        if markers_found < 1:
            return HermesInstallationInfo(path=path, is_valid=False)

        named_profiles: List[str] = []
        if profiles_dir.is_dir():
            for p in profiles_dir.iterdir():
                if p.is_dir() and not p.name.startswith((".", "_")) and p.name != "default":
                    named_profiles.append(p.name)

        # Count memories
        memory_count = 0
        if memories_dir.is_dir():
            memory_count += sum(
                1 for f in memories_dir.glob("*") if f.is_file()
            )
        if (path / "MEMORY.md").exists():
            memory_count += 1
        if (path / "USER.md").exists():
            memory_count += 1

        # Count skills
        skill_count = 0
        if skills_dir.is_dir():
            skill_count = sum(
                1 for d in skills_dir.iterdir() if d.is_dir() and not d.name.startswith(".")
            )

        # Count cron
        cron_count = 0
        if cron_file.exists():
            try:
                cron_data = json.loads(cron_file.read_text(encoding="utf-8"))
                cron_count = len(cron_data.get("jobs", [])) if isinstance(cron_data, dict) else len(cron_data)
            except Exception:
                cron_count = 1

        return HermesInstallationInfo(
            path=path,
            is_valid=True,
            has_config=cfg_file.exists(),
            has_soul=soul_file.exists(),
            named_profiles=named_profiles,
            memory_count=memory_count,
            skill_count=skill_count,
            cron_count=cron_count,
        )

    # ----------------------------------------------------------------------
    # 2. DRY-RUN / PREVIEW
    # ----------------------------------------------------------------------

    def preview_migration(
        self,
        source_path: Path | str,
        target_profile_id: str = DEFAULT_PRIMARY_PROFILE_ID,
        components: Optional[Iterable[str]] = None,
    ) -> MigrationPreview:
        """Examine source data without reading secrets or changing either tree."""
        src = self._validate_source_root(source_path)
        validate_profile_id(target_profile_id)
        target_id = target_profile_id
        selected = self._normalise_components(components)
        target_dir = self._validate_profile_dir(
            self.profile_mgr.get_profile_dir(target_id), target_id
        )

        # Build all summaries so the UI can show unselected components, while
        # conflicts are reported only for the user's explicit selection.
        all_plans, excluded = self._build_file_plans(
            src, target_dir, set(SUPPORTED_MIGRATION_COMPONENTS)
        )
        selected_plans = [plan for plan in all_plans if plan.component in selected]
        components_by_name: Dict[str, ComponentPreview] = {}
        for name in sorted(SUPPORTED_MIGRATION_COMPONENTS):
            plans = [plan for plan in all_plans if plan.component == name]
            excluded_for_component = [
                item for item in excluded if _component_for_excluded_file(item) == name
            ]
            warnings: List[str] = []
            if name == "config":
                config_plan = next(
                    (plan for plan in plans if plan.transform == "sanitise_config"),
                    None,
                )
                if config_plan:
                    _, redacted = self._load_sanitised_config(config_plan.source)
                    if redacted:
                        warnings.append(
                            f"redacted {len(redacted)} sensitive config value(s)"
                        )
            components_by_name[name] = ComponentPreview(
                name=name,
                available=bool(plans) or bool(excluded_for_component),
                file_count=len(plans),
                total_bytes=sum(plan.source.stat().st_size for plan in plans),
                sample_files=[plan.relative_path for plan in plans[:5]],
                excluded_files=excluded_for_component,
                warnings=warnings,
            )

        conflicts = [
            plan.relative_path
            for plan in selected_plans
            if plan.destination.exists()
        ]

        named: List[str] = []
        profiles_dir = src / "profiles"
        if is_link_or_reparse(profiles_dir):
            raise ValueError(
                f"Hermes profiles component is a symlink or junction: {profiles_dir}"
            )
        if profiles_dir.exists():
            self._assert_source_entry(profiles_dir, src)
            if not profiles_dir.is_dir():
                raise ValueError("Hermes profiles entry is not a directory")
            for entry in sorted(profiles_dir.iterdir(), key=lambda item: item.name.casefold()):
                if entry.name.startswith((".", "_")) or entry.name == "default":
                    continue
                self._assert_source_entry(entry, src)
                if entry.is_dir():
                    named.append(entry.name)

        warnings = []
        if excluded:
            warnings.append(".env and other credential files are never migrated")

        return MigrationPreview(
            source_path=str(src),
            target_profile_id=target_id,
            components=components_by_name,
            conflicts=conflicts,
            named_profiles=named,
            selected_components=sorted(selected),
            excluded_files=excluded,
            warnings=warnings,
            can_proceed=True,
        )

    # ----------------------------------------------------------------------
    # 3. EXECUTION
    # ----------------------------------------------------------------------

    def _ensure_safe_directory(self, root: Path, relative_dir: str) -> Path:
        """Create a directory below root without traversing links."""
        if not relative_dir or relative_dir in {".", ""}:
            return root
        normalised = self._normalise_relative_path(relative_dir)
        current = root
        for part in normalised.split("/"):
            current = current / part
            if is_link_or_reparse(current):
                raise ValueError("migration directory contains a symlink or junction")
            if current.exists():
                if not current.is_dir() or not self._is_within(current, root):
                    raise ValueError("migration directory escapes its root")
            else:
                current.mkdir()
        return current

    @staticmethod
    def _generated_directory_name(kind: str, migration_id: str) -> str:
        """Return the only staging/backup namespace valid for a generated migration ID."""
        if not isinstance(migration_id, str) or not _MIGRATION_ID_RE.fullmatch(migration_id):
            raise ValueError("migration manifest contains an invalid migration_id")
        if kind == "staging":
            return f".stella-migration-staging-{migration_id}"
        if kind == "backup":
            return f".stella-migration-backups-{migration_id}"
        if kind == "receipts":
            return f".stella-migration-receipts-{migration_id}"
        raise ValueError(f"unknown generated migration directory kind: {kind}")

    @staticmethod
    def _receipt_file_name(relative_path: str) -> str:
        return hashlib.sha256(relative_path.encode("utf-8")).hexdigest() + ".json"

    def _receipt_path(
        self, profile_dir: Path, manifest: MigrationManifest, relative_path: str
    ) -> Path:
        if not manifest.receipt_relative_path:
            raise ValueError("migration file receipt root is missing")
        receipt_root = self._safe_child(
            profile_dir, manifest.receipt_relative_path, "migration receipts"
        )
        if not receipt_root.is_dir():
            raise ValueError("migration file receipt root is missing")
        return self._safe_child(
            receipt_root,
            self._receipt_file_name(relative_path),
            "migration receipt",
        )

    @staticmethod
    def _fsync_parent_directory(path: Path) -> None:
        try:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            fd = os.open(os.fspath(path), flags)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    def _write_record_receipt(
        self, profile_dir: Path, manifest: MigrationManifest, record: CopiedFileRecord
    ) -> None:
        receipt = self._receipt_path(profile_dir, manifest, record.relative_path)
        payload = {
            "migration_id": manifest.migration_id,
            "target_profile_id": manifest.target_profile_id,
            "record": asdict(record),
        }
        key = self._load_integrity_key(create=True)
        assert key is not None
        payload["integrity_tag"] = self._integrity_tag(payload, key)
        tmp = self._safe_child(
            receipt.parent,
            f".{receipt.name}.tmp",
            "migration receipt",
        )
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(tmp), str(receipt))
        self._fsync_parent_directory(receipt.parent)

    def _validate_record_receipt(
        self, profile_dir: Path, manifest: MigrationManifest, record: CopiedFileRecord
    ) -> None:
        receipt = self._receipt_path(profile_dir, manifest, record.relative_path)
        if is_link_or_reparse(receipt) or not receipt.is_file():
            raise ValueError("migration file receipt is missing or unsafe")
        try:
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("receipt root must be an object")
            self._verify_receipt_integrity(payload)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("migration file receipt is malformed or unauthenticated") from exc
        unsigned = dict(payload)
        unsigned.pop("integrity_tag", None)
        if unsigned.get("migration_id") != manifest.migration_id or unsigned.get(
            "target_profile_id"
        ) != manifest.target_profile_id:
            raise ValueError("migration file receipt does not match manifest")
        actual_record = unsigned.get("record")
        expected_record = asdict(record)
        if not isinstance(actual_record, dict):
            raise ValueError("migration file receipt record is malformed")
        actual_state = actual_record.pop("state", None)
        expected_state = expected_record.pop("state", None)
        if actual_record != expected_record or actual_state not in {
            "planned",
            "committed",
        } or expected_state not in {"planned", "committed"}:
            raise ValueError("migration file receipt does not match manifest")

    def _recover_receipt_records(
        self, profile_dir: Path, manifest: MigrationManifest
    ) -> None:
        """Recover an intent record persisted just before a process crash."""
        if manifest.schema_version < 2 or not manifest.receipt_relative_path:
            return
        receipt_root = self._safe_child(
            profile_dir, manifest.receipt_relative_path, "migration receipts"
        )
        if not receipt_root.is_dir():
            return
        known = {record.relative_path for record in manifest.copied_files}
        for receipt in sorted(receipt_root.iterdir(), key=lambda p: p.name):
            if receipt.name.startswith(".") and receipt.name.endswith(".tmp"):
                continue
            if is_link_or_reparse(receipt) or not receipt.is_file():
                raise ValueError("migration receipt directory contains an unsafe entry")
            try:
                payload = json.loads(receipt.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("receipt root must be an object")
                self._verify_receipt_integrity(payload)
                record_data = payload["record"]
                if payload["migration_id"] != manifest.migration_id:
                    raise ValueError("migration receipt has the wrong migration_id")
                if payload["target_profile_id"] != manifest.target_profile_id:
                    raise ValueError("migration receipt has the wrong target profile")
                if not isinstance(record_data, dict):
                    raise ValueError("migration receipt record is malformed")
                record = dict(record_data)
                record.setdefault("destination_existed", False)
                record.setdefault("backup_relative_path", None)
                record.setdefault("redacted_paths", [])
                record.setdefault("state", "committed")
                record.setdefault("original_sha256", None)
                record.setdefault("original_size", None)
                recovered = CopiedFileRecord(**record)
            except (KeyError, TypeError, ValueError, OSError, UnicodeError) as exc:
                raise ValueError("migration receipt is malformed") from exc
            expected_receipt = self._receipt_path(
                profile_dir, manifest, recovered.relative_path
            )
            if receipt.name != expected_receipt.name:
                raise ValueError("migration receipt filename is not bound to its record")
            if recovered.relative_path in known:
                continue
            manifest.copied_files.append(recovered)
            known.add(recovered.relative_path)

    def _validate_rollback_manifest(
        self,
        profile_dir: Path,
        manifest: MigrationManifest,
        *,
        verify_integrity: bool = True,
    ) -> None:
        """Validate every untrusted manifest field before rollback can delete anything."""
        if not isinstance(manifest, MigrationManifest):
            raise ValueError("migration manifest has an invalid type")
        validate_profile_id(manifest.target_profile_id)
        if not isinstance(manifest.migration_id, str) or not _MIGRATION_ID_RE.fullmatch(
            manifest.migration_id
        ):
            raise ValueError("migration manifest migration_id is malformed")
        if not isinstance(manifest.source_path, str) or not isinstance(
            manifest.created_at, str
        ):
            raise ValueError("migration manifest metadata is malformed")
        if not isinstance(manifest.status, str):
            raise ValueError("migration manifest status is malformed")
        if manifest.schema_version not in {1, 2}:
            raise ValueError("unsupported migration manifest schema")
        if manifest.schema_version >= 2 and verify_integrity:
            self._verify_manifest_integrity(manifest)
        if manifest.schema_version == 1 and (
            manifest.receipt_relative_path is not None
            or manifest.parent_migration_id is not None
        ):
            raise ValueError("legacy migration manifest contains v2 metadata")
        if manifest.staging_relative_path is not None:
            expected = self._generated_directory_name("staging", manifest.migration_id)
            if manifest.staging_relative_path != expected:
                raise ValueError("migration staging path is not bound to migration_id")
        if manifest.backup_relative_path is not None:
            expected = self._generated_directory_name("backup", manifest.migration_id)
            if manifest.backup_relative_path != expected:
                raise ValueError("migration backup path is not bound to migration_id")
        if manifest.receipt_relative_path is not None:
            expected = self._generated_directory_name("receipts", manifest.migration_id)
            if manifest.receipt_relative_path != expected:
                raise ValueError("migration receipt path is not bound to migration_id")

        backup_root = manifest.backup_relative_path
        if manifest.parent_migration_id is not None and not _MIGRATION_ID_RE.fullmatch(
            manifest.parent_migration_id
        ):
            raise ValueError("migration parent migration_id is malformed")
        for record in manifest.copied_files:
            if not isinstance(record.relative_path, str) or "\\" in record.relative_path:
                raise ValueError("unsafe migration path in migration manifest")
            relative_path = self._normalise_relative_path(record.relative_path)
            if relative_path != record.relative_path:
                raise ValueError("migration manifest contains a non-canonical relative path")
            if not isinstance(record.size, int) or record.size < 0:
                raise ValueError("migration manifest contains an invalid file size")
            if not isinstance(record.sha256, str) or not re.fullmatch(
                r"[0-9a-fA-F]{64}", record.sha256
            ):
                raise ValueError("migration manifest contains an invalid SHA256")
            if not isinstance(record.copied_at, str) or not isinstance(
                record.destination_existed, bool
            ):
                raise ValueError("migration manifest file record is malformed")
            if record.state not in {"planned", "committed"}:
                raise ValueError("migration manifest file record state is malformed")
            if record.original_sha256 is not None and not re.fullmatch(
                r"[0-9a-fA-F]{64}", record.original_sha256
            ):
                raise ValueError("migration manifest original SHA256 is malformed")
            if record.original_size is not None and (
                not isinstance(record.original_size, int) or record.original_size < 0
            ):
                raise ValueError("migration manifest original size is malformed")
            if record.destination_existed and record.state == "planned" and (
                record.original_sha256 is None or record.original_size is None
            ):
                raise ValueError("planned overwrite record lacks original metadata")
            if record.backup_relative_path is not None:
                if backup_root is None:
                    raise ValueError("migration record has a backup without a backup root")
                expected_backup = f"{backup_root}/{relative_path}"
                if record.backup_relative_path != expected_backup:
                    raise ValueError("migration record backup is not bound to migration_id")
            elif record.destination_existed:
                # A missing backup is handled as a conflict, never as permission
                # to delete the imported file. Keep that legacy behavior.
                continue

        for child in manifest.child_migrations:
            if not isinstance(child, dict):
                raise ValueError("migration child record is malformed")
            child_id = child.get("profile_id")
            child_migration_id = child.get("migration_id")
            parent_migration_id = child.get("parent_migration_id")
            child_status = child.get("status", "committed")
            if not isinstance(child_id, str) or not isinstance(
                child_migration_id, str
            ) or not isinstance(parent_migration_id, str) or child_status not in {
                "planned",
                "committed",
            }:
                raise ValueError("migration child record is malformed")
            if parent_migration_id != manifest.migration_id:
                raise ValueError("migration child is not bound to its parent manifest")
            validate_profile_id(child_id)
            if not _MIGRATION_ID_RE.fullmatch(child_migration_id):
                raise ValueError("migration child record has an invalid migration_id")
            child_dir = self._validate_profile_dir(
                self.profile_mgr.get_profile_dir(child_id), child_id
            )
            child_manifest = self._read_manifest(child_dir)
            if child_manifest is None:
                if child_status == "planned":
                    continue
                raise ValueError("migration child manifest does not match its record")
            if child_manifest.migration_id != child_migration_id:
                raise ValueError("migration child manifest does not match its record")
            if child_manifest.parent_migration_id != manifest.migration_id:
                raise ValueError("migration child manifest is not bound to its parent")
            if child_manifest.child_migrations:
                raise ValueError("nested child migrations are not supported")
            self._validate_rollback_manifest(child_dir, child_manifest)

    def _remove_generated_directory(
        self, directory: Path, root: Path, expected_name: Optional[str] = None
    ) -> None:
        """Remove only a generated staging/backup directory under root."""
        if expected_name is not None and directory.name != expected_name:
            raise ValueError("generated migration directory name is invalid")
        if not directory.exists() and not is_link_or_reparse(directory):
            return
        if is_link_or_reparse(directory) or not self._is_within(directory, root):
            raise ValueError("generated migration directory is unsafe")
        if not directory.is_dir():
            raise ValueError("generated migration path is not a directory")
        shutil.rmtree(directory)

    def _read_manifest(self, profile_dir: Path) -> Optional[MigrationManifest]:
        manifest_file = self._safe_child(
            profile_dir, MIGRATION_MANIFEST_FILE, "migration manifest"
        )
        if not manifest_file.is_file() or is_link_or_reparse(manifest_file):
            return None
        try:
            raw = json.loads(manifest_file.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("manifest root must be an object")
            manifest = MigrationManifest.from_dict(raw)
            self._verify_manifest_integrity(manifest)
            return manifest
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            logger.error("Failed to read migration manifest: %s", exc)
            return None

    def _stage_file(
        self,
        plan: _FilePlan,
        stage_dir: Path,
    ) -> Tuple[Path, List[str]]:
        stage_file = self._safe_child(stage_dir, plan.relative_path, "migration staging")
        parent_relative = "/".join(plan.relative_path.split("/")[:-1])
        self._ensure_safe_directory(stage_dir, parent_relative)
        if plan.transform == "sanitise_config":
            content, redacted_paths = self._load_sanitised_config(plan.source)
            stage_file.write_text(content, encoding="utf-8")
        else:
            shutil.copy2(plan.source, stage_file)
            redacted_paths = []
        if is_link_or_reparse(stage_file) or not stage_file.is_file():
            raise ValueError("migration staging did not produce a regular file")
        return stage_file, redacted_paths

    @staticmethod
    def _backup_matches_record(backup: Path, record: CopiedFileRecord) -> bool:
        if record.original_sha256 is None or record.original_size is None:
            return False
        try:
            return (
                backup.stat().st_size == record.original_size
                and _compute_sha256(backup) == record.original_sha256
            )
        except OSError:
            return False

    @staticmethod
    def _destination_matches_original(
        destination: Path, record: CopiedFileRecord
    ) -> bool:
        if record.original_sha256 is None or record.original_size is None:
            return False
        try:
            return (
                destination.is_file()
                and destination.stat().st_size == record.original_size
                and _compute_sha256(destination) == record.original_sha256
            )
        except OSError:
            return False

    def _restore_committed_records(
        self,
        profile_dir: Path,
        records: List[CopiedFileRecord],
    ) -> None:
        """Compensate a failed commit; never overwrite an unexpected file."""
        for record in reversed(records):
            destination = self._safe_child(
                profile_dir, record.relative_path, "migration rollback"
            )
            if record.destination_existed:
                if not record.backup_relative_path:
                    raise ValueError(
                        f"missing overwrite backup for {record.relative_path}"
                    )
                backup = self._safe_child(
                    profile_dir,
                    record.backup_relative_path,
                    "migration backup",
                )
                if is_link_or_reparse(backup) or not backup.is_file():
                    raise ValueError(f"missing migration backup for {record.relative_path}")
                if not self._backup_matches_record(backup, record):
                    raise ValueError(f"migration backup integrity mismatch for {record.relative_path}")
                if is_link_or_reparse(destination):
                    raise ValueError(f"destination became a symlink: {record.relative_path}")
                if destination.exists():
                    if not destination.is_file() or _compute_sha256(destination) != record.sha256:
                        raise ValueError(
                            f"destination changed during failed migration: {record.relative_path}"
                        )
                    destination.unlink()
                os.replace(str(backup), str(destination))
            elif destination.exists():
                if is_link_or_reparse(destination) or not destination.is_file():
                    raise ValueError(f"unsafe destination during rollback: {record.relative_path}")
                if _compute_sha256(destination) != record.sha256:
                    raise ValueError(
                        f"destination changed during failed migration: {record.relative_path}"
                    )
                destination.unlink()

    @staticmethod
    def _new_migration_id() -> str:
        return f"mig_{int(time.time())}_{os.urandom(4).hex()}"

    def execute_migration(
        self,
        source_path: Path | str,
        target_profile_id: str = DEFAULT_PRIMARY_PROFILE_ID,
        components: Optional[Iterable[str]] = None,
        overwrite: bool = False,
        import_named_profiles: bool = False,
        _parent_migration_id: Optional[str] = None,
        _migration_id: Optional[str] = None,
    ) -> MigrationManifest:
        """Execute a staged, selective and reversible Hermes migration."""
        src = self._validate_source_root(source_path)
        validate_profile_id(target_profile_id)
        target_id = target_profile_id
        selected = self._normalise_components(components)

        target_info = self.profile_mgr.get_profile(target_id)
        if not target_info:
            target_info = self.profile_mgr.create_profile(
                profile_id=target_id,
                display_name=target_id.capitalize(),
                description=f"Imported from Hermes ({src})",
                is_primary=(target_id == DEFAULT_PRIMARY_PROFILE_ID),
            )
        target_dir = self._validate_profile_dir(target_info.path, target_id)

        existing_manifest = self._read_manifest(target_dir)
        if existing_manifest and existing_manifest.status in {
            "completed",
            "staged",
            "rollback_conflict",
        } and existing_manifest.copied_files:
            raise ValueError(
                "target profile has an active migration; roll it back before importing again"
            )

        migration_id = _migration_id or self._new_migration_id()
        if not _MIGRATION_ID_RE.fullmatch(migration_id):
            raise ValueError("migration_id is malformed")
        if _parent_migration_id is not None and not _MIGRATION_ID_RE.fullmatch(
            _parent_migration_id
        ):
            raise ValueError("migration parent migration_id is malformed")
        stage_name = self._generated_directory_name("staging", migration_id)
        backup_name = self._generated_directory_name("backup", migration_id)
        receipt_name = self._generated_directory_name("receipts", migration_id)
        stage_dir = target_dir / stage_name
        backup_dir = target_dir / backup_name
        receipt_dir = target_dir / receipt_name
        if any(
            is_link_or_reparse(directory) or directory.exists()
            for directory in (stage_dir, backup_dir, receipt_dir)
        ):
            raise FileExistsError("migration staging namespace already exists")

        manifest = MigrationManifest(
            migration_id=migration_id,
            source_path=str(src),
            target_profile_id=target_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            selected_components=sorted(selected),
            staging_relative_path=stage_name,
            backup_relative_path=backup_name,
            receipt_relative_path=receipt_name,
            parent_migration_id=_parent_migration_id,
        )
        transaction = _MigrationTransaction(
            stage_dir=stage_dir, backup_dir=backup_dir, receipt_dir=receipt_dir
        )
        child_manifests: List[MigrationManifest] = []

        try:
            plans, excluded_files = self._build_file_plans(src, target_dir, selected)
            manifest.excluded_files.extend(excluded_files)

            # Validate every destination and decide conflicts before any write.
            to_stage: List[_FilePlan] = []
            for plan in plans:
                destination = self._safe_child(
                    target_dir, plan.relative_path, "migration destination"
                )
                if is_link_or_reparse(destination):
                    raise ValueError(
                        f"migration destination contains a symlink: {plan.relative_path}"
                    )
                if destination.exists() and not destination.is_file():
                    raise ValueError(
                        f"migration destination is not a regular file: {plan.relative_path}"
                    )
                if destination.exists() and not overwrite:
                    manifest.skipped_files.append(
                        {"rel_path": plan.relative_path, "reason": "already_exists"}
                    )
                else:
                    to_stage.append(plan)

            stage_dir.mkdir()
            receipt_dir.mkdir()
            # Stage all content first.  A copy/parse failure leaves no imported
            # files in the profile because commit has not started yet.
            staged: Dict[str, Tuple[Path, List[str]]] = {}
            for plan in to_stage:
                staged[plan.relative_path] = self._stage_file(plan, stage_dir)
                redacted = staged[plan.relative_path][1]
                if redacted:
                    manifest.warnings.append(
                        "redacted config keys: " + ", ".join(sorted(redacted))
                    )

            manifest.status = "staged"
            self._save_manifest(target_dir, manifest)

            # Commit each already-staged file.  Existing files are copied to a
            # private backup before os.replace, so overwrite rollback restores
            # the original bytes rather than merely deleting the new file.
            for plan in to_stage:
                destination = self._safe_child(
                    target_dir, plan.relative_path, "migration destination"
                )
                destination_existed = destination.exists()
                if is_link_or_reparse(destination) or (
                    destination_existed and not destination.is_file()
                ):
                    raise ValueError(
                        f"migration destination changed unsafely: {plan.relative_path}"
                    )
                if destination_existed and not overwrite:
                    raise ValueError(
                        f"migration destination appeared during import: {plan.relative_path}"
                    )

                original_sha256: Optional[str] = None
                original_size: Optional[int] = None
                if destination_existed:
                    original_sha256 = _compute_sha256(destination)
                    original_size = destination.stat().st_size
                backup_relative_path: Optional[str] = None
                if destination_existed:
                    backup_relative_path = f"{backup_name}/{plan.relative_path}"
                    backup = self._safe_child(
                        target_dir, backup_relative_path, "migration backup"
                    )
                    self._ensure_safe_directory(
                        target_dir,
                        "/".join(backup_relative_path.split("/")[:-1]),
                    )
                    shutil.copy2(destination, backup)
                    transaction.backups_created.append(backup)

                stage_file, redacted_paths = staged[plan.relative_path]
                self._ensure_safe_directory(
                    target_dir,
                    "/".join(plan.relative_path.split("/")[:-1]),
                )
                record = CopiedFileRecord(
                    relative_path=plan.relative_path,
                    size=stage_file.stat().st_size,
                    sha256=_compute_sha256(stage_file),
                    copied_at=datetime.now(timezone.utc).isoformat(),
                    destination_existed=destination_existed,
                    backup_relative_path=backup_relative_path,
                    redacted_paths=redacted_paths,
                    state="planned",
                    original_sha256=original_sha256,
                    original_size=original_size,
                )
                manifest.copied_files.append(record)
                self._write_record_receipt(target_dir, manifest, record)
                self._save_manifest(target_dir, manifest)
                os.replace(str(stage_file), str(destination))
                transaction.committed.append(record)
                record.state = "committed"
                self._write_record_receipt(target_dir, manifest, record)
                self._save_manifest(target_dir, manifest)

            self._remove_generated_directory(
                stage_dir, target_dir, expected_name=stage_name
            )
            manifest.staging_relative_path = None
            manifest.status = "completed"
            self._save_manifest(target_dir, manifest)

            if import_named_profiles:
                named_root = src / "profiles"
                if named_root.exists():
                    self._assert_source_entry(named_root, src)
                    if not named_root.is_dir():
                        raise ValueError("Hermes named profiles path is not a directory")
                    seen_ids: Set[str] = set()
                    for sub in sorted(named_root.iterdir(), key=lambda p: p.name.casefold()):
                        if sub.name.startswith((".", "_")) or sub.name == "default":
                            continue
                        self._assert_source_entry(sub, src)
                        if not sub.is_dir():
                            raise ValueError("Hermes named profile is not a directory")
                        sub_id = sanitize_profile_id(sub.name)
                        validate_profile_id(sub_id)
                        if sub_id in seen_ids:
                            raise ValueError(
                                f"named profiles collide after ID normalization: {sub.name}"
                            )
                        seen_ids.add(sub_id)
                        child_migration_id = self._new_migration_id()
                        child_record = {
                            "profile_id": sub_id,
                            "migration_id": child_migration_id,
                            "parent_migration_id": manifest.migration_id,
                            "status": "planned",
                        }
                        manifest.child_migrations.append(child_record)
                        self._save_manifest(target_dir, manifest)
                        child = self.execute_migration(
                            source_path=sub,
                            target_profile_id=sub_id,
                            components=components,
                            overwrite=overwrite,
                            import_named_profiles=False,
                            _parent_migration_id=manifest.migration_id,
                            _migration_id=child_migration_id,
                        )
                        child_manifests.append(child)
                        child_record["status"] = "committed"
                        self._save_manifest(target_dir, manifest)
                    self._save_manifest(target_dir, manifest)

            return manifest

        except Exception:
            logger.exception("Migration failed; compensating destination changes")
            for child in reversed(child_manifests):
                try:
                    child_dir = self.profile_mgr.get_profile_dir(child.target_profile_id)
                    self.rollback_migration(child_dir, manifest=child)
                except Exception:
                    logger.exception("Failed to roll back child migration %s", child.migration_id)

            restore_ok = True
            try:
                self._restore_committed_records(target_dir, transaction.committed)
            except Exception:
                restore_ok = False
                logger.exception("Failed to compensate committed migration files")

            try:
                self._remove_generated_directory(
                    stage_dir, target_dir, expected_name=stage_name
                )
                if restore_ok:
                    self._remove_generated_directory(
                        backup_dir, target_dir, expected_name=backup_name
                    )
                    self._remove_generated_directory(
                        receipt_dir, target_dir, expected_name=receipt_name
                    )
            except Exception:
                logger.exception("Failed to clean migration temporary data")

            manifest.status = "failed" if restore_ok else "rollback_conflict"
            manifest.staging_relative_path = None
            if restore_ok:
                manifest.backup_relative_path = None
                manifest.receipt_relative_path = None
            try:
                self._save_manifest(target_dir, manifest)
            except Exception:
                logger.exception("Failed to persist failed migration manifest")
            raise

    # ----------------------------------------------------------------------
    # 4. ROLLBACK
    # ----------------------------------------------------------------------

    def _cleanup_rollback_artifacts(
        self, profile_dir: Path, manifest: MigrationManifest
    ) -> None:
        if manifest.staging_relative_path:
            staging = self._safe_child(
                profile_dir, manifest.staging_relative_path, "migration staging"
            )
            self._remove_generated_directory(
                staging,
                profile_dir,
                expected_name=self._generated_directory_name(
                    "staging", manifest.migration_id
                ),
            )
        if manifest.backup_relative_path:
            backup_root = self._safe_child(
                profile_dir, manifest.backup_relative_path, "migration backup"
            )
            self._remove_generated_directory(
                backup_root,
                profile_dir,
                expected_name=self._generated_directory_name(
                    "backup", manifest.migration_id
                ),
            )
        if manifest.receipt_relative_path:
            receipt_root = self._safe_child(
                profile_dir, manifest.receipt_relative_path, "migration receipts"
            )
            self._remove_generated_directory(
                receipt_root,
                profile_dir,
                expected_name=self._generated_directory_name(
                    "receipts", manifest.migration_id
                ),
            )

    def rollback_migration(
        self,
        target_profile_path: Path | str,
        manifest: Optional[MigrationManifest] = None,
    ) -> bool:
        """Rollback only files still matching the imported hash.

        Existing files are restored from backups.  A file edited or deleted by
        the user is reported as a conflict and is never overwritten or removed.
        """
        raw_pdir = Path(target_profile_path).expanduser()
        if not raw_pdir.exists() and not is_link_or_reparse(raw_pdir):
            return False
        if manifest is None:
            # A malformed or missing manifest fails closed without touching data.
            try:
                pdir = self._validate_profile_dir(raw_pdir)
            except ValueError:
                return False
            manifest = self._read_manifest(pdir)
            if manifest is None:
                return False
        else:
            validate_profile_id(manifest.target_profile_id)
            pdir = self._validate_profile_dir(raw_pdir, manifest.target_profile_id)

        if not pdir.is_dir():
            return False
        pdir = self._validate_profile_dir(pdir, manifest.target_profile_id)
        if manifest.schema_version >= 2:
            self._verify_manifest_integrity(manifest)
        self._recover_receipt_records(pdir, manifest)
        self._validate_rollback_manifest(pdir, manifest, verify_integrity=False)
        if manifest.status == "rolled_back":
            return True
        if manifest.schema_version == 1 and (
            manifest.copied_files
            or manifest.staging_relative_path is not None
            or manifest.backup_relative_path is not None
            or manifest.receipt_relative_path is not None
        ):
            manifest.rollback_conflicts = [
                {
                    "relative_path": "<legacy-manifest>",
                    "reason": "legacy manifest has no authenticated file receipts",
                }
            ]
            manifest.status = "rollback_conflict"
            self._save_manifest(pdir, manifest)
            return False

        prepared: List[Tuple[CopiedFileRecord, Path, Optional[Path]]] = []
        conflicts: List[Dict[str, str]] = []
        for record in manifest.copied_files:
            conflict_count = len(conflicts)
            if not re.fullmatch(r"[0-9a-fA-F]{64}", record.sha256):
                raise ValueError("migration manifest contains an invalid SHA256")
            destination = self._safe_child(
                pdir, record.relative_path, "migration rollback"
            )
            if is_link_or_reparse(destination):
                raise ValueError(
                    f"rollback destination contains a symlink: {record.relative_path}"
                )
            destination_exists = destination.exists()
            if destination_exists and not destination.is_file():
                raise ValueError(
                    f"rollback destination is not a regular file: {record.relative_path}"
                )

            backup: Optional[Path] = None
            if record.backup_relative_path:
                backup = self._safe_child(
                    pdir, record.backup_relative_path, "migration backup"
                )
                if is_link_or_reparse(backup) or not backup.is_file():
                    if record.destination_existed and self._destination_matches_original(
                        destination, record
                    ):
                        backup = None
                    else:
                        raise ValueError(
                            f"rollback backup is missing or unsafe: {record.relative_path}"
                        )
                if (
                    backup is not None
                    and manifest.schema_version >= 2
                    and not self._backup_matches_record(backup, record)
                ):
                    conflicts.append(
                        {
                            "relative_path": record.relative_path,
                            "reason": "rollback backup integrity mismatch",
                        }
                    )

            if record.state == "planned":
                # A crash can leave an intent record before replacement.  If the
                # old destination is still present, it is safe to leave it and
                # remove only generated backup data during rollback.
                if record.destination_existed:
                    if backup is None:
                        conflicts.append(
                            {
                                "relative_path": record.relative_path,
                                "reason": "overwrite backup is unavailable",
                            }
                        )
                    elif not destination_exists:
                        conflicts.append(
                            {
                                "relative_path": record.relative_path,
                                "reason": "original destination disappeared before commit",
                            }
                        )
                    else:
                        current_sha256 = _compute_sha256(destination)
                        if current_sha256 not in {
                            record.sha256,
                            record.original_sha256,
                        }:
                            conflicts.append(
                                {
                                    "relative_path": record.relative_path,
                                    "reason": "file changed during interrupted migration",
                                }
                            )
                elif destination_exists and _compute_sha256(destination) != record.sha256:
                    conflicts.append(
                        {
                            "relative_path": record.relative_path,
                            "reason": "file changed during interrupted migration",
                        }
                    )
            elif record.destination_existed:
                if self._destination_matches_original(destination, record):
                    pass
                elif backup is None:
                    conflicts.append(
                        {
                            "relative_path": record.relative_path,
                            "reason": "overwrite backup is unavailable",
                        }
                    )
                elif not destination_exists:
                    conflicts.append(
                        {
                            "relative_path": record.relative_path,
                            "reason": "imported file was deleted after migration",
                        }
                    )
                elif _compute_sha256(destination) != record.sha256:
                    conflicts.append(
                        {
                            "relative_path": record.relative_path,
                            "reason": "file changed after migration",
                        }
                    )
            elif destination_exists and _compute_sha256(destination) != record.sha256:
                conflicts.append(
                    {
                        "relative_path": record.relative_path,
                        "reason": "file changed after migration",
                    }
                )
            if len(conflicts) == conflict_count:
                destructive = destination_exists and (
                    record.state != "planned"
                    or _compute_sha256(destination) == record.sha256
                )
                if destructive and manifest.schema_version >= 2:
                    self._validate_record_receipt(pdir, manifest, record)
            prepared.append((record, destination, backup))

        if conflicts:
            manifest.rollback_conflicts = conflicts
            manifest.status = "rollback_conflict"
            self._save_manifest(pdir, manifest)
            return False

        try:
            for record, destination, backup in reversed(prepared):
                if record.state == "planned":
                    if not destination.exists():
                        continue
                    if record.destination_existed and (
                        _compute_sha256(destination) == record.original_sha256
                    ):
                        continue
                if record.destination_existed:
                    if self._destination_matches_original(destination, record):
                        continue
                    if backup is None:
                        raise ValueError(
                            f"rollback backup is unavailable: {record.relative_path}"
                        )
                    if destination.exists():
                        destination.unlink()
                    os.replace(str(backup), str(destination))
                elif destination.exists():
                    destination.unlink()

            if not manifest.child_migrations:
                self._cleanup_rollback_artifacts(pdir, manifest)
        except Exception:
            manifest.status = "rollback_failed"
            self._save_manifest(pdir, manifest)
            raise

        child_ok = True
        child_conflicts: List[Dict[str, str]] = []
        for child in manifest.child_migrations:
            child_id = child.get("profile_id", "")
            child_status = child.get("status", "committed")
            validate_profile_id(child_id)
            child_dir = self.profile_mgr.get_profile_dir(child_id)
            child_manifest = self._read_manifest(child_dir)
            if child_status == "planned" and child_manifest is None:
                child_ok = False
                child_conflicts.append(
                    {
                        "profile_id": child_id,
                        "reason": "planned child migration manifest is missing",
                    }
                )
                continue
            child_ok = self.rollback_migration(child_dir, manifest=child_manifest) and child_ok

        if child_ok and manifest.child_migrations:
            try:
                self._cleanup_rollback_artifacts(pdir, manifest)
            except Exception:
                manifest.status = "rollback_failed"
                self._save_manifest(pdir, manifest)
                raise

        manifest.rollback_conflicts = child_conflicts
        manifest.status = "rolled_back" if child_ok else "rollback_conflict"
        if child_ok:
            manifest.receipt_relative_path = None
        self._save_manifest(pdir, manifest)
        return child_ok

    def _save_manifest(self, profile_dir: Path, manifest: MigrationManifest) -> None:
        """Write an authenticated manifest atomically after boundary validation."""
        pdir = self._validate_profile_dir(profile_dir, manifest.target_profile_id)
        if manifest.schema_version >= 2:
            key = self._load_integrity_key(create=True)
            assert key is not None
            unsigned = manifest.to_dict()
            unsigned.pop("integrity_tag", None)
            manifest.integrity_tag = self._integrity_tag(unsigned, key)
        manifest_file = self._safe_child(
            pdir, MIGRATION_MANIFEST_FILE, "migration manifest"
        )
        tmp_file = self._safe_child(
            pdir, f".{MIGRATION_MANIFEST_FILE}.tmp", "migration manifest"
        )
        with tmp_file.open("w", encoding="utf-8") as handle:
            json.dump(manifest.to_dict(), handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(tmp_file), str(manifest_file))
        self._fsync_parent_directory(manifest_file.parent)
