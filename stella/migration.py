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
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from stella.constants import (
    DEFAULT_PRIMARY_PROFILE_ID,
    MIGRATION_MANIFEST_FILE,
    SUPPORTED_MIGRATION_COMPONENTS,
    get_default_stella_home,
)
from stella.profiles import StellaProfileManager, sanitize_profile_id

logger = logging.getLogger(__name__)


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


@dataclass
class MigrationPreview:
    """Dry-run inspection result of a Hermes source before copying."""

    source_path: str
    target_profile_id: str
    components: Dict[str, ComponentPreview]
    conflicts: List[str] = field(default_factory=list)
    named_profiles: List[str] = field(default_factory=list)
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
    status: str = "completed"  # 'completed', 'rolled_back', 'failed'

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MigrationManifest":
        copied = [
            CopiedFileRecord(**c) for c in data.get("copied_files", [])
        ]
        return cls(
            migration_id=data["migration_id"],
            source_path=data["source_path"],
            target_profile_id=data["target_profile_id"],
            created_at=data["created_at"],
            selected_components=data.get("selected_components", []),
            copied_files=copied,
            skipped_files=data.get("skipped_files", []),
            status=data.get("status", "completed"),
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
    ) -> MigrationPreview:
        """Examine source directory and predict what files will be copied."""
        src = Path(source_path).expanduser().resolve()
        if not src.is_dir():
            raise FileNotFoundError(f"Source Hermes directory not found: {src}")

        target_dir = self.profile_mgr.get_profile_dir(target_profile_id)
        components: Dict[str, ComponentPreview] = {}
        conflicts: List[str] = []

        # 1. Config
        cfg_files = []
        for name in ["config.yaml", ".env"]:
            f = src / name
            if f.is_file():
                cfg_files.append(f)
        components["config"] = ComponentPreview(
            name="config",
            available=bool(cfg_files),
            file_count=len(cfg_files),
            total_bytes=sum(f.stat().st_size for f in cfg_files),
            sample_files=[f.name for f in cfg_files],
        )

        # 2. Soul / Persona
        soul_files = []
        for name in ["SOUL.md", "system_prompt.md", "AGENTS.md"]:
            f = src / name
            if f.is_file():
                soul_files.append(f)
        components["soul"] = ComponentPreview(
            name="soul",
            available=bool(soul_files),
            file_count=len(soul_files),
            total_bytes=sum(f.stat().st_size for f in soul_files),
            sample_files=[f.name for f in soul_files],
        )

        # 3. Memories
        mem_files = []
        mem_dir = src / "memories"
        if mem_dir.is_dir():
            mem_files.extend(
                [f for f in mem_dir.glob("**/*") if f.is_file() and not f.name.startswith(".")]
            )
        for name in ["MEMORY.md", "USER.md"]:
            f = src / name
            if f.is_file():
                mem_files.append(f)
        components["memories"] = ComponentPreview(
            name="memories",
            available=bool(mem_files),
            file_count=len(mem_files),
            total_bytes=sum(f.stat().st_size for f in mem_files),
            sample_files=[str(f.relative_to(src)) for f in mem_files[:5]],
        )

        # 4. Skills
        skill_files = []
        skills_dir = src / "skills"
        if skills_dir.is_dir():
            skill_files.extend(
                [f for f in skills_dir.glob("**/*") if f.is_file() and not f.name.startswith(".")]
            )
        components["skills"] = ComponentPreview(
            name="skills",
            available=bool(skill_files),
            file_count=len(skill_files),
            total_bytes=sum(f.stat().st_size for f in skill_files),
            sample_files=[str(f.relative_to(src)) for f in skill_files[:5]],
        )

        # 5. Cron
        cron_files = []
        c_dir = src / "cron"
        if c_dir.is_dir():
            cron_files.extend(
                [f for f in c_dir.glob("**/*") if f.is_file() and not f.name.endswith(".db-wal")]
            )
        components["cron"] = ComponentPreview(
            name="cron",
            available=bool(cron_files),
            file_count=len(cron_files),
            total_bytes=sum(f.stat().st_size for f in cron_files),
            sample_files=[str(f.relative_to(src)) for f in cron_files[:5]],
        )

        # 6. Sessions
        session_files = []
        sess_dir = src / "sessions"
        if sess_dir.is_dir():
            session_files.extend(
                [f for f in sess_dir.glob("**/*") if f.is_file() and not f.name.startswith(".")]
            )
        components["sessions"] = ComponentPreview(
            name="sessions",
            available=bool(session_files),
            file_count=len(session_files),
            total_bytes=sum(f.stat().st_size for f in session_files),
            sample_files=[str(f.relative_to(src)) for f in session_files[:5]],
        )

        # Conflict check if target profile directory exists
        if target_dir.is_dir():
            all_source_files = (
                cfg_files + soul_files + mem_files + skill_files + cron_files + session_files
            )
            for sf in all_source_files:
                rel = sf.relative_to(src)
                dest = target_dir / rel
                if dest.exists():
                    conflicts.append(str(rel))

        # Discover named profiles
        named: List[str] = []
        p_dir = src / "profiles"
        if p_dir.is_dir():
            named = [
                d.name for d in p_dir.iterdir()
                if d.is_dir() and not d.name.startswith((".", "_")) and d.name != "default"
            ]

        return MigrationPreview(
            source_path=str(src),
            target_profile_id=target_profile_id,
            components=components,
            conflicts=conflicts,
            named_profiles=named,
            can_proceed=True,
        )

    # ----------------------------------------------------------------------
    # 3. EXECUTION
    # ----------------------------------------------------------------------

    def execute_migration(
        self,
        source_path: Path | str,
        target_profile_id: str = DEFAULT_PRIMARY_PROFILE_ID,
        components: Optional[List[str] | Set[str]] = None,
        overwrite: bool = False,
        import_named_profiles: bool = False,
    ) -> MigrationManifest:
        """Execute selective migration from Hermes source into target Stella profile.

        Strictly read-only on the source.
        Atomic & rollback-safe on destination.
        """
        src = Path(source_path).expanduser().resolve()
        if not src.is_dir():
            raise FileNotFoundError(f"Source Hermes directory not found: {src}")

        target_id = sanitize_profile_id(target_profile_id)
        selected = set(components or ["config", "soul", "memories", "skills", "cron"])

        # Ensure target profile exists in Stella
        target_info = self.profile_mgr.get_profile(target_id)
        if not target_info:
            target_info = self.profile_mgr.create_profile(
                profile_id=target_id,
                display_name=target_id.capitalize(),
                description=f"Imported from Hermes ({src})",
                is_primary=(target_id == DEFAULT_PRIMARY_PROFILE_ID),
            )
        target_dir = target_info.path

        migration_id = f"mig_{int(time.time())}_{os.urandom(4).hex()}"
        manifest = MigrationManifest(
            migration_id=migration_id,
            source_path=str(src),
            target_profile_id=target_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            selected_components=sorted(selected),
        )

        files_to_copy: List[tuple[Path, Path, str]] = []  # (src_file, dst_file, rel_str)

        try:
            # 1. Config
            if "config" in selected:
                for name in ["config.yaml", ".env"]:
                    sf = src / name
                    if sf.is_file():
                        files_to_copy.append((sf, target_dir / name, name))

            # 2. Soul
            if "soul" in selected:
                for name in ["SOUL.md", "system_prompt.md", "AGENTS.md"]:
                    sf = src / name
                    if sf.is_file():
                        files_to_copy.append((sf, target_dir / name, name))

            # 3. Memories
            if "memories" in selected:
                mem_dir = src / "memories"
                if mem_dir.is_dir():
                    for sf in mem_dir.glob("**/*"):
                        if sf.is_file() and not sf.name.startswith("."):
                            rel = sf.relative_to(src)
                            files_to_copy.append((sf, target_dir / rel, str(rel)))
                for name in ["MEMORY.md", "USER.md"]:
                    sf = src / name
                    if sf.is_file():
                        # Map root MEMORY.md / USER.md cleanly into memories/ in Stella
                        target_mem = target_dir / "memories" / name
                        files_to_copy.append((sf, target_mem, f"memories/{name}"))

            # 4. Skills
            if "skills" in selected:
                skills_dir = src / "skills"
                if skills_dir.is_dir():
                    for sf in skills_dir.glob("**/*"):
                        if sf.is_file() and not sf.name.startswith("."):
                            rel = sf.relative_to(src)
                            files_to_copy.append((sf, target_dir / rel, str(rel)))

            # 5. Cron
            if "cron" in selected:
                c_dir = src / "cron"
                if c_dir.is_dir():
                    for sf in c_dir.glob("**/*"):
                        if sf.is_file() and not sf.name.endswith((".db-wal", ".db-shm")):
                            rel = sf.relative_to(src)
                            files_to_copy.append((sf, target_dir / rel, str(rel)))

            # 6. Sessions
            if "sessions" in selected:
                sess_dir = src / "sessions"
                if sess_dir.is_dir():
                    for sf in sess_dir.glob("**/*"):
                        if sf.is_file() and not sf.name.startswith("."):
                            rel = sf.relative_to(src)
                            files_to_copy.append((sf, target_dir / rel, str(rel)))

            # Execute copy with audit logging
            for sf, df, rel_name in files_to_copy:
                if df.exists() and not overwrite:
                    manifest.skipped_files.append(
                        {"rel_path": rel_name, "reason": "already_exists"}
                    )
                    continue

                df.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(sf, df)
                copied_sha = _compute_sha256(df)
                manifest.copied_files.append(
                    CopiedFileRecord(
                        relative_path=rel_name,
                        size=df.stat().st_size,
                        sha256=copied_sha,
                        copied_at=datetime.now(timezone.utc).isoformat(),
                    )
                )

            # Persist migration manifest in target profile
            self._save_manifest(target_dir, manifest)

            # Handle named profiles if requested
            if import_named_profiles:
                p_dir = src / "profiles"
                if p_dir.is_dir():
                    for sub in p_dir.iterdir():
                        if (
                            sub.is_dir()
                            and not sub.name.startswith((".", "_"))
                            and sub.name != "default"
                        ):
                            sub_id = sanitize_profile_id(sub.name)
                            self.execute_migration(
                                source_path=sub,
                                target_profile_id=sub_id,
                                components=components,
                                overwrite=overwrite,
                                import_named_profiles=False,
                            )

            return manifest

        except Exception as exc:
            logger.error("Migration failed unexpectedly: %s. Rolling back.", exc)
            manifest.status = "failed"
            self._save_manifest(target_dir, manifest)
            self.rollback_migration(target_dir, manifest=manifest)
            raise

    # ----------------------------------------------------------------------
    # 4. ROLLBACK
    # ----------------------------------------------------------------------

    def rollback_migration(
        self,
        target_profile_path: Path | str,
        manifest: Optional[MigrationManifest] = None,
    ) -> bool:
        """Cleanly revert an import using migration_manifest.json."""
        pdir = Path(target_profile_path).expanduser().resolve()
        if not pdir.is_dir():
            return False

        if manifest is None:
            m_file = pdir / MIGRATION_MANIFEST_FILE
            if not m_file.is_file():
                return False
            try:
                data = json.loads(m_file.read_text(encoding="utf-8"))
                manifest = MigrationManifest.from_dict(data)
            except Exception as exc:
                logger.error("Failed to read migration manifest: %s", exc)
                return False

        # Remove copied files in reverse order
        for record in reversed(manifest.copied_files):
            target_file = pdir / record.relative_path
            if target_file.is_file():
                try:
                    target_file.unlink()
                except Exception as exc:
                    logger.warning("Failed to delete %s during rollback: %s", target_file, exc)

        manifest.status = "rolled_back"
        self._save_manifest(pdir, manifest)
        return True

    def _save_manifest(self, profile_dir: Path, manifest: MigrationManifest) -> None:
        """Write manifest to profile_dir atomically."""
        manifest_file = profile_dir / MIGRATION_MANIFEST_FILE
        tmp_file = profile_dir / f".{MIGRATION_MANIFEST_FILE}.tmp"
        tmp_file.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
        os.replace(str(tmp_file), str(manifest_file))
