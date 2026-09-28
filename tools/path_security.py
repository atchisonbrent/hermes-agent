"""Shared path validation helpers for tool implementations (skills, cron, credential files)."""

import re
from pathlib import Path
from typing import Optional


def validate_within_dir(path: Path, root: Path) -> Optional[str]:
    """Error message if *path* does not resolve inside *root* (symlinks and ``..`` followed)."""
    try:
        path.resolve().relative_to(root.resolve())
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
    """Cheap pre-check for a literal ``..`` component before full resolution."""
    return ".." in Path(path_str).parts


# Control chars + Unicode line separators (NEL, LS, PS): newline-bearing paths are legal POSIX
# names, but they corrupt line-delimited protocols (MEDIA: tags) and forge log lines. Same
# class as _LOG_UNSAFE_CHARS in gateway.platforms.base.
_UNSAFE_PATH_CHARS = re.compile(r"[\x00-\x1f\x7f\x85\u2028\u2029]")


def has_unsafe_path_chars(path_str: str) -> bool:
    """True when *path_str* contains control characters or line separators."""
    return bool(_UNSAFE_PATH_CHARS.search(path_str))


# ---- BEGIN PLUGIN-COMPAT (revert-scheduled; see COMPAT_MANIFEST.md) ----
# Names external plugins imported from this module before the Sep 2026 decomposition.
# Internal code MUST NOT use these (scripts/check_compat_pointers.py fails CI if it does).
# The whole block is removed by reverting the commit that added it.
import logging  # noqa: F401,E402


_PLUGIN_COMPAT_LAZY = {
    'logger': ('tools.approval', 'logger'),
}


def __getattr__(name):  # PEP 562 — lazy so no import cycles
    target = _PLUGIN_COMPAT_LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    from hermes_cli.plugin_compat import warn_once
    warn_once(__name__, name, *target)
    return getattr(importlib.import_module(target[0]), target[1])
# ---- END PLUGIN-COMPAT ----
