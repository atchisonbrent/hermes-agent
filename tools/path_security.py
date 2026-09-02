"""Shared path validation helpers for tool implementations.

Extracts the ``resolve() + relative_to()`` and ``..`` traversal check
patterns previously duplicated across skill_manager_tool, skills_tool,
skills_hub, cronjob_tools, and credential_files.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def validate_within_dir(path: Path, root: Path) -> Optional[str]:
    """Ensure *path* resolves to a location within *root*.

    Returns an error message string if validation fails, or ``None`` if the
    path is safe.  Uses ``Path.resolve()`` to follow symlinks and normalize
    ``..`` components.

    Usage::

        error = validate_within_dir(user_path, allowed_root)
        if error:
            return tool_error(error)
    """
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
        resolved.relative_to(root_resolved)
    except (ValueError, OSError) as exc:
        return f"Path escapes allowed directory: {exc}"
    return None


def validate_within_dir_or_linked_root(
    path: Path, root: Path, canonical_root: Optional[Path]
) -> Optional[str]:
    """Like :func:`validate_within_dir`, but also accept a *leaf* symlink that
    points into ``canonical_root``.

    Skills are commonly installed as a wrapper directory whose individual
    files are symlinks into one canonical checkout (a Git-owned skills
    registry, a vendored submodule, a versioned release cache).  In that layout
    ``SKILL.md`` resolves into the canonical tree, and so do its
    ``references/`` siblings.  A strict ``resolve() + relative_to(root)`` check
    rejects those siblings even though they are exactly as trusted as the
    ``SKILL.md`` that was just loaded.

    Acceptance requires all of:

    * ``path`` itself is a symlink (directories reached *through* a symlinked
      directory are still rejected, so a linked ``references/`` dir cannot
      widen the trust boundary);
    * every ancestor of ``path`` resolves within ``root`` (no traversal via a
      parent link);
    * the symlink target resolves within ``canonical_root``.

    ``canonical_root`` is normally ``SKILL.md.resolve().parent``.  When it is
    ``None`` or equals ``root`` this degrades to :func:`validate_within_dir`.
    """
    error = validate_within_dir(path, root)
    if error is None:
        return None
    if canonical_root is None:
        return error
    try:
        if not path.is_symlink():
            return error
        if validate_within_dir(path.parent, root) is not None:
            return error
        canonical_resolved = canonical_root.resolve()
        if canonical_resolved == root.resolve():
            return error
        path.resolve().relative_to(canonical_resolved)
    except (ValueError, OSError):
        return error
    return None


def has_traversal_component(path_str: str) -> bool:
    """Return True if *path_str* contains ``..`` traversal components.

    Quick check for obvious traversal attempts before doing full resolution.
    """
    parts = Path(path_str).parts
    return ".." in parts
