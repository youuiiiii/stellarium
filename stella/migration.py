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
import json
import logging
import os
import re
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
    r"(?:api[_-]?keys?|access[_-]?tokens?|refresh[_-]?tokens?|"
    r"auth(?:orization)?|passwords?|passwd|secrets?|credentials?|"
    r"private[_-]?keys?|client[_-]?secrets?|cookies?|webhooks?|"
    r"headers?|env(?:ironment)?|connection[_-]?strings?|dsn)$",
    re.IGNORECASE,
)
_ENV_REFERENCE_SUFFIXES = ("_env", "_environment")
_CONNECTION_SECRET_RE = re.compile(r"://[^\s/@:]+:[^\s/@]+@")


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


@dataclass
class _RollbackConflict:
    relative_path: str
    reason: str


@dataclass
class _MigrationTransaction:
    stage_dir: Path
    backup_dir: Path
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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MigrationManifest":
        copied = []
        for raw_record in data.get("copied_files", []):
            record = dict(raw_record)
            # Keep manifests written by the first implementation readable.
            record.setdefault("destination_existed", False)
            record.setdefault("backup_relative_path", None)
            record.setdefault("redacted_paths", [])
            copied.append(CopiedFileRecord(**record))
        return cls(
            migration_id=data["migration_id"],
            source_path=data["source_path"],
            target_profile_id=data["target_profile_id"],
            created_at=data["created_at"],
            selected_components=data.get("selected_components", []),
            copied_files=copied,
            skipped_files=data.get("skipped_files", []),
            excluded_files=data.get("excluded_files", []),
            warnings=data.get("warnings", []),
            child_migrations=data.get("child_migrations", []),
            status=data.get("status", "completed"),
            rollback_conflicts=data.get("rollback_conflicts", []),
            staging_relative_path=data.get("staging_relative_path"),
            backup_relative_path=data.get("backup_relative_path"),
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
        if source_input.is_symlink():
            raise ValueError("Hermes source directory may not be a symlink or junction")
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
        if profile_path.is_symlink():
            raise ValueError("Stella profile directory may not be a symlink or junction")
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
        if not self._is_within(candidate, root):
            raise ValueError(f"{label} escapes its root: {relative_path!r}")

        cursor = root
        for part in normalised.split("/"):
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError(f"{label} contains a symlink or junction: {relative_path!r}")
            if cursor.exists() and not self._is_within(cursor, root):
                raise ValueError(f"{label} escapes its root: {relative_path!r}")
        return candidate

    def _assert_source_entry(self, path: Path, source_root: Path) -> None:
        if path.is_symlink():
            raise ValueError(f"Hermes source contains a symlink or junction: {path}")
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
        if root.is_symlink():
            raise ValueError(f"Hermes source contains a symlink or junction: {root}")
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
                if not normalised_key.endswith(_ENV_REFERENCE_SUFFIXES) and _SENSITIVE_KEY_RE.search(
                    normalised_key
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
        if isinstance(value, str) and _CONNECTION_SECRET_RE.search(value):
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
            if not source_dir.exists():
                return
            for source_file in self._iter_source_files(source_dir, source):
                relative = source_file.relative_to(source).as_posix()
                # Hidden files are deliberately not migratable, but are still
                # inspected by _iter_source_files so links cannot hide in them.
                if any(part.startswith(".") for part in source_file.relative_to(source_dir).parts):
                    continue
                add_file(source_file, relative, component)

        if "config" in selected:
            config_file = source / "config.yaml"
            if config_file.exists() and not config_file.is_dir():
                add_file(config_file, "config.yaml", "config", "sanitise_config")
            dotenv = source / ".env"
            if dotenv.exists() or dotenv.is_symlink():
                # Never inspect or copy its contents.  Recording the exclusion
                # makes the opt-in choice visible in preview/manifest output.
                excluded_files.append(".env")

        if "soul" in selected:
            for name in ("SOUL.md", "system_prompt.md", "AGENTS.md"):
                source_file = source / name
                if source_file.is_file() or source_file.is_symlink():
                    add_file(source_file, name, "soul")

        if "memories" in selected:
            for name in ("MEMORY.md", "USER.md"):
                source_file = source / name
                if source_file.is_file() or source_file.is_symlink():
                    add_file(source_file, f"memories/{name}", "memories")
            add_tree("memories", source / "memories")

        if "skills" in selected:
            add_tree("skills", source / "skills")

        if "cron" in selected:
            cron_dir = source / "cron"
            if cron_dir.exists():
                for source_file in self._iter_source_files(cron_dir, source):
                    if source_file.name.endswith((".db-wal", ".db-shm")):
                        continue
                    relative = source_file.relative_to(source).as_posix()
                    add_file(source_file, relative, "cron")

        if "sessions" in selected:
            add_tree("sessions", source / "sessions")

        return plans, excluded_files

    # ----------------------------------------------------------------------
    # 1. DISCOVERY
    # ----------------------------------------------------------------------

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
                resolved = c.resolve()
                if resolved not in seen and resolved != self.stella_home.resolve():
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
            excluded_for_component = [item for item in excluded if name == "config"]
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
            if current.is_symlink():
                raise ValueError("migration directory contains a symlink or junction")
            if current.exists():
                if not current.is_dir() or not self._is_within(current, root):
                    raise ValueError("migration directory escapes its root")
            else:
                current.mkdir()
        return current

    def _remove_generated_directory(self, directory: Path, root: Path) -> None:
        """Remove only a generated staging/backup directory under root."""
        if not directory.exists() and not directory.is_symlink():
            return
        if directory.is_symlink() or not self._is_within(directory, root):
            raise ValueError("generated migration directory is unsafe")
        if not directory.is_dir():
            raise ValueError("generated migration path is not a directory")
        shutil.rmtree(directory)

    def _read_manifest(self, profile_dir: Path) -> Optional[MigrationManifest]:
        manifest_file = self._safe_child(
            profile_dir, MIGRATION_MANIFEST_FILE, "migration manifest"
        )
        if not manifest_file.is_file() or manifest_file.is_symlink():
            return None
        try:
            raw = json.loads(manifest_file.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("manifest root must be an object")
            return MigrationManifest.from_dict(raw)
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
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
        if stage_file.is_symlink() or not stage_file.is_file():
            raise ValueError("migration staging did not produce a regular file")
        return stage_file, redacted_paths

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
                if backup.is_symlink() or not backup.is_file():
                    raise ValueError(f"missing migration backup for {record.relative_path}")
                if destination.is_symlink():
                    raise ValueError(f"destination became a symlink: {record.relative_path}")
                if destination.exists():
                    if not destination.is_file() or _compute_sha256(destination) != record.sha256:
                        raise ValueError(
                            f"destination changed during failed migration: {record.relative_path}"
                        )
                    destination.unlink()
                os.replace(str(backup), str(destination))
            elif destination.exists():
                if destination.is_symlink() or not destination.is_file():
                    raise ValueError(f"unsafe destination during rollback: {record.relative_path}")
                if _compute_sha256(destination) != record.sha256:
                    raise ValueError(
                        f"destination changed during failed migration: {record.relative_path}"
                    )
                destination.unlink()

    def execute_migration(
        self,
        source_path: Path | str,
        target_profile_id: str = DEFAULT_PRIMARY_PROFILE_ID,
        components: Optional[Iterable[str]] = None,
        overwrite: bool = False,
        import_named_profiles: bool = False,
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

        migration_id = f"mig_{int(time.time())}_{os.urandom(4).hex()}"
        stage_name = f".stella-migration-staging-{migration_id}"
        backup_name = f".stella-migration-backups-{migration_id}"
        stage_dir = target_dir / stage_name
        backup_dir = target_dir / backup_name
        if stage_dir.exists() or stage_dir.is_symlink() or backup_dir.exists() or backup_dir.is_symlink():
            raise FileExistsError("migration staging namespace already exists")

        manifest = MigrationManifest(
            migration_id=migration_id,
            source_path=str(src),
            target_profile_id=target_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            selected_components=sorted(selected),
            staging_relative_path=stage_name,
            backup_relative_path=backup_name,
        )
        transaction = _MigrationTransaction(stage_dir=stage_dir, backup_dir=backup_dir)
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
                if destination.is_symlink():
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
                if destination.is_symlink() or (
                    destination_existed and not destination.is_file()
                ):
                    raise ValueError(
                        f"migration destination changed unsafely: {plan.relative_path}"
                    )
                if destination_existed and not overwrite:
                    raise ValueError(
                        f"migration destination appeared during import: {plan.relative_path}"
                    )

                backup_relative_path: Optional[str] = None
                if destination_existed:
                    backup_relative_path = (
                        f"{backup_name}/{plan.relative_path}"
                    )
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
                )
                os.replace(str(stage_file), str(destination))
                transaction.committed.append(record)
                manifest.copied_files.append(record)

            self._remove_generated_directory(stage_dir, target_dir)
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
                        child = self.execute_migration(
                            source_path=sub,
                            target_profile_id=sub_id,
                            components=components,
                            overwrite=overwrite,
                            import_named_profiles=False,
                        )
                        child_manifests.append(child)
                        manifest.child_migrations.append(
                            {
                                "profile_id": child.target_profile_id,
                                "migration_id": child.migration_id,
                            }
                        )
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
                self._remove_generated_directory(stage_dir, target_dir)
                if restore_ok:
                    self._remove_generated_directory(backup_dir, target_dir)
            except Exception:
                logger.exception("Failed to clean migration temporary data")

            manifest.status = "failed" if restore_ok else "rollback_conflict"
            manifest.staging_relative_path = None
            if restore_ok:
                manifest.backup_relative_path = None
            try:
                self._save_manifest(target_dir, manifest)
            except Exception:
                logger.exception("Failed to persist failed migration manifest")
            raise

    # ----------------------------------------------------------------------
    # 4. ROLLBACK
    # ----------------------------------------------------------------------

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
        if not raw_pdir.exists() and not raw_pdir.is_symlink():
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
        if manifest.status == "rolled_back":
            return True

        prepared: List[Tuple[CopiedFileRecord, Path, Optional[Path]]] = []
        conflicts: List[Dict[str, str]] = []
        for record in manifest.copied_files:
            if not re.fullmatch(r"[0-9a-fA-F]{64}", record.sha256):
                raise ValueError("migration manifest contains an invalid SHA256")
            destination = self._safe_child(
                pdir, record.relative_path, "migration rollback"
            )
            if destination.is_symlink():
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
                if backup.is_symlink() or not backup.is_file():
                    raise ValueError(
                        f"rollback backup is missing or unsafe: {record.relative_path}"
                    )

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
            prepared.append((record, destination, backup))

        if conflicts:
            manifest.rollback_conflicts = conflicts
            manifest.status = "rollback_conflict"
            self._save_manifest(pdir, manifest)
            return False

        try:
            for record, destination, backup in reversed(prepared):
                if record.destination_existed:
                    assert backup is not None
                    if destination.exists():
                        destination.unlink()
                    os.replace(str(backup), str(destination))
                elif destination.exists():
                    destination.unlink()

            if manifest.staging_relative_path:
                staging = self._safe_child(
                    pdir, manifest.staging_relative_path, "migration staging"
                )
                self._remove_generated_directory(staging, pdir)
            if manifest.backup_relative_path:
                backup_root = self._safe_child(
                    pdir, manifest.backup_relative_path, "migration backup"
                )
                self._remove_generated_directory(backup_root, pdir)
        except Exception:
            manifest.status = "rollback_failed"
            self._save_manifest(pdir, manifest)
            raise

        child_ok = True
        for child in manifest.child_migrations:
            child_id = child.get("profile_id", "")
            validate_profile_id(child_id)
            child_dir = self.profile_mgr.get_profile_dir(child_id)
            child_ok = self.rollback_migration(child_dir) and child_ok

        manifest.rollback_conflicts = []
        manifest.status = "rolled_back" if child_ok else "rollback_conflict"
        self._save_manifest(pdir, manifest)
        return child_ok

    def _save_manifest(self, profile_dir: Path, manifest: MigrationManifest) -> None:
        """Write manifest atomically after validating its profile boundary."""
        pdir = self._validate_profile_dir(profile_dir, manifest.target_profile_id)
        manifest_file = self._safe_child(
            pdir, MIGRATION_MANIFEST_FILE, "migration manifest"
        )
        tmp_file = self._safe_child(
            pdir, f".{MIGRATION_MANIFEST_FILE}.tmp", "migration manifest"
        )
        tmp_file.write_text(
            json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(str(tmp_file), str(manifest_file))
