"""Filesystem safety primitives shared by Stella profile and migration code."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Iterator


# FILE_ATTRIBUTE_REPARSE_POINT is intentionally kept local so this module
# remains importable on non-Windows platforms without pywin32.
_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
_INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF


def is_link_or_reparse(path: Path) -> bool:
    """Return whether *path* is a symlink, junction, or reparse point.

    ``Path.is_symlink()`` is not sufficient on Windows: directory junctions
    are reparse points but are not reported as symlinks.  ``lstat`` exposes
    the Windows attribute on supported Python versions; the realpath fallback
    covers older runtimes and platforms where that attribute is unavailable.
    Any error other than a missing path is treated as unsafe (fail closed).
    """
    candidate = Path(path)
    try:
        if candidate.is_symlink():
            return True
        info = os.lstat(os.fspath(candidate))
    except FileNotFoundError:
        return False
    except OSError:
        return True

    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = int(getattr(info, "st_file_attributes", 0) or 0)
    if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        return True

    # The attribute is not exposed by every Python/platform combination.
    # Keep this fallback after lstat so ordinary paths do not get resolved
    # before their link metadata has been inspected.
    try:
        absolute = os.path.normcase(os.path.abspath(os.fspath(candidate)))
        resolved = os.path.normcase(os.path.realpath(os.fspath(candidate)))
    except OSError:
        return True
    return absolute != resolved


def _existing_path_components(path: Path) -> Iterator[Path]:
    """Yield existing lexical components of an absolute path in order."""
    absolute = Path(os.path.abspath(os.fspath(Path(path).expanduser())))
    current = Path(absolute.anchor) if absolute.anchor else Path()
    for part in absolute.parts:
        if part == absolute.anchor:
            continue
        current = current / part
        yield current
        if not current.exists() and not current.is_symlink():
            # No descendant can exist below a missing component.
            break


def assert_no_link_or_reparse(path: Path, label: str) -> None:
    """Reject a path and every existing ancestor containing a link."""
    for component in _existing_path_components(Path(path)):
        if is_link_or_reparse(component):
            raise ValueError(f"{label} may not contain a symlink, junction, or reparse point: {path}")


__all__ = ["assert_no_link_or_reparse", "is_link_or_reparse"]
