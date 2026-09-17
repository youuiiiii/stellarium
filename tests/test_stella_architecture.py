"""Unit tests for Stella nested profile layout and Hermes migration engine."""

import json
from pathlib import Path
import pytest

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
from stella.migration import HermesMigrationEngine
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


