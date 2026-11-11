"""Exact-value redaction of the secrets this process itself loaded.

Pattern redaction (``agent.redact``) cannot recognise an opaque value with no vendor prefix once it is
printed outside an assignment: a secrets-manager CLI's JSON listing, an application's own config dump, a
debug print. The process does know those values: a secret source supplied them, or they sit in a
variable the child-environment policy strips as a credential. They are registered here with the name of
their key, and every occurrence (raw, JSON-escaped, percent-encoded or base64-encoded) is replaced with
``«redacted-secret:NAME»``, both in ``redact_sensitive_text`` and on every tool result as it becomes the
message the model sees (``scrub_known_secrets``). Names are not secret; values are memory-only, never
logged or persisted.

Registration is keyed by profile home, but the lookup is the union of every home's values. Output does
not always belong to the profile that is bound when it is scrubbed: a cross-profile ``session_search``
returns another profile's stored rows, and background-process heartbeats run on a timer thread bound to
no profile. Masking a sibling profile's value in this profile's output is the safe failure, and the
per-home keys keep a later narrowing possible.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

# Shorter values are not registered: an 8-character floor keeps exact matching from masking ordinary
# words and numbers. Their names are reported once (``log_uncovered_names``) so the gap is visible.
MIN_VALUE_LENGTH = 8
# Encoded forms are derived, and a short one (the base64 of a value's first few bytes) can occur in
# unrelated output. They are registered only from this length; the raw value is always covered.
MIN_DERIVED_FORM_LENGTH = 16

# A secrets manager also holds addresses, identities and settings. Masking a hostname or a model name
# everywhere would wreck ordinary output, so keys ending in one of these words are never registered.
# Matched as a whole ``_``-separated word, so ``SUPPORT`` or ``ANDROID`` do not count.
_NON_SECRET_SUFFIXES = (
    "URL", "URI", "BASE", "PATH", "DIR", "HOST", "HOSTNAME", "PORT", "ENDPOINT", "DOMAIN", "USERNAME",
    "USER", "EMAIL", "ID", "NAME", "REGION", "MODEL",
)
_CONFIG_EXEMPT_KEY = "known_secret_exempt_keys"  # security.<this>: extra key names never registered
_IMAGE_PART_TYPES = frozenset({"image", "image_url", "input_image"})
_WALK_MAX_DEPTH = 64


class _Registry:
    """One profile home's registered values."""

    def __init__(self) -> None:
        self.forms: dict[str, dict[str, str]] = {}  # value -> {form: key name}; first registration wins
        self.short: set[str] = set()  # key names whose value was too short to register
        self.reported: set[str] = set()  # short names already logged


_REGISTRIES: dict[str, _Registry] = {}
_LOCK = threading.Lock()
# One compiled pattern for the union of every home's forms, swapped in whole so readers need no lock.
_MATCHER: Optional[tuple[re.Pattern[str], dict[str, str]]] = None


def _home_key(home=None) -> str:
    from hermes_constants import hermes_home_key
    return hermes_home_key(home)


def _normalize_name(name: str) -> str:
    return name.strip().upper().replace("-", "_")


def is_exempt_name(name: str, extra: frozenset = frozenset()) -> bool:
    """True for a key whose value is an address/identity/setting, or one the config exempts."""
    norm = _normalize_name(name)
    return norm in extra or any(norm == s or norm.endswith("_" + s) for s in _NON_SECRET_SUFFIXES)


def _read_config(home) -> dict:
    try:
        from hermes_cli.config_backend import read_config_doc_readonly
        doc = read_config_doc_readonly(Path(home) / "config.yaml")
    except Exception:  # health: allow BLE001 -- no readable config: no exemptions, no key_env names
        return {}
    return doc if isinstance(doc, dict) else {}


def _config_exempt_names(home) -> frozenset:
    """``security.known_secret_exempt_keys``, normalized. Unreadable config exempts nothing: masking too
    much is the safe failure."""
    security = _read_config(home).get("security")
    raw = security.get(_CONFIG_EXEMPT_KEY) if isinstance(security, dict) else None
    return frozenset(_normalize_name(n) for n in raw if isinstance(n, str)) if isinstance(raw, list) else frozenset()


def configured_key_env_names(home) -> set[str]:
    """Variable names *home*'s config.yaml reads provider API keys from (``key_env`` / ``api_key_env``
    of the main model, ``providers``, ``custom_providers`` and ``fallback_providers`` entries)."""
    config = _read_config(home)
    providers = config.get("providers")
    entries = [config.get("model"), *(providers.values() if isinstance(providers, dict) else ())]
    for key in ("custom_providers", "fallback_providers"):
        if isinstance(config.get(key), list):
            entries.extend(config[key])
    names = set()
    for entry in entries:
        if isinstance(entry, dict):
            names.update(str(entry.get(k)).strip() for k in ("key_env", "api_key_env") if entry.get(k))
    return names


def _marker(name: str) -> str:
    # Key names from a store need not be variable names; keep the marker inert inside JSON and shell text.
    return "«redacted-secret:" + re.sub(r"[^A-Za-z0-9_.:-]", "_", name) + "»"


def _forms(value: str) -> set[str]:
    """The value as it may appear in output: raw, JSON-string-escaped, percent-encoded (either hex
    case), and standard / URL-safe base64 of its UTF-8 bytes, padded or not. The base64 of the whole
    3-byte groups is added too: it is the same whatever follows the value (``echo "$TOKEN" | base64``
    encodes a newline). Raises ``UnicodeEncodeError`` for a value with lone surrogates."""
    raw = value.encode("utf-8")
    quoted = quote(value, safe="")
    derived = {json.dumps(value)[1:-1], json.dumps(value, ensure_ascii=False)[1:-1], quoted,
               re.sub(r"%[0-9A-F]{2}", lambda m: m.group(0).lower(), quoted)}
    for encode in (base64.b64encode, base64.urlsafe_b64encode):
        encoded = encode(raw).decode("ascii")
        derived.update((encoded, encoded.rstrip("="), encoded[: len(raw) // 3 * 4]))
    return {value} | {f for f in derived if len(f) >= MIN_DERIVED_FORM_LENGTH}


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


def _build_matcher() -> Optional[tuple[re.Pattern[str], dict[str, str]]]:
    markers: dict[str, str] = {}
    for registry in _REGISTRIES.values():
        for forms in registry.forms.values():
            for form, name in forms.items():
                markers.setdefault(form, _marker(name))
    if not markers:
        return None
    trie: dict = {}
    for form in markers:
        node = trie
        for char in form:
            node = node.setdefault(char, {})
        node[""] = {}
    return re.compile(_trie_regex(trie)), markers


def register_known_secrets(home, values: Mapping[str, str]) -> None:
    """Register *values* (key name -> value) for *home* (None: the active profile home). Exempt keys
    are skipped; values under ``MIN_VALUE_LENGTH`` are recorded by name only. Never raises: it runs on
    startup paths, and a value it cannot handle is skipped with its key name logged."""
    try:
        _register(home, dict(values))
    except Exception as exc:  # health: allow BLE001 -- registration must never abort startup
        logger.warning("Exact-value secret redaction: registration failed (%s)", type(exc).__name__)


def _register(home, values: dict) -> None:
    if not values:
        return
    if home is None:
        from hermes_constants import get_hermes_home
        home = get_hermes_home()
    exempt = _config_exempt_names(home)
    candidates: dict[str, dict[str, str]] = {}
    short: set[str] = set()
    unencodable: list[str] = []
    for name, value in values.items():
        if not (isinstance(name, str) and isinstance(value, str) and value.strip()) or is_exempt_name(name, exempt):
            continue
        if len(value) < MIN_VALUE_LENGTH:
            short.add(name)
            continue
        try:
            candidates.setdefault(value, dict.fromkeys(_forms(value), name))
        except UnicodeEncodeError:  # undecodable bytes in a POSIX environment value
            unencodable.append(name)
    if unencodable:
        logger.warning("Exact-value secret redaction skips values that are not valid text: %s",
                       ", ".join(sorted(unencodable)))
    global _MATCHER
    with _LOCK:
        registry = _REGISTRIES.setdefault(_home_key(home), _Registry())
        registry.short.update(short)
        added = {v: f for v, f in candidates.items() if v not in registry.forms}
        if not added:
            return
        registry.forms.update(added)
        registry.short.difference_update(n for forms in added.values() for n in forms.values())
        try:
            _MATCHER = _build_matcher()
        except Exception:
            for value in added:  # keep registry and matcher consistent: the batch is not registered
                registry.forms.pop(value, None)
            raise


def register_environment_credentials(home, environ: Mapping[str, str]) -> None:
    """Register the credentials in *environ*: the variables the child-environment policy strips from
    model-run commands as credentials (what is a credential for stripping is one for masking), plus
    the provider keys *home*'s config names through ``key_env``. Never by name keyword alone: a
    ``MAX_TOKENS`` count or an ``SSH_AUTH_SOCK`` path is not a credential."""
    try:
        environ = dict(environ)
        from tools.environments.local_env_policy import credential_env_values
        values = credential_env_values(environ)
        values.update((n, environ[n]) for n in configured_key_env_names(home) if n in environ)
    except Exception as exc:  # health: allow BLE001 -- registration must never abort startup
        logger.warning("Exact-value secret redaction: environment credentials not read (%s)", type(exc).__name__)
        return
    register_known_secrets(home, values)


def redact_known_secret_values(text: str) -> str:
    """Replace every registered value (of any profile home), in any registered form, by its marker."""
    matcher = _MATCHER
    if matcher is None or not isinstance(text, str) or not text:
        return text
    pattern, markers = matcher
    return pattern.sub(lambda m: markers[m.group(0)], text)


def map_text_leaves(value: Any, fn: Callable[[str], str], _depth: int = 0) -> Any:
    """*value* with *fn* applied to every string inside lists and dicts. Image parts of a multimodal
    result and non-string leaves are returned as they are; unchanged containers are not copied."""
    if isinstance(value, str):
        return fn(value)
    if _depth >= _WALK_MAX_DEPTH:
        return value
    if isinstance(value, list):
        out = [map_text_leaves(v, fn, _depth + 1) for v in value]
        return value if all(a is b for a, b in zip(out, value)) else out
    if isinstance(value, dict) and value.get("type") not in _IMAGE_PART_TYPES:
        out = {k: map_text_leaves(v, fn, _depth + 1) for k, v in value.items()}
        return value if all(out[k] is v for k, v in value.items()) else out
    return value


def scrub_known_secrets(value: Any) -> Any:
    """Exact-value scrub of a tool result (string or structured content)."""
    return value if _MATCHER is None else map_text_leaves(value, redact_known_secret_values)


def scrub_tool_row(row: dict) -> dict:
    """Scrub a ``role == "tool"`` row's content in place: the rows an agent provider projects never pass
    ``make_tool_result_message``. Ids and every other field stay as they are."""
    if row.get("role") == "tool" and "content" in row:
        row["content"] = scrub_known_secrets(row["content"])
    return row


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
    global _MATCHER
    with _LOCK:
        if home is None:
            _REGISTRIES.clear()
        else:
            _REGISTRIES.pop(_home_key(home), None)
        _MATCHER = _build_matcher()
