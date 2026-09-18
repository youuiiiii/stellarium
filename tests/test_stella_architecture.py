"""Unit tests for Stella nested profile layout and Hermes migration engine."""

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from hermes_cli.web_routers import stella as stella_api

from stella.constants import (
    DEFAULT_PRIMARY_PROFILE_ID,
    DEFAULT_PRIMARY_PROFILE_NAME,
    MIGRATION_MANIFEST_FILE,
    PROFILE_METADATA_FILE,
    STANDARD_PROFILE_SUBDIRS,
    STELLA_CACHE_DIR_NAME,
    STELLA_PROFILES_DIR_NAME,
    STELLA_SHARED_DIR_NAME,
)
from stella.migration import (
    CopiedFileRecord,
    HermesMigrationEngine,
    MigrationManifest,
)
from stella.profiles import StellaProfileManager, sanitize_profile_id, validate_profile_id


# ---------------------------------------------------------------------------
# Stella Profiles Tests
# ---------------------------------------------------------------------------

def test_sanitize_and_validate_profile_id():
    assert sanitize_profile_id("My Personal Profile") == "my-personal-profile"
    assert sanitize_profile_id("stella_01") == "stella_01"
    assert sanitize_profile_id("!!!") != ""

    validate_profile_id("stella")
    validate_profile_id("p_123456")
    validate_profile_id("work-profile")

    with pytest.raises(ValueError):
        validate_profile_id("../../traversal")
    with pytest.raises(ValueError):
        validate_profile_id("has space")


def test_stella_root_layout_and_default_profile(tmp_path: Path):
    mgr = StellaProfileManager(root=tmp_path)
    created = mgr.ensure_root_layout(auto_create_default=True)

    assert created is not None
    assert created.id == DEFAULT_PRIMARY_PROFILE_ID
    assert created.display_name == DEFAULT_PRIMARY_PROFILE_NAME
    assert created.is_primary is True

    # Root folders must exist
    assert (tmp_path / STELLA_PROFILES_DIR_NAME).is_dir()
    assert (tmp_path / STELLA_SHARED_DIR_NAME).is_dir()
    assert (tmp_path / STELLA_CACHE_DIR_NAME).is_dir()

    # Subdirectories for default profile
    pdir = created.path
    assert pdir.is_dir()
    for sub in STANDARD_PROFILE_SUBDIRS:
        assert (pdir / sub).is_dir()

    assert (pdir / PROFILE_METADATA_FILE).is_file()
    assert (pdir / "SOUL.md").is_file()
    assert (pdir / "config.yaml").is_file()


def test_create_and_update_profile(tmp_path: Path):
    mgr = StellaProfileManager(root=tmp_path)
    mgr.ensure_root_layout(auto_create_default=True)

    p2 = mgr.create_profile(
        display_name="Work Sanctum",
        description="Profile for work tasks",
        tags=["coding", "analysis"],
    )

    assert p2.id == "work-sanctum"
    assert p2.display_name == "Work Sanctum"
    assert p2.description == "Profile for work tasks"
    assert p2.is_primary is False
    assert "coding" in p2.tags

    # Rename / update display name without renaming directory
    updated = mgr.update_profile(
        profile_id="work-sanctum",
        display_name="Executive Sanctum",
        description="Updated description",
    )
    assert updated.display_name == "Executive Sanctum"
    assert updated.description == "Updated description"
    assert updated.path.name == "work-sanctum"  # Directory name preserved

    # Verify persistence on disk
    read_back = mgr.get_profile("work-sanctum")
    assert read_back is not None
    assert read_back.display_name == "Executive Sanctum"


def test_delete_profile_with_archive(tmp_path: Path):
    mgr = StellaProfileManager(root=tmp_path)
    mgr.ensure_root_layout(auto_create_default=True)

    p = mgr.create_profile(display_name="Temporary")
    pid = p.id
    assert mgr.get_profile(pid) is not None

    # Delete (archive)
    assert mgr.delete_profile(pid, archive=True) is True
    assert mgr.get_profile(pid) is None

    # Check that archive exists in .deleted
    deleted_dir = tmp_path / STELLA_PROFILES_DIR_NAME / ".deleted"
    assert deleted_dir.is_dir()
    archives = list(deleted_dir.glob(f"{pid}_*"))
    assert len(archives) == 1

    # Deleting primary requires force
    with pytest.raises(ValueError):
        mgr.delete_profile(DEFAULT_PRIMARY_PROFILE_ID, force=False)


def test_profile_manager_ignores_symlinked_profile_entry(tmp_path: Path):
    mgr = StellaProfileManager(root=tmp_path / "stella_home")
    mgr.ensure_root_layout(auto_create_default=False)
    outside = tmp_path / "outside-profile"
    outside.mkdir()
    (outside / PROFILE_METADATA_FILE).write_text(
        json.dumps({"id": "outside", "display_name": "Outside"}),
        encoding="utf-8",
    )
    link = mgr.profiles_dir / "outside"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this host")

    assert all(profile.id != "outside" for profile in mgr.list_profiles())


def test_profile_manager_rejects_symlinked_profiles_root(tmp_path: Path):
    stella_home = tmp_path / "stella_home"
    stella_home.mkdir()
    outside = tmp_path / "outside-root"
    outside.mkdir()
    try:
        (stella_home / STELLA_PROFILES_DIR_NAME).symlink_to(
            outside, target_is_directory=True
        )
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this host")

    with pytest.raises(ValueError, match="symlink|junction"):
        StellaProfileManager(root=stella_home).ensure_root_layout(
            auto_create_default=False
        )


# ---------------------------------------------------------------------------
# Hermes -> Stella Migration Tests
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_hermes_installation(tmp_path: Path) -> Path:
    """Create a mock Hermes home directory with realistic components."""
    hermes_root = tmp_path / "fake_hermes"
    hermes_root.mkdir(parents=True)

    # Config & Soul
    (hermes_root / "config.yaml").write_text("model: test-model\n", encoding="utf-8")
    (hermes_root / ".env").write_text("API_KEY=secret\n", encoding="utf-8")
    (hermes_root / "SOUL.md").write_text("# Old Hermes Persona\n", encoding="utf-8")

    # Memories
    mem_dir = hermes_root / "memories"
    mem_dir.mkdir()
    (mem_dir / "user_facts.txt").write_text("Fact 1\nFact 2\n", encoding="utf-8")
    (hermes_root / "MEMORY.md").write_text("Core memory note\n", encoding="utf-8")

    # Skills
    skill_dir = hermes_root / "skills" / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("name: my-skill\n", encoding="utf-8")

    # Cron
    cron_dir = hermes_root / "cron"
    cron_dir.mkdir()
    (cron_dir / "jobs.json").write_text('{"jobs": [{"id": "j1"}]}', encoding="utf-8")

    # Named sub-profile
    sub_profile = hermes_root / "profiles" / "sub_bot"
    sub_profile.mkdir(parents=True)
    (sub_profile / "config.yaml").write_text("model: sub-model\n", encoding="utf-8")

    return hermes_root


def test_hermes_detection_and_preview(tmp_path: Path, fake_hermes_installation: Path):
    stella_root = tmp_path / "stella_home"
    engine = HermesMigrationEngine(stella_home=stella_root)

    detected = engine.detect_hermes_installations(extra_paths=[fake_hermes_installation])
    assert len(detected) >= 1
    found = next((d for d in detected if d.path == fake_hermes_installation.resolve()), None)
    assert found is not None
    assert found.has_config is True
    assert found.has_soul is True
    assert "sub_bot" in found.named_profiles
    assert found.memory_count >= 2
    assert found.skill_count >= 1

    preview = engine.preview_migration(fake_hermes_installation, target_profile_id="stella")
    assert preview.components["config"].available is True
    assert preview.components["soul"].available is True
    assert preview.components["memories"].available is True
    assert preview.components["skills"].available is True
    assert preview.components["cron"].available is True
    assert "sub_bot" in preview.named_profiles


def test_hermes_migration_execution_and_rollback(tmp_path: Path, fake_hermes_installation: Path):
    stella_root = tmp_path / "stella_home"
    engine = HermesMigrationEngine(stella_home=stella_root)

    # Record source file hashes before migration to ensure source remains untouched
    source_cfg = (fake_hermes_installation / "config.yaml").read_text(encoding="utf-8")
    source_soul = (fake_hermes_installation / "SOUL.md").read_text(encoding="utf-8")

    manifest = engine.execute_migration(
        source_path=fake_hermes_installation,
        target_profile_id="stella",
        components=["config", "soul", "memories", "skills"],
        overwrite=True,
    )

    assert manifest.status == "completed"
    assert len(manifest.copied_files) > 0

    # 1. Verify source was NEVER modified (Strict Read-Only invariant)
    assert (fake_hermes_installation / "config.yaml").read_text(encoding="utf-8") == source_cfg
    assert (fake_hermes_installation / "SOUL.md").read_text(encoding="utf-8") == source_soul

    # 2. Verify destination received files strictly inside profiles/stella/
    target_pdir = stella_root / STELLA_PROFILES_DIR_NAME / "stella"
    assert target_pdir.is_dir()
    assert (target_pdir / "config.yaml").is_file()
    assert (target_pdir / "SOUL.md").is_file()
    assert (target_pdir / "skills" / "my-skill" / "SKILL.md").is_file()
    assert (target_pdir / MIGRATION_MANIFEST_FILE).is_file()

    # 3. Test Rollback
    rollback_ok = engine.rollback_migration(target_pdir)
    assert rollback_ok is True

    # After rollback, copied files must be cleaned up
    assert not (target_pdir / "skills" / "my-skill" / "SKILL.md").exists()
    m_data = json.loads((target_pdir / MIGRATION_MANIFEST_FILE).read_text(encoding="utf-8"))
    assert m_data["status"] == "rolled_back"


# ---------------------------------------------------------------------------
# Stella Web API Router Tests
# ---------------------------------------------------------------------------

def test_stella_web_api_routes(tmp_path: Path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hermes_cli.web_routers.stella import router as stella_router

    monkeypatch.setenv("STELLA_HOME", str(tmp_path / "stella_web_test"))
    app = FastAPI()
    app.include_router(stella_router)
    client = TestClient(app)

    # 1. List profiles
    resp = client.get("/api/stella/profiles")
    assert resp.status_code == 200
    data = resp.json()
    assert "profiles" in data
    assert len(data["profiles"]) >= 1
    assert data["profiles"][0]["id"] == "stella"

    # 2. Create profile
    resp = client.post(
        "/api/stella/profiles",
        json={"display_name": "API Studio", "description": "Created via API"},
    )
    assert resp.status_code == 200
    created = resp.json()["profile"]
    assert created["id"] == "api-studio"
    assert created["display_name"] == "API Studio"

    # 3. Update profile display name
    resp = client.patch(
        f"/api/stella/profiles/{created['id']}",
        json={"display_name": "Pro Studio"},
    )
    assert resp.status_code == 200
    assert resp.json()["profile"]["display_name"] == "Pro Studio"

    # 4. Migration detect
    resp = client.get("/api/stella/migration/detect")
    assert resp.status_code == 200
    assert "detected" in resp.json()


def test_stella_cli_dispatch(tmp_path: Path, monkeypatch, capsys):
    from hermes_cli.subcommands.stella_cmd import cmd_stella
    import argparse

    monkeypatch.setenv("STELLA_HOME", str(tmp_path / "stella_cli_test"))

    # Test 'stella profile list'
    args = argparse.Namespace(stella_subcommand="profile", stella_profile_action="list")
    code = cmd_stella(args)
    assert code == 0
    captured = capsys.readouterr()
    assert "Stella Profiles" in captured.out
    assert "Stella" in captured.out

    # Test 'stella profile create'
    args = argparse.Namespace(
        stella_subcommand="profile",
        stella_profile_action="create",
        name="Gaming Zone",
        profile_id="gaming",
        desc="Gaming assistant",
        primary=False,
    )
    code = cmd_stella(args)
    assert code == 0
    captured = capsys.readouterr()
    assert "Created Stella profile" in captured.out

    # Test 'stella profile rename'
    args = argparse.Namespace(
        stella_subcommand="profile",
        stella_profile_action="rename",
        id="gaming",
        new_name="Arcade Zone",
    )
    code = cmd_stella(args)
    assert code == 0
    captured = capsys.readouterr()
    assert "Renamed profile" in captured.out


def test_first_profile_created_directly_is_primary(tmp_path: Path):
    mgr = StellaProfileManager(root=tmp_path)
    profile = mgr.create_profile(display_name="First Workspace")
    assert profile.is_primary is True
    assert mgr.get_primary_profile().id == profile.id


def test_receipt_commit_interruption_is_recoverable(tmp_path: Path, monkeypatch):
    source = tmp_path / "hermes_source"
    (source / "skills").mkdir(parents=True)
    (source / "skills" / "safe.md").write_text("safe import\\n", encoding="utf-8")
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    original_write = engine._write_record_receipt
    calls = {"count": 0}

    def interrupt_after_receipt(*args, **kwargs):
        calls["count"] += 1
        result = original_write(*args, **kwargs)
        if calls["count"] == 2:
            raise KeyboardInterrupt
        return result

    monkeypatch.setattr(engine, "_write_record_receipt", interrupt_after_receipt)
    with pytest.raises(KeyboardInterrupt):
        engine.execute_migration(source, components=["skills"])

    profile_dir = engine.profile_mgr.get_profile_dir("stella")
    assert (profile_dir / "skills" / "safe.md").exists()
    assert engine.rollback_migration(profile_dir) is True
    assert not (profile_dir / "skills" / "safe.md").exists()


def test_rollback_retry_after_backup_consumed(tmp_path: Path, monkeypatch):
    import stella.migration as migration_module

    source = tmp_path / "hermes_source"
    source.mkdir()
    (source / "config.yaml").write_text("model: new\n", encoding="utf-8")
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    profile = engine.profile_mgr.create_profile("Target", profile_id="target")
    destination = profile.path / "config.yaml"
    destination.write_text("model: old\n", encoding="utf-8")

    manifest = engine.execute_migration(
        source, target_profile_id="target", components=["config"], overwrite=True
    )
    real_replace = migration_module.os.replace

    def consume_backup_then_interrupt(src, dst):
        if ".stella-migration-backups-" in str(src):
            real_replace(src, dst)
            raise KeyboardInterrupt
        return real_replace(src, dst)

    monkeypatch.setattr(migration_module.os, "replace", consume_backup_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        engine.rollback_migration(profile.path)

    monkeypatch.setattr(migration_module.os, "replace", real_replace)
    assert destination.read_text(encoding="utf-8").startswith("model: old")
    assert engine.rollback_migration(profile.path) is True


def test_receipt_recovery_rehydrates_missing_manifest_record(tmp_path: Path):
    source = tmp_path / "hermes_source"
    (source / "skills").mkdir(parents=True)
    (source / "skills" / "safe.md").write_text("safe import\n", encoding="utf-8")
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    manifest = engine.execute_migration(source, components=["skills"])
    profile = engine.profile_mgr.get_profile_dir(manifest.target_profile_id)
    imported = profile / "skills" / "safe.md"
    assert imported.exists()

    manifest.copied_files = []
    manifest.status = "staged"
    engine._save_manifest(profile, manifest)

    assert engine.rollback_migration(profile) is True
    assert not imported.exists()


def test_named_child_receipt_interruption_recovers_via_parent(
    tmp_path: Path, monkeypatch
):
    source = tmp_path / "hermes_source"
    (source / "profiles" / "child" / "skills").mkdir(parents=True)
    (source / "profiles" / "child" / "skills" / "safe.md").write_text(
        "child import\\n", encoding="utf-8"
    )
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    original_write = engine._write_record_receipt
    calls = {"count": 0}

    def interrupt_child_receipt(profile_dir, manifest, record):
        calls["count"] += 1
        result = original_write(profile_dir, manifest, record)
        if calls["count"] == 2:
            raise KeyboardInterrupt
        return result

    monkeypatch.setattr(engine, "_write_record_receipt", interrupt_child_receipt)
    with pytest.raises(KeyboardInterrupt):
        engine.execute_migration(
            source, target_profile_id="parent", components=["skills"], import_named_profiles=True
        )

    child_dir = engine.profile_mgr.get_profile_dir("child")
    assert (child_dir / "skills" / "safe.md").exists()
    parent_dir = engine.profile_mgr.get_profile_dir("parent")
    assert engine.rollback_migration(parent_dir) is True
    assert not (child_dir / "skills" / "safe.md").exists()


def test_planned_child_without_manifest_reports_conflict(tmp_path: Path):
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    parent = engine.profile_mgr.create_profile("Parent", profile_id="parent")
    child = engine.profile_mgr.create_profile("Child", profile_id="child")
    parent_manifest = MigrationManifest(
        migration_id="mig_123_abcdef41",
        source_path=str(tmp_path / "source"),
        target_profile_id=parent.id,
        created_at="now",
        selected_components=[],
        child_migrations=[
            {
                "profile_id": child.id,
                "migration_id": "mig_123_abcdef42",
                "parent_migration_id": "mig_123_abcdef41",
                "status": "planned",
            }
        ],
    )
    engine._save_manifest(parent.path, parent_manifest)

    assert engine.rollback_migration(parent.path) is False
    persisted = engine._read_manifest(parent.path)
    assert persisted is not None
    assert persisted.status == "rollback_conflict"
    assert child.path.exists()


def test_legacy_manifest_rollback_is_non_destructive(tmp_path: Path):
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    profile = engine.profile_mgr.create_profile("Legacy", profile_id="legacy")
    imported = profile.path / "skills" / "legacy.md"
    imported.parent.mkdir(parents=True, exist_ok=True)
    imported.write_text("legacy import\\n", encoding="utf-8")
    raw = {
        "migration_id": "mig_123_abcdef31",
        "source_path": str(tmp_path / "old-hermes"),
        "target_profile_id": "legacy",
        "created_at": "2026-01-01T00:00:00+00:00",
        "selected_components": ["skills"],
        "copied_files": [
            {
                "relative_path": "skills/legacy.md",
                "size": imported.stat().st_size,
                "sha256": hashlib.sha256(imported.read_bytes()).hexdigest(),
                "copied_at": "2026-01-01T00:00:00+00:00",
            }
        ],
        "status": "completed",
    }
    (profile.path / MIGRATION_MANIFEST_FILE).write_text(
        json.dumps(raw), encoding="utf-8"
    )

    assert engine.rollback_migration(profile.path) is False
    assert imported.read_text(encoding="utf-8") == "legacy import\\n"


def test_legacy_manifest_hash_conflict_preserves_user_edit(tmp_path: Path):
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    profile = engine.profile_mgr.create_profile("Legacy", profile_id="legacy")
    imported = profile.path / "skills" / "legacy.md"
    imported.parent.mkdir(parents=True, exist_ok=True)
    imported.write_text("user edit\\n", encoding="utf-8")
    raw = {
        "migration_id": "mig_123_abcdef32",
        "source_path": str(tmp_path / "old-hermes"),
        "target_profile_id": "legacy",
        "created_at": "2026-01-01T00:00:00+00:00",
        "selected_components": ["skills"],
        "copied_files": [
            {
                "relative_path": "skills/legacy.md",
                "size": 13,
                "sha256": "0" * 64,
                "copied_at": "2026-01-01T00:00:00+00:00",
            }
        ],
        "status": "completed",
    }
    (profile.path / MIGRATION_MANIFEST_FILE).write_text(
        json.dumps(raw), encoding="utf-8"
    )

    assert engine.rollback_migration(profile.path) is False
    assert imported.read_text(encoding="utf-8") == "user edit\\n"


def test_interrupted_commit_recovers_from_planned_record(tmp_path: Path, monkeypatch):
    import stella.migration as migration_module

    source = tmp_path / "hermes_source"
    (source / "skills").mkdir(parents=True)
    (source / "skills" / "safe.md").write_text("safe skill\\n", encoding="utf-8")
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")

    real_replace = migration_module.os.replace

    def replace_then_interrupt(source_name, destination_name):
        if "stella-migration-staging-" in str(source_name) and str(destination_name).endswith(
            "safe.md"
        ):
            real_replace(source_name, destination_name)
            raise KeyboardInterrupt("simulated process crash")
        return real_replace(source_name, destination_name)

    monkeypatch.setattr(migration_module.os, "replace", replace_then_interrupt)
    with pytest.raises(KeyboardInterrupt, match="simulated process crash"):
        engine.execute_migration(source, components=["skills"])

    profile_dir = engine.profile_mgr.get_profile_dir("stella")
    manifest = engine._read_manifest(profile_dir)
    assert manifest is not None
    assert manifest.status == "staged"
    assert manifest.copied_files[0].state == "planned"
    assert engine.rollback_migration(profile_dir) is True
    assert not (profile_dir / "skills" / "safe.md").exists()


def test_non_config_sensitive_files_are_excluded(tmp_path: Path):
    source = tmp_path / "hermes_source"
    (source / "cron").mkdir(parents=True)
    (source / "skills").mkdir()
    (source / "cron" / "jobs.json").write_text(
        '{"jobs": [{"token": "synthetic-value"}]}', encoding="utf-8"
    )
    (source / "cron" / ".hidden-job").write_text("hidden cron\n", encoding="utf-8")

    (source / "skills" / "signature.txt").write_text(
        "signature: synthetic-signature-value\n", encoding="utf-8"
    )
    (source / "skills" / "credentials.json").write_text(
        '{"credential": "synthetic-value"}', encoding="utf-8"
    )
    (source / "skills" / "safe.md").write_text("safe skill\\n", encoding="utf-8")
    (source / "skills" / "notes.txt").write_text(
        "endpoint=https://example.invalid/api?token=synthetic-query-secret&signature=synthetic-signature&client_secret=synthetic-client-secret#access_token=synthetic-fragment-secret\n",
        encoding="utf-8",
    )
    (source / "skills" / "readme.txt").write_text(
        "token_env=literal-non-config-value\n",
        encoding="utf-8",
    )
    (source / "skills" / "reference.txt").write_text(
        "token_env=${TOKEN_REFERENCE}\n",
        encoding="utf-8",
    )
    pem_marker = "-----BEGIN " + "PRIVATE" + " KEY-----\n"
    pem_marker += "synthetic-key-material\n"
    pem_marker += "-----END " + "PRIVATE" + " KEY-----\n"
    (source / "skills" / "notes.pem.txt").write_text(
        pem_marker,
        encoding="utf-8",
    )

    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    preview = engine.preview_migration(source, components=["cron", "skills"])

    assert "cron/jobs.json" in preview.excluded_files
    assert "cron/.hidden-job" in preview.excluded_files
    assert "skills/signature.txt" in preview.excluded_files
    assert "skills/credentials.json" in preview.excluded_files
    assert "skills/notes.txt" in preview.excluded_files
    assert "skills/notes.pem.txt" in preview.excluded_files
    assert "skills/readme.txt" in preview.excluded_files
    assert "skills/reference.txt" not in preview.excluded_files
    assert "skills/safe.md" not in preview.excluded_files
    assert preview.components["cron"].file_count == 0
    assert set(preview.components["cron"].excluded_files) == {
        "cron/.hidden-job",
        "cron/jobs.json",
    }
    assert preview.components["skills"].file_count == 2
    assert "skills/signature.txt" in preview.components["skills"].excluded_files
    assert set(preview.components["skills"].excluded_files) == {
        "skills/credentials.json",
        "skills/notes.pem.txt",
        "skills/signature.txt",
        "skills/notes.txt",
        "skills/readme.txt",
    }
    assert "skills/credentials.json" in preview.components["skills"].excluded_files
    assert "skills/notes.txt" in preview.components["skills"].excluded_files

    manifest = engine.execute_migration(source, components=["cron", "skills"])
    profile_dir = engine.profile_mgr.get_profile_dir(manifest.target_profile_id)
    assert not (profile_dir / "cron" / "jobs.json").exists()
    assert not (profile_dir / "cron" / ".hidden-job").exists()
    assert not (profile_dir / "skills" / "signature.txt").exists()
    assert not (profile_dir / "skills" / "credentials.json").exists()
    assert not (profile_dir / "skills" / "notes.txt").exists()
    assert (profile_dir / "skills" / "reference.txt").read_text(encoding="utf-8").startswith("token_env=${TOKEN_REFERENCE}")
    assert (profile_dir / "skills" / "safe.md").read_text(encoding="utf-8") == "safe skill\\n"


def test_config_migration_excludes_dotenv_and_sanitizes_inline_credentials(
    tmp_path: Path, fake_hermes_installation: Path
):
    (fake_hermes_installation / "config.yaml").write_text(
        "model: safe-model\n"
        "providers:\n"
        "  custom:\n"
        "    base_url: https://example.test/v1\n"
        "    endpoint: https://example.invalid/api?token=synthetic-query-secret&signature=synthetic-signature&client_secret=synthetic-client-secret\n"
        "    redirect_url: 'https://example.invalid/callback#access_token=synthetic-fragment-secret'\n"
        "    api_key: should-not-be-copied\n"
        "    api_keys: [another-secret]\n"
        "    token: synthetic-token-value\n"
        "    clientSecret: synthetic-client-value\n"
        "    headers:\n"
        "      Authorization: Bearer raw-header-secret\n"
        "    env:\n"
        "      OPENAI_API_KEY: raw-env-secret\n"
        "    key_env: ${SAFE_PROVIDER_KEY}\n"
        "    token_env: literal-token-value\n"
        "    token_upper_env: BARE_LITERAL\n"
        "    token_reference_env: ${TOKEN_REFERENCE}\n",
        encoding="utf-8",
    )
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")

    manifest = engine.execute_migration(
        fake_hermes_installation,
        components=["config"],
        overwrite=True,
    )

    target = tmp_path / "stella_home" / "profiles" / "stella"
    config_text = (target / "config.yaml").read_text(encoding="utf-8")
    assert "safe-model" in config_text
    assert "synthetic-query-secret" not in config_text
    assert "synthetic-signature" not in config_text
    assert "synthetic-client-secret" not in config_text
    assert "synthetic-fragment-secret" not in config_text
    assert "should-not-be-copied" not in config_text
    assert "another-secret" not in config_text
    assert "synthetic-token-value" not in config_text
    assert "synthetic-client-value" not in config_text
    assert "raw-header-secret" not in config_text
    assert "literal-token-value" not in config_text
    assert "BARE_LITERAL" not in config_text
    assert "SAFE_PROVIDER_KEY" in config_text
    assert "${TOKEN_REFERENCE}" in config_text
    assert "raw-env-secret" not in config_text
    assert "api_key" not in config_text
    assert "key_env: ${SAFE_PROVIDER_KEY}" in config_text
    assert not (target / ".env").exists()
    assert ".env" in manifest.excluded_files


def test_component_selection_rejects_empty_and_unknown_components(
    tmp_path: Path, fake_hermes_installation: Path
):
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")

    with pytest.raises(ValueError, match="component"):
        engine.execute_migration(fake_hermes_installation, components=[])
    with pytest.raises(ValueError, match="Unknown migration component"):
        engine.execute_migration(fake_hermes_installation, components=["secrets"])


def test_migration_rejects_source_inside_stella_home(
    tmp_path: Path, fake_hermes_installation: Path
):
    stella_home = tmp_path / "stella_home"
    source_inside = stella_home / "not-hermes"
    source_inside.mkdir(parents=True)
    (source_inside / "config.yaml").write_text("model: unsafe\n", encoding="utf-8")
    engine = HermesMigrationEngine(stella_home=stella_home)

    with pytest.raises(ValueError, match="outside Stella home"):
        engine.execute_migration(source_inside, components=["config"])


def test_rollback_rejects_manifest_path_escape(tmp_path: Path):
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    profile = engine.profile_mgr.create_profile("Target")
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("keep me", encoding="utf-8")
    manifest = MigrationManifest(
        migration_id="mig_123_abcdef12",
        source_path=str(tmp_path / "source"),
        target_profile_id=profile.id,
        created_at="now",
        selected_components=["config"],
        copied_files=[
            CopiedFileRecord(
                relative_path="..\\sentinel",
                size=7,
                sha256="0" * 64,
                copied_at="now",
            )
        ],
    )

    engine._save_manifest(profile.path, manifest)
    with pytest.raises(ValueError, match="unsafe migration path"):
        engine.rollback_migration(profile.path, manifest=manifest)
    assert sentinel.read_text(encoding="utf-8") == "keep me"


def test_migration_rejects_symlinked_source_files(
    tmp_path: Path, fake_hermes_installation: Path
):
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = fake_hermes_installation / "skills" / "linked.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this host")

    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    with pytest.raises(ValueError, match="symlink"):
        engine.execute_migration(
            fake_hermes_installation,
            components=["skills"],
            overwrite=True,
        )


def test_rollback_with_malformed_manifest_is_fail_closed(tmp_path: Path):
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    profile = engine.profile_mgr.create_profile("Target")
    manifest_file = profile.path / MIGRATION_MANIFEST_FILE
    manifest_file.write_text("{not-json", encoding="utf-8")

    assert engine.rollback_migration(profile.path) is False
    assert manifest_file.read_text(encoding="utf-8") == "{not-json"


def test_destination_symlink_is_rejected(
    tmp_path: Path, fake_hermes_installation: Path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "linked.md").write_text("outside", encoding="utf-8")
    target_root = tmp_path / "stella_home"
    engine = HermesMigrationEngine(stella_home=target_root)
    profile = engine.profile_mgr.create_profile("Target")
    skills_dir = profile.path / "skills"
    shutil.rmtree(skills_dir)
    try:
        skills_dir.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this host")

    with pytest.raises(ValueError, match="symlink"):
        engine.execute_migration(
            fake_hermes_installation,
            target_profile_id=profile.id,
            components=["skills"],
            overwrite=True,
        )
    assert not (outside / "skill.md").exists()


def test_overwrite_rollback_restores_original_file(
    tmp_path: Path, fake_hermes_installation: Path
):
    stella_home = tmp_path / "stella_home"
    engine = HermesMigrationEngine(stella_home=stella_home)
    profile = engine.profile_mgr.create_profile("Target")
    target_config = profile.path / "config.yaml"
    target_config.write_text("model: original\n", encoding="utf-8")
    (fake_hermes_installation / "config.yaml").write_text(
        "model: imported\n", encoding="utf-8"
    )

    manifest = engine.execute_migration(
        fake_hermes_installation,
        target_profile_id=profile.id,
        components=["config"],
        overwrite=True,
    )
    assert target_config.read_text(encoding="utf-8") == "model: imported\n"

    assert engine.rollback_migration(profile.path, manifest=manifest) is True
    assert target_config.read_text(encoding="utf-8") == "model: original\n"


def test_rollback_rejects_tampered_backup(
    tmp_path: Path, fake_hermes_installation: Path
):
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    profile = engine.profile_mgr.create_profile("Target")
    target_config = profile.path / "config.yaml"
    target_config.write_text("model: original\\n", encoding="utf-8")
    (fake_hermes_installation / "config.yaml").write_text(
        "model: imported\\n", encoding="utf-8"
    )

    manifest = engine.execute_migration(
        fake_hermes_installation,
        target_profile_id=profile.id,
        components=["config"],
        overwrite=True,
    )
    assert manifest.backup_relative_path is not None
    backup_relative = manifest.copied_files[0].backup_relative_path
    assert backup_relative is not None
    backup = profile.path / backup_relative.replace("/", os.sep)
    backup.write_text("tampered backup\\n", encoding="utf-8")

    assert engine.rollback_migration(profile.path, manifest=manifest) is False
    assert target_config.read_text(encoding="utf-8").startswith("model: imported")
    assert "tampered backup" not in target_config.read_text(encoding="utf-8")
    assert manifest.rollback_conflicts


def test_rollback_preserves_file_modified_after_import(
    tmp_path: Path, fake_hermes_installation: Path
):
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    profile = engine.profile_mgr.create_profile("Target")
    imported = profile.path / "skills" / "skill.md"
    source_skill = fake_hermes_installation / "skills" / "skill.md"
    source_skill.write_text("imported\n", encoding="utf-8")

    manifest = engine.execute_migration(
        fake_hermes_installation,
        target_profile_id=profile.id,
        components=["skills"],
        overwrite=True,
    )
    imported.write_text("user edit\n", encoding="utf-8")

    assert engine.rollback_migration(profile.path, manifest=manifest) is False
    assert imported.read_text(encoding="utf-8") == "user edit\n"
    assert manifest.rollback_conflicts


def test_copy_failure_is_transactional(
    tmp_path: Path, fake_hermes_installation: Path, monkeypatch: pytest.MonkeyPatch
):
    source_skills = fake_hermes_installation / "skills"
    (source_skills / "a.md").write_text("a\n", encoding="utf-8")
    (source_skills / "b.md").write_text("b\n", encoding="utf-8")
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    original_copy2 = shutil.copy2
    calls = 0

    def fail_on_second_copy(source, destination, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected copy failure")
        return original_copy2(source, destination, *args, **kwargs)

    monkeypatch.setattr("stella.migration.shutil.copy2", fail_on_second_copy)
    with pytest.raises(OSError, match="injected copy failure"):
        engine.execute_migration(
            fake_hermes_installation,
            components=["skills"],
            overwrite=True,
        )

    target_skills = tmp_path / "stella_home" / "profiles" / "stella" / "skills"
    assert not (target_skills / "a.md").exists()
    assert not (target_skills / "b.md").exists()


def test_named_profile_import_rolls_back_parent_when_child_fails(
    tmp_path: Path, fake_hermes_installation: Path, monkeypatch: pytest.MonkeyPatch
):
    named = fake_hermes_installation / "profiles" / "child"
    named.mkdir(parents=True)
    (named / "SOUL.md").write_text("child\n", encoding="utf-8")
    (fake_hermes_installation / "SOUL.md").write_text("parent\n", encoding="utf-8")
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    parent_profile = engine.profile_mgr.create_profile("stella")
    parent_soul = parent_profile.path / "SOUL.md"
    parent_scaffold = parent_soul.read_text(encoding="utf-8")
    original_execute = engine.execute_migration
    calls = 0

    def fail_child(*args, **kwargs):
        nonlocal calls
        calls += 1
        if kwargs.get("import_named_profiles") is False and calls >= 1:
            raise OSError("child migration failure")
        return original_execute(*args, **kwargs)

    monkeypatch.setattr(engine, "execute_migration", fail_child)
    with pytest.raises(OSError, match="child migration failure"):
        original_execute(
            fake_hermes_installation,
            components=["soul"],
            overwrite=True,
            import_named_profiles=True,
        )

    child_soul = tmp_path / "stella_home" / "profiles" / "child" / "SOUL.md"
    assert parent_soul.read_text(encoding="utf-8") == parent_scaffold
    assert not child_soul.exists()


def test_stella_api_rejects_invalid_profile_id(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("STELLA_HOME", str(tmp_path / "stella_home"))

    with pytest.raises(HTTPException) as caught:
        asyncio.run(stella_api.get_stella_profile("../outside"))
    assert caught.value.status_code == 400


def test_stella_api_preview_preserves_empty_component_selection(
    tmp_path: Path, fake_hermes_installation: Path, monkeypatch
):
    monkeypatch.setenv("STELLA_HOME", str(tmp_path / "stella_home"))
    body = stella_api.MigrationPreviewRequest(
        source_path=str(fake_hermes_installation),
        target_profile_id="stella",
        components=[],
    )

    with pytest.raises(HTTPException) as caught:
        asyncio.run(stella_api.preview_hermes_migration(body))
    assert caught.value.status_code == 400


def test_stella_api_maps_migration_conflict_to_409(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("STELLA_HOME", str(tmp_path / "stella_home"))
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    profile = engine.profile_mgr.create_profile("Target")
    manifest = MigrationManifest(
        migration_id="mig_123_abcdef13",
        source_path=str(tmp_path / "source"),
        target_profile_id=profile.id,
        created_at="now",
        selected_components=["skills"],
        copied_files=[
            CopiedFileRecord(
                relative_path="skills/changed.md",
                size=3,
                sha256="0" * 64,
                copied_at="now",
            )
        ],
    )
    target_file = profile.path / "skills" / "changed.md"
    target_file.write_text("user", encoding="utf-8")
    engine._save_manifest(profile.path, manifest)

    with pytest.raises(HTTPException) as caught:
        asyncio.run(stella_api.rollback_hermes_migration(
            stella_api.MigrationRollbackRequest(target_profile_id=profile.id)
        ))
    assert caught.value.status_code == 409


# ---------------------------------------------------------------------------
# Stella Filesystem & Runtime Safety Tests
# ---------------------------------------------------------------------------

def test_stella_filesystem_link_detection(tmp_path: Path):
    from stella.filesystem import is_link_or_reparse, assert_no_link_or_reparse

    normal_file = tmp_path / "normal.txt"
    normal_file.write_text("ok", encoding="utf-8")
    assert not is_link_or_reparse(normal_file)
    assert_no_link_or_reparse(normal_file, "normal_file")


def test_stella_runtime_resolution_and_scope(tmp_path: Path, monkeypatch):
    from stella.runtime import (
        activate_profile,
        get_active_profile,
        resolve_active_profile_home,
        resolve_profile_home,
        runtime_scope,
    )

    stella_root = tmp_path / "stella_runtime_root"
    monkeypatch.setenv("STELLA_HOME", str(stella_root))

    # Initially defaults to primary 'stella' profile
    active = get_active_profile(root=stella_root)
    assert active is not None
    assert active.id == "stella"
    assert resolve_active_profile_home(root=stella_root) == active.path
    assert resolve_profile_home("stella", root=stella_root) == active.path

    # Create & activate a new profile
    from stella.profiles import StellaProfileManager
    mgr = StellaProfileManager(root=stella_root)
    mgr.create_profile("Studio Pro", profile_id="studio-pro")

    activated = activate_profile("studio-pro", root=stella_root)
    assert activated.id == "studio-pro"
    assert get_active_profile(root=stella_root).id == "studio-pro"

    # Context manager runtime_scope
    with runtime_scope("studio-pro", root=stella_root) as prof:
        assert prof.id == "studio-pro"
        from hermes_constants import get_hermes_home
        # Inside the scope, Hermes HOME resolver resolves to the profile dir
        assert Path(get_hermes_home()).resolve() == prof.path.resolve()


def test_startup_fast_uses_platform_default_stella_profile(tmp_path: Path, monkeypatch):
    if sys.platform != "win32":
        pytest.skip("platform-default assertion is Windows-specific")
    local_appdata = tmp_path / "local_appdata"
    profile = local_appdata / "stella" / "profiles" / "active"
    profile.mkdir(parents=True)
    (local_appdata / "stella" / "active_profile").write_text(
        "active\n", encoding="utf-8"
    )
    monkeypatch.delenv("STELLA_HOME", raising=False)
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))

    from hermes_cli._startup_fast import _resolved_home

    assert Path(_resolved_home()).resolve() == profile.resolve()


def test_early_startup_uses_active_stella_profile(tmp_path: Path, monkeypatch):
    root = tmp_path / "stella_home"
    profile = root / "profiles" / "active"
    profile.mkdir(parents=True)
    (root / "active_profile").write_text("active\n", encoding="utf-8")
    (profile / "config.yaml").write_text(
        "display:\n  interface: tui\n", encoding="utf-8"
    )
    monkeypatch.setenv("STELLA_HOME", str(root))
    monkeypatch.delenv("HERMES_HOME", raising=False)

    import hermes_cli.main as hermes_main
    from hermes_cli._startup_fast import _resolved_home

    monkeypatch.setattr(hermes_main, "_EARLY_INTERFACE_CACHE", None)
    assert hermes_main._config_default_interface_early() == "tui"
    assert Path(_resolved_home()).resolve() == profile.resolve()


def test_watchdog_uses_active_stella_profile(tmp_path: Path, monkeypatch):
    import hermes_startup_watchdog as watchdog

    stella_root = tmp_path / "stella_home"
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setenv("STELLA_HOME", str(stella_root))
    manager = StellaProfileManager(root=stella_root)
    profile = manager.create_profile("Active", profile_id="active")
    manager.set_active_profile(profile.id)

    assert watchdog._process_hermes_home() == profile.path


def test_unreadable_gateway_pid_requires_profile_home(tmp_path: Path, monkeypatch):
    import gateway.status as status

    expected_home = tmp_path / "profiles" / "target"
    other_home = tmp_path / "profiles" / "other"
    record = {
        "kind": status._GATEWAY_KIND,
        "argv": ["hermes", "gateway", "run"],
        "hermes_home": str(other_home),
    }
    monkeypatch.setattr(status, "_read_process_cmdline", lambda _pid: None)
    assert not status._record_matches_live_gateway_pid(
        record, 123, expected_home=expected_home
    )
    record["hermes_home"] = str(expected_home)
    assert status._record_matches_live_gateway_pid(
        record, 123, expected_home=expected_home
    )


def test_process_identity_is_stable_after_active_profile_switch(tmp_path: Path):
    script = """
from pathlib import Path
import sys
from stella.profiles import StellaProfileManager
from gateway.status import _get_process_hermes_home
from hermes_cli._startup_fast import _resolved_home
root = Path(sys.argv[1])
manager = StellaProfileManager(root=root)
manager.create_profile("Alpha", profile_id="alpha")
manager.create_profile("Beta", profile_id="beta")
manager.set_active_profile("alpha")
first = _get_process_hermes_home()
fast_first = _resolved_home()
manager.set_active_profile("beta")
second = _get_process_hermes_home()
fast_second = _resolved_home()
print(first == second and first.name == "alpha" and fast_first == fast_second)
"""
    env = os.environ.copy()
    env.pop("HERMES_HOME", None)
    env["STELLA_HOME"] = str(tmp_path / "stella_home")
    result = subprocess.run(
        [sys.executable, "-c", script, env["STELLA_HOME"]],
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
        env=env,
        check=True,
    )
    assert result.stdout.strip() == "True"


def test_gateway_identity_uses_active_stella_profile(tmp_path: Path, monkeypatch):
    from gateway.status import _get_process_hermes_home
    from stella.profiles import StellaProfileManager

    stella_root = tmp_path / "stella_gateway_root"
    manager = StellaProfileManager(root=stella_root)
    manager.ensure_root_layout(auto_create_default=True)
    profile = manager.create_profile("Gateway", profile_id="gateway")
    manager.set_active_profile(profile.id)
    monkeypatch.setenv("STELLA_HOME", str(stella_root))
    monkeypatch.delenv("HERMES_HOME", raising=False)

    assert _get_process_hermes_home() == profile.path


def test_profile_directory_name_is_canonical_identity(tmp_path: Path):
    mgr = StellaProfileManager(root=tmp_path / "stella_home")
    mgr.ensure_root_layout(auto_create_default=False)
    profile_dir = mgr.profiles_dir / "stable"
    profile_dir.mkdir()
    (profile_dir / PROFILE_METADATA_FILE).write_text(
        json.dumps({"id": "other", "display_name": "Stable Profile"}),
        encoding="utf-8",
    )

    listed = mgr.list_profiles()
    looked_up = mgr.get_profile("stable")

    assert [profile.id for profile in listed] == ["stable"]
    assert looked_up is not None
    assert looked_up.id == "stable"
    assert mgr.get_profile("other") is None


def test_rollback_rejects_manifest_paths_not_bound_to_migration_id(tmp_path: Path):
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    profile = engine.profile_mgr.create_profile("Target", profile_id="target")
    victim = profile.path / "skills" / "user-file.txt"
    victim.write_text("user data\n", encoding="utf-8")
    manifest = MigrationManifest(
        migration_id="mig_123_abcdef12",
        source_path=str(tmp_path / "source"),
        target_profile_id=profile.id,
        created_at="now",
        selected_components=["skills"],
        staging_relative_path="skills",
    )
    engine._save_manifest(profile.path, manifest)

    with pytest.raises(ValueError, match="generated|migration"):
        engine.rollback_migration(profile.path)
    assert victim.read_text(encoding="utf-8") == "user data\n"


def test_rollback_rejects_child_from_another_parent_migration(tmp_path: Path):
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    parent_profile = engine.profile_mgr.create_profile("Parent")
    child_profile = engine.profile_mgr.create_profile("Child")
    child_manifest = MigrationManifest(
        migration_id="mig_123_abcdef23",
        source_path=str(tmp_path / "source-child"),
        target_profile_id=child_profile.id,
        created_at="now",
        selected_components=["config"],
        parent_migration_id="mig_123_abcdef22",
    )
    engine._save_manifest(child_profile.path, child_manifest)
    parent_manifest = MigrationManifest(
        migration_id="mig_123_abcdef21",
        source_path=str(tmp_path / "source-parent"),
        target_profile_id=parent_profile.id,
        created_at="now",
        selected_components=["config"],
        child_migrations=[
            {
                "profile_id": child_profile.id,
                "migration_id": child_manifest.migration_id,
                "parent_migration_id": "mig_123_abcdef21",
            }
        ],
    )
    engine._save_manifest(parent_profile.path, parent_manifest)

    with pytest.raises(ValueError, match="parent"):
        engine.rollback_migration(parent_profile.path, manifest=parent_manifest)


def test_rollback_rejects_unreceipted_in_profile_record(tmp_path: Path):
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    profile = engine.profile_mgr.create_profile("Target", profile_id="target")
    victim = profile.path / "skills" / "user-file.txt"
    victim.write_text("user data\n", encoding="utf-8")
    manifest = MigrationManifest(
        migration_id="mig_123_abcdef12",
        source_path=str(tmp_path / "source"),
        target_profile_id=profile.id,
        created_at="now",
        selected_components=["skills"],
        copied_files=[
            CopiedFileRecord(
                relative_path="skills/user-file.txt",
                size=victim.stat().st_size,
                sha256=hashlib.sha256(victim.read_bytes()).hexdigest(),
                copied_at="now",
                destination_existed=False,
            )
        ],
    )
    engine._save_manifest(profile.path, manifest)

    with pytest.raises(ValueError, match="receipt"):
        engine.rollback_migration(profile.path)
    assert victim.read_text(encoding="utf-8") == "user data\n"


def _create_authenticated_migration(tmp_path: Path):
    source = tmp_path / "hermes_source"
    (source / "skills").mkdir(parents=True)
    (source / "skills" / "safe.md").write_text("safe import\\n", encoding="utf-8")
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    manifest = engine.execute_migration(
        source, target_profile_id="target", components=["skills"]
    )
    return engine, manifest, engine.profile_mgr.get_profile_dir("target")


def test_v2_manifest_tampering_fails_closed(tmp_path: Path):
    engine, manifest, profile_dir = _create_authenticated_migration(tmp_path)
    victim = profile_dir / "skills" / "user-file.txt"
    victim.write_text("safe import\\n", encoding="utf-8")
    manifest_file = profile_dir / MIGRATION_MANIFEST_FILE
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    data["copied_files"][0]["relative_path"] = "skills/user-file.txt"
    manifest_file.write_text(json.dumps(data), encoding="utf-8")

    assert engine.rollback_migration(profile_dir) is False
    assert victim.read_text(encoding="utf-8") == "safe import\\n"


def test_v2_receipt_forgery_fails_closed(tmp_path: Path):
    engine, manifest, profile_dir = _create_authenticated_migration(tmp_path)
    victim = profile_dir / "skills" / "user-file.txt"
    victim.write_text("safe import\\n", encoding="utf-8")
    receipt_root = profile_dir / manifest.receipt_relative_path
    receipt_file = next(receipt_root.glob("*.json"))
    receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    receipt["record"]["relative_path"] = "skills/user-file.txt"
    receipt_file.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(ValueError, match="malformed|unauthenticated|integrity"):
        engine.rollback_migration(profile_dir)
    assert victim.read_text(encoding="utf-8") == "safe import\\n"


def test_rollback_rejects_target_profile_mismatch(tmp_path: Path):
    engine, manifest, profile_dir = _create_authenticated_migration(tmp_path)
    other = engine.profile_mgr.create_profile("Other", profile_id="other")

    with pytest.raises(ValueError, match="target profile"):
        engine.rollback_migration(other.path, manifest=manifest)
    assert (profile_dir / "skills" / "safe.md").exists()


def test_legacy_generated_cleanup_is_non_destructive(tmp_path: Path):
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    profile = engine.profile_mgr.create_profile("Legacy", profile_id="legacy")
    migration_id = "mig_123_abcdef41"
    generated = profile.path / f".stella-migration-staging-{migration_id}"
    generated.mkdir()
    victim = generated / "user-file.txt"
    victim.write_text("user data\\n", encoding="utf-8")
    raw = {
        "migration_id": migration_id,
        "source_path": str(tmp_path / "source"),
        "target_profile_id": "legacy",
        "created_at": "now",
        "selected_components": ["skills"],
        "copied_files": [],
        "status": "completed",
        "staging_relative_path": generated.name,
    }
    (profile.path / MIGRATION_MANIFEST_FILE).write_text(
        json.dumps(raw), encoding="utf-8"
    )

    assert engine.rollback_migration(profile.path) is False
    assert victim.read_text(encoding="utf-8") == "user data\\n"
    assert generated.exists()


def test_named_profile_child_intent_recovers_after_parent_interrupt(
    tmp_path: Path, monkeypatch
):

    source = tmp_path / "hermes_source"
    child_source = source / "profiles" / "child" / "skills"
    child_source.mkdir(parents=True)
    (child_source / "child.md").write_text("child import\\n", encoding="utf-8")
    engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
    real_save = engine._save_manifest

    def interrupt_parent(profile_dir, manifest):
        if manifest.target_profile_id == "parent" and any(
            child.get("status") == "committed" for child in manifest.child_migrations
        ):
            raise KeyboardInterrupt
        return real_save(profile_dir, manifest)

    monkeypatch.setattr(engine, "_save_manifest", interrupt_parent)
    with pytest.raises(KeyboardInterrupt):
        engine.execute_migration(
            source,
            target_profile_id="parent",
            components=["skills"],
            import_named_profiles=True,
        )

    parent_dir = engine.profile_mgr.get_profile_dir("parent")
    child_dir = engine.profile_mgr.get_profile_dir("child")
    assert (child_dir / "skills" / "child.md").exists()
    assert engine.rollback_migration(parent_dir) is True
    assert not (child_dir / "skills" / "child.md").exists()


def test_stella_api_rejects_empty_migration_source_path():
    with pytest.raises(ValidationError):
        stella_api.MigrationPreviewRequest(source_path="")
    with pytest.raises(ValidationError):
        stella_api.MigrationExecuteRequest(source_path="   ")


def test_resolve_active_profile_home_does_not_create_layout(tmp_path: Path):
    from stella.runtime import resolve_active_profile_home

    root = tmp_path / "fresh_stella_home"
    assert resolve_active_profile_home(root=root) is None
    assert not root.exists()


def test_migration_rejects_source_junction(tmp_path: Path):
    if sys.platform != "win32":
        pytest.skip("junction probe requires Windows")
    real_source = tmp_path / "real_source"
    real_source.mkdir()
    (real_source / "config.yaml").write_text("model: safe\n", encoding="utf-8")
    linked_source = tmp_path / "linked_source"
    result = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(linked_source), str(real_source)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip("Windows junction creation is not permitted")
    try:
        engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
        discovered = {
            info.path.resolve() for info in engine.detect_hermes_installations([linked_source])
        }
        assert real_source.resolve() not in discovered
        with pytest.raises(ValueError, match="symlink|junction|reparse"):
            engine.preview_migration(linked_source, components=["config"])
    finally:
        subprocess.run(
            ["cmd.exe", "/c", "rmdir", str(linked_source)],
            capture_output=True,
            text=True,
        )


def test_optional_dangling_junction_is_rejected(tmp_path: Path):
    if sys.platform != "win32":
        pytest.skip("junction probe requires Windows")
    source = tmp_path / "hermes_source"
    source.mkdir()
    linked = source / "skills"
    missing_target = tmp_path / "missing_target"
    proc = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(linked), str(missing_target)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.skip("Windows junction creation is not permitted")
    try:
        engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
        with pytest.raises(ValueError, match="symlink|junction|reparse"):
            engine.preview_migration(source, components=["skills"])
    finally:
        subprocess.run(["cmd.exe", "/c", "rmdir", str(linked)], capture_output=True)


def test_inspection_rejects_descendant_junction(tmp_path: Path):
    if sys.platform != "win32":
        pytest.skip("junction probe requires Windows")
    candidate = tmp_path / "hermes_candidate"
    candidate.mkdir()
    (candidate / "config.yaml").write_text("model: safe\\n", encoding="utf-8")
    external = tmp_path / "external_profiles"
    external.mkdir()
    linked_profiles = candidate / "profiles"
    result = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(linked_profiles), str(external)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip("Windows junction creation is not permitted")
    try:
        engine = HermesMigrationEngine(stella_home=tmp_path / "stella_home")
        assert engine.inspect_hermes_directory(candidate).is_valid is False
    finally:
        subprocess.run(
            ["cmd.exe", "/c", "rmdir", str(linked_profiles)],
            capture_output=True,
            text=True,
        )


def test_discovery_excludes_stella_home_descendants(tmp_path: Path):
    stella_root = tmp_path / "stella_home"
    nested = stella_root / "profiles" / "nested"
    nested.mkdir(parents=True)
    (nested / "config.yaml").write_text("model: safe\\n", encoding="utf-8")
    engine = HermesMigrationEngine(stella_home=stella_root)
    discovered = {info.path.resolve() for info in engine.detect_hermes_installations([nested])}
    assert nested.resolve() not in discovered


def test_early_profile_resolvers_reject_active_junction(
    tmp_path: Path, monkeypatch
):
    if sys.platform != "win32":
        pytest.skip("junction probe requires Windows")
    root = tmp_path / "stella_home"
    profiles = root / "profiles"
    profiles.mkdir(parents=True)
    real_profile = tmp_path / "real_profile"
    real_profile.mkdir()
    linked_profile = profiles / "active"
    result = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(linked_profile), str(real_profile)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip("Windows junction creation is not available")
    (root / "active_profile").write_text("active\\n", encoding="utf-8")
    monkeypatch.setenv("STELLA_HOME", str(root))
    monkeypatch.setenv("HERMES_HOME", str(root))
    try:
        from hermes_cli._startup_fast import _stella_process_home
        from hermes_cli.profiles import resolve_profile_env

        assert Path(_stella_process_home()).resolve() == root.resolve()
        with pytest.raises(ValueError, match="unsafe link|reparse|junction"):
            resolve_profile_env("active")
    finally:
        subprocess.run(
            ["cmd.exe", "/c", "rmdir", str(linked_profile)],
            capture_output=True,
            check=False,
        )


def test_default_stella_home_rejects_junction(monkeypatch, tmp_path: Path):
    if sys.platform != "win32":
        pytest.skip("junction probe requires Windows")
    real_root = tmp_path / "real_stella"
    real_root.mkdir()
    (real_root / "nested").mkdir()
    linked_root = tmp_path / "linked_stella"
    result = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(linked_root), str(real_root)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip("Windows junction creation is not permitted")
    try:
        monkeypatch.setenv("STELLA_HOME", str(linked_root))
        from stella.profiles import StellaProfileManager

        with pytest.raises(ValueError, match="symlink|junction|reparse"):
            StellaProfileManager()
        with pytest.raises(ValueError, match="symlink|junction|reparse"):
            StellaProfileManager(root=linked_root / "nested")
    finally:
        subprocess.run(
            ["cmd.exe", "/c", "rmdir", str(linked_root)],
            capture_output=True,
            text=True,
        )


