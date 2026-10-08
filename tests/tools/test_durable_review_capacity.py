"""Capacity controls exercise real packet building without inference or live state."""
import json
import py_compile
from pathlib import Path

import pytest

from tools import write_approval as wa


def configure(home, monkeypatch, **overrides):
    monkeypatch.setenv("HERMES_HOME", str(home))
    policy = {"enabled": True, "model": "gpt-6-astra", "max_input_bytes": "auto", **overrides}
    (home / "config.yaml").write_text(json.dumps({"durable_write_review": policy}))
    config = wa.review_config()
    assert config is not None
    return config


@pytest.mark.parametrize("limit", [131072, "auto"])
def test_complete_evidence_applies_but_any_generated_cache_defers(tmp_path, monkeypatch, limit):
    config = configure(tmp_path, monkeypatch, max_input_bytes=limit)
    skill = tmp_path / "skills" / "capacity-example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: capacity-example\ndescription: Demonstrate capacity.\n---\nOld step.\n")
    script = skill / "scripts" / "example.py"
    script.parent.mkdir()
    script.write_text("# Supporting evidence.\n" * (8000 if limit == "auto" else 100))
    evidence = "Observed verification details.\n" * (4000 if limit == "auto" else 100)
    messages = [{"role": "user", "content": "Correct the demonstrated step."},
                {"role": "assistant", "tool_calls": [{"id": "proof", "function": {"name": "read_file", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "proof", "content": evidence}]
    payload = {"action": "patch", "name": "capacity-example", "old_string": "Old step.", "new_string": "Verified step."}
    with wa.review_evidence(messages):
        context = wa._review_context("skills", payload, wa._evidence.get(), config)
    assert any(s["text"] == evidence for s in context["source"])
    assert context["files"]["capacity-example/scripts/example.py"]["text"] == script.read_text()
    assert context["capacity"]["input_tokens_estimate"] > 0
    assert context["capacity"]["input_tokens_estimate"] <= config["max_input_tokens"]
    # Exercise the supported writer, including the model decision and fresh
    # compare-before-apply boundary; only inference is replaced here.
    from tools.skill_manager_tool import skill_manage
    calls = []
    def accept(actual, settings):
        calls.append(actual)
        return {"decision": "accept", "reason": "Fixture control.", "evidence": ["source:0"]}, {}
    monkeypatch.setattr(wa, "_review_call", accept)
    with wa.review_evidence(messages):
        result = json.loads(skill_manage(**payload))
    assert result["saved"] is True and len(calls) == 1
    assert "Verified step." in (skill / "SKILL.md").read_text()
    # Even a genuine cache prevents review: header identity is not source proof.
    compiled = py_compile.compile(str(script), doraise=True)
    assert compiled is not None
    cache = Path(compiled)
    original = cache.read_bytes()
    before = (skill / "SKILL.md").read_bytes()
    calls.clear()
    payload.update(old_string="Verified step.", new_string="Another verified step.")
    for contents in (original, original + b"altered bytecode", b"plain text impostor"):
        cache.write_bytes(contents)
        with wa.review_evidence(messages):
            result = json.loads(skill_manage(**payload))
        assert result["saved"] is False
        assert calls == []
        assert (skill / "SKILL.md").read_bytes() == before
        assert cache.read_bytes() == contents
        with pytest.raises(wa._ReviewRefusal, match="cache"):
            wa._review_context("skills", payload, context["source"], config)


@pytest.mark.parametrize("relative", ["scripts/example.pyc", "scripts/example.pyo", "scripts/__PYCACHE__/x.PYC", "scripts/__pycache__/notes.txt"])
def test_cache_paths_and_new_targets_refuse(tmp_path, monkeypatch, relative):
    config = configure(tmp_path, monkeypatch)
    skill = tmp_path / "skills" / "cache-example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("Original step.")
    source = [{"id": "source:0", "role": "user", "text": "Update the step."}]
    payload = {"action": "write_file", "name": "cache-example", "file_path": relative, "file_content": "text"}
    with pytest.raises(wa._ReviewRefusal, match="durable-write target"):
        wa._review_context("skills", payload, source, config)
    target = skill / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("text impostor")
    with pytest.raises(wa._ReviewRefusal, match="prevents complete owner review"):
        wa._review_context("skills", {"action": "patch", "name": "cache-example", "old_string": "Original", "new_string": "New"}, source, config)


def test_cache_appearing_during_review_defers_and_other_binary_refuses(tmp_path, monkeypatch):
    config = configure(tmp_path, monkeypatch)
    skill = tmp_path / "skills" / "race-example"
    skill.mkdir(parents=True)
    owner = skill / "SKILL.md"
    owner.write_text("---\nname: race-example\ndescription: Exercise cache races.\n---\nOriginal step.\n")
    original = owner.read_bytes()
    cache = skill / "late.pyc"
    calls = []
    def accept(context, settings):
        calls.append(context)
        cache.write_bytes(b"unreviewed cache")
        return {"decision": "accept", "reason": "Fixture control.", "evidence": ["source:0"]}, {}
    monkeypatch.setattr(wa, "_review_call", accept)
    payload = {"action": "patch", "name": "race-example", "old_string": "Original step.", "new_string": "New step."}
    from tools.skill_manager_tool import skill_manage
    with wa.review_evidence([{"role": "user", "content": "Update the step."}]):
        result = json.loads(skill_manage(**payload))
    assert len(calls) == 1
    assert result["saved"] is False and result["review_state"] == "defer"
    assert owner.read_bytes() == original and cache.read_bytes() == b"unreviewed cache"
    cache.unlink()  # Disposable fixture only, not runtime cleanup.
    binary = skill / "assets" / "blob.bin"
    binary.parent.mkdir()
    binary.write_bytes(b"\xff\x00")
    with pytest.raises(wa._ReviewRefusal, match="Non-UTF8"):
        wa._review_context("skills", payload, calls[0]["source"], config)


@pytest.mark.parametrize("model", ["gpt-50", "x-gpt-5-y", "gpt-5-anything", "gpt-6-astra-900K", "GPT-6-ASTRA"])
def test_model_lookalikes_refused(tmp_path, monkeypatch, model):
    with pytest.raises(wa._ReviewRefusal):
        configure(tmp_path, monkeypatch, model=model)


def test_collection_is_lazy_for_unrelated_tools(monkeypatch):
    from types import SimpleNamespace
    def unexpected():
        pytest.fail("unrelated tool parsed reviewer config")
    monkeypatch.setattr(wa, "review_config", unexpected)
    @wa.capture_review_evidence
    def tool(agent, messages):
        return "unrelated result"
    assert tool(SimpleNamespace(), [{"role": "user", "content": "hello"}]) == "unrelated result"


def test_remaining_packet_budget_preserves_whole_human_and_reports_tools(tmp_path, monkeypatch):
    config = configure(tmp_path, monkeypatch, max_input_bytes=65536)
    memories = tmp_path / "memories"
    memories.mkdir()
    (memories / "MEMORY.md").write_text("Existing notes. " * 2000)
    messages = [{"role": "user", "content": "Record this preference."},
                {"role": "assistant", "tool_calls": [{"id": "proof", "function": {"name": "read_file", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "proof", "content": "x" * 40000}]
    with wa.review_evidence(messages):
        context = wa._review_context("memory", {"action": "add", "target": "user", "content": "Preference."}, wa._evidence.get(), config)
    assert context["omitted_source_results"] == 1
    assert [s["text"] for s in context["source"]] == ["Record this preference."]
    assert context["files"]["memory"]["text"] == (memories / "MEMORY.md").read_text()


def test_omission_digit_boundary_does_not_change_recheck(tmp_path, monkeypatch):
    config = configure(tmp_path, monkeypatch)
    payload = {"action": "add", "target": "user", "content": "A stable preference."}
    source = [{"id": "source:0", "role": "user", "text": "Record the preference."}]
    source += [{"id": f"source:{i}", "role": "tool", "text": "x" * 12000} for i in range(1, 11)]
    source.append({"id": "source:11", "role": "tool", "text": "Small relevant result."})
    # Find the exact fit boundary without freezing incidental path/policy sizes.
    low, high = 4096, 12000
    while low < high:
        middle = (low + high) // 2
        context = wa._review_context("memory", payload, source, {**config, "max_input_bytes": middle})
        if any(s["id"] == "source:11" for s in context["source"]):
            high = middle
        else:
            low = middle + 1
    settings = {**config, "max_input_bytes": low}
    context = wa._review_context("memory", payload, source, settings)
    assert context["omitted_source_results"] == 10
    assert len(context["source"]) == 2
    fresh = wa._review_context("memory", payload, context["source"], settings,
                              omitted_source_results=context["omitted_source_results"])
    assert fresh == context


def test_user_omissions_survive_review_and_apply(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch, max_input_bytes=65536)
    skill = tmp_path / "skills" / "omission-example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: omission-example\ndescription: Exercise omission accounting.\n---\nOld step.\n" + "Reference. " * 3600)
    messages = [{"role": "user", "content": str(i) + " Earlier context." * 1875} for i in range(4)]
    messages.append({"role": "user", "content": "Correct the step."})
    captured = []
    def accept(context, config):
        captured.append(context)
        return {"decision": "accept", "reason": "Controlled fixture.", "evidence": ["source:0"]}, {}
    monkeypatch.setattr(wa, "_review_call", accept)
    from tools.skill_manager_tool import skill_manage
    with wa.review_evidence(messages):
        result = json.loads(skill_manage(action="patch", name="omission-example", old_string="Old step.", new_string="New step."))
    assert captured[0]["omitted_earlier_user_messages"] == 4
    assert result["saved"] is True
    assert "New step." in (skill / "SKILL.md").read_text()


def test_capacity_is_profile_scoped_and_each_overflow_fails_closed(tmp_path, monkeypatch):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir(); second.mkdir()
    a = configure(first, monkeypatch)
    b = configure(second, monkeypatch, max_input_bytes=4096)
    again = configure(first, monkeypatch)
    assert a == again and b["max_input_bytes"] == 4096
    assert a["max_input_bytes"] > 131072
    source = [{"id": "source:0", "role": "user", "text": "Evidence. " * 1000}]
    payload = {"action": "add", "target": "user", "content": "A preference."}
    with pytest.raises(wa._ReviewRefusal, match="bytes"):
        wa._review_context("memory", payload, source, b)
    with pytest.raises(wa._ReviewRefusal, match="tokens"):
        wa._review_context("memory", payload, source, {**a, "max_input_tokens": 100})
    # A profile's model must be known on the exact Codex route, not guessed from
    # an unrelated API catalog or inherited from the interactive agent.
    with pytest.raises(wa._ReviewRefusal, match="context"):
        configure(first, monkeypatch, model="unrecognized-review-model")
