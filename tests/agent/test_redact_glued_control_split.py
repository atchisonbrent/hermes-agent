"""A key glued to an identifier by ``-``/``_`` AND split by a control character is still masked."""
import pytest

from agent import redact

# Synthetic fixed-format fixtures: opaque bodies that mix cases and digits.
_SK = "sk-" + "aB3xY7zQ9wE1rT5uI0oP" + "mN4kL8jH2gF6"
_GHP = "ghp_" + "a1B2" * 9


def _mask(text):
    return redact._mask_control_split_tokens(text, lambda _token: "<masked>")


@pytest.mark.parametrize("glue,token,control", [
    ("backup-", _SK, "\x1b"),
    ("backup_", _SK, "\u200b"),
    ("x-", _GHP, "\x1b"),
    ("x_", _GHP, "\u200b"),
])
def test_glued_control_split_key_is_masked(glue, token, control):
    assert redact._PREFIX_RE.fullmatch(token) is not None  # the fixture is a real key shape
    split = token[:7] + control + token[7:]
    out = _mask(f"see {glue}{split} here")
    assert out == f"see {glue}<masked> here"
    assert token[7:] not in out


def test_unglued_control_split_key_is_still_masked():
    split = _SK[:7] + "\x1b" + _SK[7:]
    assert _mask(f"see {split} here") == "see <masked> here"


def test_glued_non_secret_split_by_a_control_character_stays_whole():
    text = "pip install backup-sk-lea\x1brn-extensions"
    assert _mask(text) == text


def test_public_redaction_masks_the_glued_split_key(monkeypatch):
    monkeypatch.setattr(redact, "_REDACT_ENABLED", True, raising=False)
    split = _SK[:7] + "\x1b" + _SK[7:]
    out = redact.redact_sensitive_text(f"backup-{split}")
    assert _SK[7:] not in out and _SK[3:7] + "\x1b" + _SK[7:11] not in out
