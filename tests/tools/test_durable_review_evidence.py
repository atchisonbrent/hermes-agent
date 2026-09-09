"""Evidence regression cases from independent durable-write review."""
from types import SimpleNamespace

import pytest

from tools import write_approval as wa


def test_large_unrelated_result_preserves_complete_human_preference():
    messages = [
        {"role": "user", "content": "Remember that I prefer concise replies."},
        {"role": "assistant", "tool_calls": [{"id": "large", "function": {"name": "read_file", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "large", "content": "x" * 20000},
    ]
    with wa.review_evidence(messages):
        source = wa._evidence.get()
        assert len(source) == 1
        assert source[0]["text"] == messages[0]["content"]
        assert source[0]["omitted_tool_results"] == 1


@pytest.mark.parametrize("call", [
    {"call_id": "call_1", "response_item_id": "item_1", "function": {"name": "read_file", "arguments": "{}"}},
    SimpleNamespace(call_id="call_1", response_item_id="item_1", function=SimpleNamespace(name="read_file", arguments="{}")),
])
def test_alias_tool_result_retains_attribution(call):
    messages = [{"role": "user", "content": "Check the existing owner."},
                {"role": "assistant", "tool_calls": [call]},
                {"role": "tool", "tool_call_id": "call_1|item_1", "content": "Original owner contents."}]
    with wa.review_evidence(messages):
        source = wa._evidence.get()
        assert source[-1]["text"] == "Original owner contents."
        assert source[-1]["tool_name"] == "read_file"


@pytest.mark.parametrize("attributes", [{"platform": "cron"}, {"_delegate_depth": 1}, {"is_subagent": True}])
def test_machine_prompt_is_not_human_evidence(attributes):
    @wa.capture_review_evidence
    def invoke(agent, messages):
        return wa._evidence.get()
    assert invoke(SimpleNamespace(**attributes), [{"role": "user", "content": "The user always wants resets."}]) == []


def test_ambiguous_tool_ids_do_not_misattribute_evidence():
    messages = [{"role": "user", "content": "Check."}, {"role": "assistant", "tool_calls": [
        {"id": "same", "function": {"name": "read_file", "arguments": "{}"}},
        {"id": "same", "function": {"name": "memory", "arguments": "{}"}},
    ]}, {"role": "tool", "tool_call_id": "same", "content": "Not independent proof."}]
    with wa.review_evidence(messages):
        assert all(s["role"] != "tool" for s in wa._evidence.get())


def test_pending_id_collision_does_not_replace_existing(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ids = iter(["aaaaaaaa", "aaaaaaaa", "bbbbbbbb"])
    monkeypatch.setattr(wa.uuid, "uuid4", lambda: SimpleNamespace(hex=next(ids)))
    first = wa.stage_write("memory", {"content": "first"}, summary="first", origin="foreground")
    second = wa.stage_write("memory", {"content": "second"}, summary="second", origin="foreground")
    assert first["id"] != second["id"]
    assert wa.get_pending("memory", first["id"])["payload"]["content"] == "first"


def test_busy_scheduler_reports_not_started(monkeypatch):
    monkeypatch.setattr(wa, "_review_slots", SimpleNamespace(acquire=lambda **kwargs: False))
    assert wa._start_review(lambda: pytest.fail("Must not start while busy")) is False
