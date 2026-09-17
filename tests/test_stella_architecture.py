"""Unit tests for Stella nested profile layout and Hermes migration engine."""

import asyncio
import json
import shutil
from pathlib import Path
import pytest
from fastapi import HTTPException

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


def test_config_migration_excludes_dotenv_and_sanitizes_inline_credentials(
    tmp_path: Path, fake_hermes_installation: Path
):
    (fake_hermes_installation / "config.yaml").write_text(
        "model: safe-model\n"
        "providers:\n"
        "  custom:\n"
        "    base_url: https://example.test/v1\n"
        "    api_key: should-not-be-copied\n"
        "    api_keys: [another-secret]\n"
        "    headers:\n"
        "      Authorization: Bearer raw-header-secret\n"
        "    env:\n"
        "      OPENAI_API_KEY: raw-env-secret\n"
        "    key_env: SAFE_PROVIDER_KEY\n",
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
    assert "should-not-be-copied" not in config_text
    assert "another-secret" not in config_text
    assert "raw-header-secret" not in config_text
    assert "raw-env-secret" not in config_text
    assert "api_key" not in config_text
    assert "key_env: SAFE_PROVIDER_KEY" in config_text
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
        migration_id="mig_test",
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
        migration_id="m1",
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


