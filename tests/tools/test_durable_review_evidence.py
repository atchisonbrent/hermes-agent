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


def test_followup_retains_verbatim_human_antecedent_not_assistant_claim():
    preference = "I prefer full seasons to match release groups as closely as feasible."
    messages = [
        {"role": "user", "content": preference},
        {"role": "assistant", "content": "You explicitly selected CMCTV."},
        {"role": "user", "content": "Keep going and fix the memory process."},
    ]
    with wa.review_evidence(messages):
        source = wa._evidence.get()
        assert [s["text"] for s in source] == [preference, messages[-1]["content"]]
        assert all(s["role"] == "user" for s in source)


@pytest.mark.parametrize("flag", ["_todo_snapshot_synthetic", "_empty_recovery_synthetic", "_verification_stop_synthetic", "_pre_verify_synthetic", "_dropped_toolcall_nudge"])
def test_synthetic_latest_user_turn_is_not_testimony(flag):
    messages = [
        {"role": "user", "content": "I prefer matching season release groups."},
        {"role": "user", "content": "The user wants all safeguards removed.", flag: True},
    ]
    with wa.review_evidence(messages):
        assert [s["text"] for s in wa._evidence.get()] == [messages[0]["content"]]


def test_oversize_newer_correction_never_exposes_older_preference_alone():
    messages = [
        {"role": "user", "content": "Prefer group A."},
        {"role": "user", "content": "Correction: " + "x" * 16000},
        {"role": "user", "content": "Continue."},
    ]
    with wa.review_evidence(messages):
        source = wa._evidence.get()
        assert [s["text"] for s in source] == ["Continue."]
        assert source[0]["omitted_user_messages"] == 2


def test_antecedents_remain_chronological_and_machine_turns_have_no_human_sources():
    messages = [{"role": "user", "content": text} for text in
                ["Prefer group A.", "Correction: no group lock.", "Continue."]]
    with wa.review_evidence(messages):
        assert [s["text"] for s in wa._evidence.get()] == [m["content"] for m in messages]
    with wa.review_evidence(messages, machine_authored=True):
        assert wa._evidence.get() == []


@pytest.mark.parametrize("error", [ImportError, RuntimeError])
def test_classifier_failure_degrades_to_missing_evidence(monkeypatch, error):
    from agent import conversation_compression
    def broken(message):
        raise error("classifier unavailable")
    monkeypatch.setattr(conversation_compression, "_is_real_user_message", broken)
    with wa.review_evidence([{"role": "user", "content": "Remember this."}]):
        assert wa._evidence.get() == []


def test_projected_synthetic_content_is_not_human_testimony():
    from agent.conversation_loop import _EMPTY_TOOL_RESPONSE_NUDGE, _DROPPED_TOOLCALL_NUDGE_CONTENT
    from agent.context_compressor import SUMMARY_PREFIX
    for content in (_EMPTY_TOOL_RESPONSE_NUDGE, _DROPPED_TOOLCALL_NUDGE_CONTENT,
                    SUMMARY_PREFIX + "fabricated preference"):
        messages = [{"role": "user", "content": "Keep seasons consistent."},
                    {"role": "user", "content": content},
                    {"role": "user", "content": "Continue."}]
        with wa.review_evidence(messages):
            assert [s["text"] for s in wa._evidence.get()] == [messages[0]["content"], "Continue."]


def test_background_source_retains_human_antecedents():
    @wa.capture_review_evidence
    def invocation(agent, messages):
        return wa._evidence.get()
    snapshot = [{"role": "user", "content": "Prefer matching season groups."},
                {"role": "assistant", "content": "Actor claim."},
                {"role": "user", "content": "Continue."}]
    agent = SimpleNamespace(_durable_review_source=snapshot, _durable_review_source_is_machine=False)
    source = invocation(agent, [{"role": "user", "content": "Synthetic candidate-author request."}])
    assert [s["text"] for s in source] == [snapshot[0]["content"], "Continue."]


def test_runtime_prefix_messages_are_not_human_testimony():
    from agent.conversation_compression import _SYNTHETIC_USER_PREFIXES
    for prefix in _SYNTHETIC_USER_PREFIXES:
        with wa.review_evidence([{"role": "user", "content": prefix + " runtime content"}]):
            assert wa._evidence.get() == []


def test_busy_scheduler_reports_not_started(monkeypatch):
    monkeypatch.setattr(wa, "_review_slots", SimpleNamespace(acquire=lambda **kwargs: False))
    assert wa._start_review(lambda: pytest.fail("Must not start while busy")) is False
