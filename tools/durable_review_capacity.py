"""Local capacity accounting for the no-tools durable-write reviewer.

No network, credentials, inference, or persistent caches are used in preflight.
"""
import importlib.util
import struct
from pathlib import Path

from agent.model_metadata import (
    _CODEX_OAUTH_CONTEXT_FALLBACK,
)

# I/O/memory bound, not a model context window. The model-token budget is separate.
MAX_PACKET_BYTES = 16 * 1024 * 1024


def model_capacity(model):
    """Use the existing Codex-route catalog, not direct-API or interactive limits."""
    window = _CODEX_OAUTH_CONTEXT_FALLBACK.get(model)
    source = "exact Codex-route fallback catalog"
    if type(window) is not int or window <= 8192:
        return None
    # Reserve at least 8192 tokens and 20% of the window for output, reasoning,
    # wire framing and estimator error. This is not a provider output-token cap.
    return {"context_tokens": window, "max_input_tokens": window - max(8192, window // 5),
            "context_source": source}


def packet_tokens(policy, encoded_context):
    # Deliberately more conservative than the general ASCII chars/4 estimate.
    # This remains an estimate, not a tokenizer or proof of provider fit; the
    # reserved context margin and fail-closed API boundary remain necessary.
    # Do not retain entire packets in the global message-estimator cache.
    size = len(policy.encode("utf-8")) + len(encoded_context.encode("utf-8"))
    return (size + 2) // 3 + 32


def verified_bytecode_cache(path: Path, root: Path):
    """Ignore only timestamp caches matching a present, non-linked source file.

Malformed, stale, hash-based or unrecognized binary files remain fail-closed.
The bytecode is never unmarshalled or executed. Symlinks are checked by the owner
walker before calling this helper.
"""
    if path.parent.name != "__pycache__" or path.suffix != ".pyc":
        return False
    try:
        source = Path(importlib.util.source_from_cache(str(path)))
        if not source.is_relative_to(root) or source.is_symlink() or not source.is_file():
            return False
        with path.open("rb") as stream:
            header = stream.read(16)
        if len(header) != 16 or header[:4] != importlib.util.MAGIC_NUMBER:
            return False
        flags, timestamp, size = struct.unpack("<III", header[4:])
        stat = source.stat()
        return flags == 0 and timestamp == int(stat.st_mtime) & 0xFFFFFFFF and size == stat.st_size
    except (OSError, ValueError, NotImplementedError):
        return False
