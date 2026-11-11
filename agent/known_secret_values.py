"""Exact-value redaction of the secrets this process itself loaded.

Pattern redaction (``agent.redact``) cannot recognise an opaque value with no vendor prefix once it is
printed outside an assignment: a secrets-manager CLI's JSON listing, an application's own config dump, a
debug print. The process does know those values, because a secret source supplied them or a ``.env``
loaded them under a credential name. They are registered here per profile home, with the name of their
key, and ``redact_sensitive_text`` replaces every occurrence (raw, JSON-escaped, percent-encoded or
base64-encoded) with ``«redacted-secret:NAME»``. Names are not secret; values are memory-only, never
logged or persisted.

Keyed by profile home like the vault registry, so a multiplex gateway never scrubs profile B's output
with profile A's values (which would also confirm to B that those bytes exist).
"""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

# Shorter values are not registered: an 8-character floor keeps exact matching from masking ordinary
# words and numbers. Their names are reported once (``log_uncovered_names``) so the gap is visible.
MIN_VALUE_LENGTH = 8

# A secrets manager also holds addresses, identities and settings. Masking a hostname or a model name
# everywhere would wreck ordinary output, so keys ending in one of these words are never registered.
# Matched as a whole ``_``-separated word, so ``SUPPORT`` or ``ANDROID`` do not count.
_NON_SECRET_SUFFIXES = (
    "URL", "URI", "PATH", "DIR", "HOST", "HOSTNAME", "PORT", "ENDPOINT", "USERNAME", "USER", "EMAIL",
    "ID", "REGION", "MODEL",
)
_CONFIG_EXEMPT_KEY = "known_secret_exempt_keys"  # security.<this>: extra key names never registered


class _Registry:
    """One profile home's registered values. ``matcher`` is rebuilt when a batch adds a value and
    swapped in whole, so readers never need the lock."""

    def __init__(self) -> None:
        self.names: dict[str, str] = {}  # value -> key name (first registration wins)
        self.short: set[str] = set()  # key names whose value was too short to register
        self.reported: set[str] = set()  # short names already logged
        self.matcher: Optional[tuple[re.Pattern[str], dict[str, str]]] = None


_REGISTRIES: dict[str, _Registry] = {}
_LOCK = threading.Lock()


def _home_key(home=None) -> str:
    from hermes_constants import hermes_home_key
    return hermes_home_key(home)


def _normalize_name(name: str) -> str:
    return name.strip().upper().replace("-", "_")


def is_exempt_name(name: str, extra: frozenset = frozenset()) -> bool:
    """True for a key whose value is an address/identity/setting, or one the config exempts."""
    norm = _normalize_name(name)
    return norm in extra or any(norm == s or norm.endswith("_" + s) for s in _NON_SECRET_SUFFIXES)


def _config_exempt_names(home) -> frozenset:
    """``security.known_secret_exempt_keys`` of *home*'s config.yaml, normalized. Unreadable config
    exempts nothing: masking too much is the safe failure."""
    try:
        from hermes_cli.config_backend import read_config_doc_readonly
        security = (read_config_doc_readonly(Path(home) / "config.yaml") or {}).get("security") or {}
        raw = security.get(_CONFIG_EXEMPT_KEY) if isinstance(security, dict) else None
    except Exception:  # health: allow BLE001 -- any read failure means "no exemptions"
        return frozenset()
    return frozenset(_normalize_name(n) for n in raw if isinstance(n, str)) if isinstance(raw, list) else frozenset()


def _looks_secret_name(name: str) -> bool:
    # The redactor's own notion of a credential-bearing key (``API_KEY``, ``DB_PW``, not ``KEYBOARD``).
    from agent.redact import _key_has_secret_keyword
    return _key_has_secret_keyword(name)


def _forms(value: str) -> set[str]:
    """The value as it may appear in output: raw, JSON-string-escaped, percent-encoded, and standard /
    URL-safe base64 of its UTF-8 bytes. The base64 prefix covering only whole 3-byte groups is added
    too: it is the same whatever follows the value (``echo "$TOKEN" | base64`` encodes a newline)."""
    raw = value.encode("utf-8")
    forms = {value, json.dumps(value)[1:-1], json.dumps(value, ensure_ascii=False)[1:-1], quote(value, safe="")}
    for encode in (base64.b64encode, base64.urlsafe_b64encode):
        encoded = encode(raw).decode("ascii")
        forms.update((encoded, encoded[: len(raw) // 3 * 4]))
    return {f for f in forms if len(f) >= MIN_VALUE_LENGTH}


def _trie_regex(node: dict) -> str:
    """Regex for a character trie. Sibling alternatives start with different characters, so at most
    one can match, and a word end is a greedy optional group: the pattern takes the LONGEST registered
    form at each position (a value that is a substring of another never shadows it), and the regex
    engine rejects most positions on the first character instead of trying every value in turn."""
    alternatives = []
    for char, child in node.items():
        if not char:
            continue
        run = [char]
        while len(child) == 1 and "" not in child:  # collapse single-child chains into one literal
            (char, child), = child.items()
            run.append(char)
        alternatives.append(re.escape("".join(run)) + _trie_regex(child))
    if not alternatives:
        return ""
    body = alternatives[0] if len(alternatives) == 1 else "(?:" + "|".join(alternatives) + ")"
    return f"(?:{body})?" if "" in node else body


def _build_matcher(names: dict[str, str]) -> tuple[re.Pattern[str], dict[str, str]]:
    by_form: dict[str, str] = {}
    for value, name in names.items():
        for form in _forms(value):
            by_form.setdefault(form, name)
    trie: dict = {}
    for form in by_form:
        node = trie
        for char in form:
            node = node.setdefault(char, {})
        node[""] = {}
    return re.compile(_trie_regex(trie)), by_form


def register_known_secrets(home, values: Mapping[str, str], *, require_secret_name: bool = False) -> None:
    """Register *values* (key name -> value) for *home*. ``require_secret_name`` keeps only keys the
    redactor would treat as credentials: a ``.env`` or process environment also holds plain settings.
    Exempt keys are skipped; values under ``MIN_VALUE_LENGTH`` are recorded by name only. *home*
    None means the active profile home."""
    if not values:
        return
    if home is None:
        from hermes_constants import get_hermes_home
        home = get_hermes_home()
    exempt = _config_exempt_names(home)
    candidates = [(name, value) for name, value in values.items()
                  if isinstance(name, str) and isinstance(value, str) and value.strip()
                  and not is_exempt_name(name, exempt) and (not require_secret_name or _looks_secret_name(name))]
    if not candidates:
        return
    with _LOCK:
        registry = _REGISTRIES.setdefault(_home_key(home), _Registry())
        added = False
        for name, value in candidates:
            if len(value) < MIN_VALUE_LENGTH:
                registry.short.add(name)
            elif value not in registry.names:
                registry.names[value] = name
                added = True
        if added:
            registry.matcher = _build_matcher(registry.names)


def redact_known_secret_values(text: str) -> str:
    """Replace every registered value of the current profile, in any registered form, by its marker."""
    if not isinstance(text, str) or not text or not _REGISTRIES:
        return text
    registry = _REGISTRIES.get(_home_key())
    matcher = registry.matcher if registry is not None else None
    if matcher is None:
        return text
    pattern, by_form = matcher
    return pattern.sub(lambda m: f"«redacted-secret:{by_form[m.group(0)]}»", text)


def uncovered_names(home=None) -> list[str]:
    """Key names whose value is too short to be matched exactly (names only)."""
    registry = _REGISTRIES.get(_home_key(home))
    return sorted(registry.short) if registry is not None else []


def log_uncovered_names(home) -> None:
    """One log line naming the keys exact-value redaction cannot cover; only names not yet reported."""
    with _LOCK:
        registry = _REGISTRIES.get(_home_key(home))
        fresh = sorted(registry.short - registry.reported) if registry is not None else []
        if registry is not None:
            registry.reported.update(fresh)
    if fresh:  # logged outside the lock: the log formatter itself calls redact_known_secret_values
        logger.info("Exact-value secret redaction skips values shorter than %d characters: %s",
                    MIN_VALUE_LENGTH, ", ".join(fresh))


def clear_known_secrets(home=None) -> None:
    """Forget *home*'s registered values (every home when None): tests, profile teardown."""
    with _LOCK:
        if home is None:
            _REGISTRIES.clear()
        else:
            _REGISTRIES.pop(_home_key(home), None)
