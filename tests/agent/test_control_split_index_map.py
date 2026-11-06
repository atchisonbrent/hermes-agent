"""Regression coverage for matching control-split token prefix misses cheaply."""
from unittest.mock import patch

from agent import redact


def _valid_control_split_token(body="a1"):
    # Synthetic, fixed-format fixture; choosing it never calls the function tested.
    token = "ghp_" + body * 18
    assert redact._PREFIX_RE.fullmatch(token) is not None
    return token[:6] + "\x1b" + token[6:]


def test_missing_prefix_match_does_not_scan_each_character():
    text = "descriptive prefix sk-short " + "\x1b"
    stripped = redact._CONTROL_CHARS_RE.sub("", text)
    assert stripped != text
    assert redact._PREFIX_RE.search(stripped) is None
    with patch.object(redact, "_CONTROL_CHARS_RE", wraps=redact._CONTROL_CHARS_RE) as control_pattern:
        assert redact._mask_control_split_tokens(text, lambda _: "<masked>") == text
        control_pattern.match.assert_not_called()


def test_multiple_control_split_tokens_preserve_callback_order_and_prose():
    first = _valid_control_split_token("a1")
    second = _valid_control_split_token("b2")
    calls = []

    def mask(token):
        calls.append(token)
        return f"<masked-{len(calls)}>"

    text = f"before {first} between {second} after"
    assert redact._mask_control_split_tokens(text, mask) == "before <masked-1> between <masked-2> after"
    assert calls == [first.replace("\x1b", ""), second.replace("\x1b", "")]


def test_rejected_first_match_does_not_drop_a_later_control_split_token():
    first = _valid_control_split_token("a1")
    second = _valid_control_split_token("b2")
    calls = []

    def mask(token):
        calls.append(token)
        return "<masked>"

    text = f"before {first}=value between {second} after"
    assert redact._mask_control_split_tokens(text, mask) == f"before {first}=value between <masked> after"
    assert calls == [second.replace("\x1b", "")]

    calls.clear()
    only_rejected = f"before {first}=value after"
    assert redact._mask_control_split_tokens(only_rejected, mask) == only_rejected
    assert calls == []
