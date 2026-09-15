"""Guard the Hermes feature surface while Stella is cleaned up."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from unittest import SkipTest


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "docs" / "architecture" / "feature-surface.json"
REQUIRED_SURFACE_PATHS = {
    "core-runtime": frozenset(
        {
            "agent",
            "gateway",
            "hermes_cli",
            "tools",
            "cli.py",
            "run_agent.py",
            "model_tools.py",
            "toolsets.py",
            "hermes_constants.py",
        }
    ),
    "user-surfaces": frozenset(
        {
            "apps/desktop",
            "web",
            "ui-tui",
            "tui_gateway",
            "acp_adapter",
            "apps/shared",
            "apps/bootstrap-installer",
        }
    ),
    "extensibility": frozenset(
        {
            "plugins",
            "skills",
            "optional-skills",
            "optional-mcps",
            "plugin-catalog",
            "native",
            "locales",
        }
    ),
    "distribution": frozenset(
        {
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.windows.yml",
            "nix",
            "setup-hermes.sh",
            "pyproject.toml",
            "setup.py",
            "package.json",
            "package-lock.json",
        }
    ),
    "quality-and-maintenance": frozenset(
        {
            "tests",
            "tests-js",
            "evals",
            ".github",
            "contributors",
            "website",
            "docs",
            "AGENTS.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
        }
    ),
}


def _assert_schema_version_is_supported(manifest: dict[str, object]) -> None:
    schema_version = manifest.get("schema_version")
    assert isinstance(schema_version, int) and not isinstance(schema_version, bool)
    assert schema_version == 1


def _assert_manifest_path_is_safe(
    relative_path: object, *, repo_root: Path = REPO_ROOT
) -> None:
    assert isinstance(relative_path, str) and relative_path, relative_path

    path = Path(relative_path)
    windows_path = PureWindowsPath(relative_path)
    assert not path.is_absolute(), relative_path
    assert not PurePosixPath(relative_path).is_absolute(), relative_path
    assert not windows_path.is_absolute(), relative_path
    assert not windows_path.root, relative_path
    assert not windows_path.drive, relative_path
    assert not windows_path.is_reserved(), relative_path
    raw_components = relative_path.replace("\\", "/").split("/")
    assert all(component not in {".", ".."} for component in raw_components), relative_path

    resolved_root = repo_root.resolve()
    resolved_path = (resolved_root / path).resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise AssertionError(
            f"feature-surface path escapes repository: {relative_path}"
        ) from exc

    assert resolved_path.exists(), relative_path


def test_feature_surface_manifest_exists_and_declares_required_paths() -> None:
    assert MANIFEST_PATH.is_file(), "feature-surface.json must guard cleanup decisions"

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    surfaces = manifest["surfaces"]

    _assert_schema_version_is_supported(manifest)
    assert manifest["product"] == "Stella"
    assert isinstance(surfaces, list)
    surface_ids = [surface["id"] for surface in surfaces]
    assert len(surface_ids) == len(REQUIRED_SURFACE_PATHS)
    assert len(surface_ids) == len(set(surface_ids))
    assert set(surface_ids) == set(REQUIRED_SURFACE_PATHS)

    for surface in surfaces:
        surface_id = surface["id"]
        paths = surface["paths"]
        assert isinstance(paths, list) and paths
        assert all(isinstance(path, str) and path for path in paths)
        assert len(paths) == len(set(paths)), surface_id
        assert set(paths) == REQUIRED_SURFACE_PATHS[surface_id], surface_id

        for relative_path in paths:
            _assert_manifest_path_is_safe(relative_path)


def test_schema_version_validator_rejects_non_integer_versions() -> None:
    for schema_version in (True, 1.0, "1", None):
        try:
            _assert_schema_version_is_supported({"schema_version": schema_version})
        except AssertionError:
            continue
        raise AssertionError(f"invalid schema version accepted: {schema_version!r}")


def test_manifest_path_validator_rejects_unsafe_paths() -> None:
    unsafe_paths = (
        ".",
        "apps/./desktop",
        "..",
        "../outside",
        "apps/../desktop",
        "/tmp/outside",
        "C:/Windows",
        r"\10_Projects\Project_Stella\stellarium\apps\desktop",
        r"D:apps\desktop",
        "NUL",
        "apps/NUL",
        "CON.txt",
        r"apps\.\desktop",
        r"apps\..\desktop",
    )

    for relative_path in unsafe_paths:
        try:
            _assert_manifest_path_is_safe(relative_path)
        except AssertionError:
            continue
        raise AssertionError(f"unsafe feature-surface path accepted: {relative_path}")


def test_manifest_path_validator_rejects_symlink_escape(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo_root.mkdir()
    outside.mkdir()
    link = repo_root / "linked"

    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        if os.name == "nt" and (
            isinstance(exc, PermissionError)
            or getattr(exc, "winerror", None) == 1314
            or exc.errno == errno.EPERM
        ):
            raise SkipTest("Windows symlink creation requires elevated privilege") from exc
        raise

    try:
        _assert_manifest_path_is_safe("linked", repo_root=repo_root)
    except AssertionError:
        return
    raise AssertionError("symlink escape accepted")
