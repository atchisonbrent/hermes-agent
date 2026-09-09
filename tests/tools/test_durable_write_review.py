"""Proposal review contracts with real pending/memory/skill files; no network."""
import json
from pathlib import Path

import pytest

# Deliberately inert provider fixture; never a credential or environment read.
FAKE_AUTH = "test-oauth-token"


@pytest.fixture
def review(monkeypatch, tmp_path):
    from tools import write_approval as wa
    from hermes_cli.config import load_config, save_config
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    cfg = load_config()
    cfg["durable_write_review"] = {"enabled": True, "model": "gpt-6-astra"}
    save_config(cfg)
    class Jobs(list):
        start_review = staticmethod(wa._start_review)
    jobs = Jobs()
    monkeypatch.setattr(wa, "_start_review", lambda callback: jobs.append(callback))
    return wa, jobs, tmp_path


def propose(wa, **kwargs):
    from tools.memory_tool import MemoryStore, memory_tool
    with wa.review_evidence([
        {"role": "user", "content": "Please remember that I prefer concise replies."},
        {"role": "assistant", "content": "Author claims are not evidence."},
    ]):
        return json.loads(memory_tool(store=MemoryStore(), **kwargs))


@pytest.mark.parametrize("batch", [False, True])
def test_accept_exact_memory_proposal(review, monkeypatch, batch):
    wa, jobs, home = review
    calls = []
    def decide(context, config):
        calls.append(context)
        return {"decision": "accept", "reason": "Explicit stable preference.",
                "evidence": ["source:0"]}, {"input_tokens": 100}
    monkeypatch.setattr(wa, "_review_call", decide)
    args = {"target": "user"}
    if batch:
        args["operations"] = [{"action": "add", "content": "Prefers concise replies."}]
    else:
        args.update(action="add", content="Prefers concise replies.")
    result = propose(wa, **args)
    assert result["staged"]
    assert not (home / "memories/USER.md").exists()
    assert len(jobs) == 1
    jobs[0]()
    assert "Prefers concise replies." in (home / "memories/USER.md").read_text()
    assert len(calls) == 1
    assert "Author claims" not in json.dumps(calls)
    assert wa.get_pending("memory", result["pending_id"]) is None
    jobs[0]()
    assert len(calls) == 1


def answer(decision="accept", evidence=None):
    return {"decision": decision, "reason": "Source supports this exact change.",
            "evidence": ["source:0"] if evidence is None else evidence}, {}


def test_thread_start_failure_defers_with_reason(review, monkeypatch):
    wa, jobs, home = review
    def fail(callback):
        raise RuntimeError("thread unavailable")
    monkeypatch.setattr(wa, "_start_review", fail)
    result = staged_memory(wa)
    record = wa.get_pending("memory", result["pending_id"])
    assert record["review"]["state"] == "defer"
    assert "start" in record["review"]["reason"].lower()
    assert not (home / "memories/USER.md").exists()


def test_omission_metadata_is_context_level(review):
    wa, jobs, home = review
    source = [{"id": "source:0", "role": "user", "text": "Prefers concise replies.",
               "omitted_tool_results": 2}]
    context = wa._review_context("memory", {"action": "add", "target": "user", "content": "Prefers concise replies."}, source, wa.review_config())
    assert context["omitted_source_results"] == 2
    assert "omitted_tool_results" not in context["source"][0]
    assert source[0]["omitted_tool_results"] == 2


def staged_memory(wa):
    return propose(wa, action="add", target="user", content="Prefers concise replies.")


@pytest.mark.parametrize("kind", ["reject", "defer", "no_evidence", "wrong_evidence", "error", "malformed"])
def test_nonacceptance_leaves_target_unchanged(review, monkeypatch, kind):
    wa, jobs, home = review
    def decide(*args):
        if kind == "error":
            raise RuntimeError("provider failure")
        if kind == "malformed":
            return {"decision": "accept", "replacement": "rewritten"}, {}
        if kind in ("no_evidence", "wrong_evidence"):
            return answer(evidence=[] if kind == "no_evidence" else ["author:0"])
        return answer(kind)
    monkeypatch.setattr(wa, "_review_call", decide)
    result = staged_memory(wa)
    jobs[0]()
    assert not (home / "memories/USER.md").exists()
    record = wa.get_pending("memory", result["pending_id"])
    if kind == "reject":
        assert record is None
        assert (home / "pending/memory/receipts" / (result["pending_id"] + ".json")).exists()
    else:
        assert record["review"]["state"] == "defer"


@pytest.mark.parametrize("kind", ["source", "memory", "missing", "secret", "multiline_secret"])
def test_incomplete_or_sensitive_context_never_calls_reviewer(review, monkeypatch, kind):
    wa, jobs, home = review
    from tools.memory_tool import MemoryStore, memory_tool
    if kind == "memory":
        (home / "memories").mkdir(exist_ok=True)
        (home / "memories/MEMORY.md").write_text("x" * 140000)
    text = "x" * 17000 if kind == "source" else "Please save my preference."
    if kind == "secret":
        text += " password=not-for-export-12345"
    if kind == "multiline_secret":
        marker = "PRIVATE" + " KEY"
        text += "\n-----BEGIN " + marker + "-----\nnot-a-real-key\n-----END " + marker + "-----"
    messages = [] if kind == "missing" else [{"role": "user", "content": text}]
    with wa.review_evidence(messages):
        result = json.loads(memory_tool(action="add", content="Fact", store=MemoryStore()))
    assert result["staged"]
    assert not jobs
    assert wa.get_pending("memory", result["pending_id"])["review"]["state"] == "defer"


@pytest.mark.parametrize("changed", ["target", "other_memory", "config", "payload"])
def test_stale_context_never_overwrites(review, monkeypatch, changed):
    wa, jobs, home = review
    from tools.memory_tool import MemoryStore
    def decide(*args):
        if changed in ("target", "other_memory"):
            store = MemoryStore()
            store.add("user" if changed == "target" else "memory", "Concurrent entry")
        elif changed == "config":
            with (home / "config.yaml").open("a") as f:
                f.write("\n# Changed during review\n")
        else:
            path = home / "pending/memory" / (result["pending_id"] + ".json")
            record = json.loads(path.read_text())
            record["payload"]["content"] = "Changed payload"
            path.write_text(json.dumps(record))
        return answer()
    monkeypatch.setattr(wa, "_review_call", decide)
    result = staged_memory(wa)
    jobs[0]()
    target = home / "memories/USER.md"
    assert not target.exists() or "Prefers concise replies" not in target.read_text()
    assert wa.get_pending("memory", result["pending_id"])


@pytest.mark.parametrize("state", ["reviewing", "applying", "accepted", "applied"])
def test_no_automatic_replay_after_restart(review, monkeypatch, state):
    wa, jobs, home = review
    result = staged_memory(wa)
    record = wa.get_pending("memory", result["pending_id"])
    record["review"]["state"] = state
    wa._save_record(record)
    monkeypatch.setattr(wa, "_review_call", lambda *a: pytest.fail("Unexpected retry"))
    wa._process_review("memory", result["pending_id"], home)
    assert not (home / "memories/USER.md").exists()


def test_human_gate_remains_required_after_automatic_acceptance(review, monkeypatch):
    wa, jobs, home = review
    from hermes_cli.config import load_config, save_config
    from hermes_cli.write_approval_commands import handle_pending_subcommand
    from tools.memory_tool import MemoryStore
    cfg = load_config()
    cfg["memory"]["write_approval"] = True
    save_config(cfg)
    monkeypatch.setattr(wa, "_review_call", lambda *a: answer())
    result = staged_memory(wa)
    jobs[0]()
    assert not (home / "memories/USER.md").exists()
    assert wa.get_pending("memory", result["pending_id"])["review"]["state"] == "accepted"
    output = handle_pending_subcommand("memory", ["approve", result["pending_id"]], memory_store=MemoryStore())
    assert "Approved 1" in output
    assert (home / "memories/USER.md").exists()


@pytest.mark.parametrize("state", ["applying", "applied"])
def test_manual_approval_cannot_replay_uncertain_auto_apply(review, state):
    wa, jobs, home = review
    from hermes_cli.write_approval_commands import handle_pending_subcommand
    from tools.memory_tool import MemoryStore
    result = staged_memory(wa)
    record = wa.get_pending("memory", result["pending_id"])
    record["review"]["state"] = state
    wa._save_record(record)
    output = handle_pending_subcommand("memory", ["approve", result["pending_id"]], memory_store=MemoryStore())
    assert "Approved 0" in output
    assert not (home / "memories/USER.md").exists()


def test_broken_config_fails_closed(review):
    wa, jobs, home = review
    (home / "config.yaml").write_text("durable_write_review: [broken yaml")
    result = staged_memory(wa)
    assert not result["success"]
    assert not (home / "memories/USER.md").exists()


@pytest.fixture
def skill_owner(review):
    wa, jobs, home = review
    root = home / "skills/probe"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text("---\nname: probe\ndescription: Repeat a validated procedure.\n---\n# Probe\nStep 1.\n")
    (root / "references").mkdir()
    (root / "references/check.md").write_text("Check old behavior")
    return root


@pytest.mark.parametrize("stale", [False, True])
def test_multifile_skill_batch_review(review, skill_owner, monkeypatch, stale):
    wa, jobs, home = review
    from tools.skill_manager_tool import skill_manage
    def decide(context, config):
        assert context["files"]["probe/references/check.md"]["text"] == "Check old behavior"
        if stale:
            (skill_owner / "references/check.md").write_text("Concurrent owner change")
        return answer()
    monkeypatch.setattr(wa, "_review_call", decide)
    with wa.review_evidence([{"role": "user", "content": "Repeated tests demonstrate Step 1 should be Step 2."}]):
        result = json.loads(skill_manage(action="batch", name="probe", operations=[
            {"action": "patch", "name": "probe", "old_string": "Step 1.", "new_string": "Step 2."},
            {"action": "write_file", "name": "probe", "file_path": "references/check.md", "file_content": "Check new behavior"},
        ]))
    assert result["staged"]
    assert len(jobs) == 1
    jobs[0]()
    assert ("Step 1." if stale else "Step 2.") in (skill_owner / "SKILL.md").read_text()
    assert (skill_owner / "references/check.md").read_text() == ("Concurrent owner change" if stale else "Check new behavior")


def test_skill_batch_validation_rolls_back(review, skill_owner, monkeypatch):
    wa, jobs, home = review
    from tools.skill_manager_tool import skill_manage
    monkeypatch.setattr(wa, "_review_call", lambda *a: answer())
    before = (skill_owner / "SKILL.md").read_text()
    with wa.review_evidence([{"role": "user", "content": "Fix the demonstrated defect."}]):
        result = json.loads(skill_manage(action="batch", name="probe", operations=[
            {"action": "patch", "name": "probe", "old_string": "Step 1.", "new_string": "Step 2."},
            {"action": "write_file", "name": "probe", "file_path": "bad/nope.md", "file_content": "invalid"},
        ]))
    jobs[0]()
    assert (skill_owner / "SKILL.md").read_text() == before
    assert wa.get_pending("skills", result["pending_id"])["review"]["state"] == "defer"


def test_single_skill_and_batch_default_name_preserve_exact_payload(review, skill_owner, monkeypatch):
    wa, jobs, home = review
    from tools.skill_manager_tool import skill_manage
    monkeypatch.setattr(wa, "_review_call", lambda *a: answer())
    with wa.review_evidence([{"role": "user", "content": "Validated defect: Step 1 must be Step 2."}]):
        result = json.loads(skill_manage(action="batch", name="probe", operations=[
            {"action": "patch", "old_string": "Step 1.", "new_string": "Step 2."},
        ]))
    assert result["staged"]
    assert jobs
    jobs.pop(0)()
    assert "Step 2." in (skill_owner / "SKILL.md").read_text()
    with wa.review_evidence([{"role": "user", "content": "Validated defect: Step 2 must be Step 3."}]):
        result = json.loads(skill_manage(action="patch", name="probe", old_string="Step 2.", new_string="Step 3."))
    jobs.pop(0)()
    assert "Step 3." in (skill_owner / "SKILL.md").read_text()


def test_real_oauth_resolver_and_codex_wire_have_one_attempt_no_tools_or_caps(review, monkeypatch):
    from types import SimpleNamespace as NS
    import agent.auxiliary_client as aux
    wa, jobs, home = review
    result = staged_memory(wa)
    record = wa.get_pending("memory", result["pending_id"])
    created, wire, options = [], [], []
    class Raw:
        api_key = FAKE_AUTH
        base_url = aux._CODEX_AUX_BASE_URL
        timeout = 120
        def __init__(self, **kwargs):
            created.append(kwargs)
            self.responses = NS(create=self.create)
        def with_options(self, **kwargs):
            options.append(kwargs)
            return self
        def create(self, **kwargs):
            wire.append(kwargs)
            return NS(output=[{"type": "message", "content": [
                {"type": "output_text", "text": json.dumps(answer()[0])}]}], usage=None)
        def close(self):
            pass
    monkeypatch.setattr(aux, "OpenAI", Raw)
    monkeypatch.setattr(aux, "_select_pool_entry", lambda *a: (False, None))
    monkeypatch.setattr(aux, "_read_codex_access_token", lambda: "test-oauth-token")
    monkeypatch.setattr(aux, "_openai_http_client_kwargs", lambda *a: {})
    decision, usage = wa._review_call(record["review"]["context"], record["review"]["config"])
    assert decision["decision"] == "accept"
    assert len(created) == len(wire) == 1
    assert created[0]["api_key"] == "test-oauth-token"
    assert str(created[0]["base_url"]).rstrip("/") == aux._CODEX_AUX_BASE_URL.rstrip("/")
    assert options[0]["max_retries"] == 0
    assert wire[0]["model"] == "gpt-6-astra"
    assert not ({"tools", "max_tokens", "max_output_tokens", "max_completion_tokens"} & wire[0].keys())
    # OAuth absent must not try the main model or API credentials.
    monkeypatch.setattr(aux, "_read_codex_access_token", lambda: None)
    with pytest.raises(ValueError, match="OAuth"):
        wa._review_call(record["review"]["context"], record["review"]["config"])
    assert len(created) == len(wire) == 1


@pytest.mark.parametrize("raw", [
    '```json\n{"decision":"accept","reason":"yes","evidence":["source:0"]}\n```',
    '{"decision":"reject","decision":"accept","reason":"yes","evidence":["source:0"]}',
    '{"decision":"accept","reason":"yes","evidence":[]}',
    '{"decision":"accept","reason":"yes","evidence":["source:99"]}',
    '{"decision":"accept","reason":"yes","evidence":["source:0"],"rewrite":"new"}',
])
def test_strict_parser_rejects_unbound_decisions(review, raw):
    wa, jobs, home = review
    result = staged_memory(wa)
    context = wa.get_pending("memory", result["pending_id"])["review"]["context"]
    with pytest.raises(ValueError):
        wa._parse_decision(raw, context)


def test_competing_processes_only_call_and_apply_once(review):
    import os
    import subprocess
    import sys
    wa, jobs, home = review
    result = staged_memory(wa)
    code = '''
import sys
from pathlib import Path
from tools import write_approval as wa
home = Path(sys.argv[1])
def decide(*args):
    with (home / "calls").open("a") as f:
        f.write("call\\n")
    return {"decision": "accept", "reason": "Explicit preference", "evidence": ["source:0"]}, {}
wa._review_call = decide
wa._process_review("memory", sys.argv[2], home)
'''
    processes = [subprocess.Popen([sys.executable, "-c", code, str(home), result["pending_id"]],
                                  env=dict(os.environ), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for _ in range(2)]
    for process in processes:
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == 0, stderr.decode()
    assert (home / "calls").read_text().splitlines() == ["call"]
    assert (home / "memories/USER.md").read_text().count("Prefers concise replies.") == 1


def test_real_background_worker_does_not_block_task_or_overwrite_concurrent_write(review, monkeypatch):
    import threading
    wa, jobs, home = review
    from tools.memory_tool import MemoryStore
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    def decide(*a):
        entered.set()
        assert release.wait(10)
        return answer()
    monkeypatch.setattr(wa, "_review_call", decide)
    # Restore the real scheduler, replacing only the network call.
    monkeypatch.setattr(wa, "_start_review", jobs.start_review)
    original = wa._process_review
    def process(*a):
        try:
            return original(*a)
        finally:
            finished.set()
    monkeypatch.setattr(wa, "_process_review", process)
    try:
        result = staged_memory(wa)
        assert result["staged"]
        assert entered.wait(10)
        # The reviewer is still waiting; a normal supported write can finish.
        assert MemoryStore().add("user", "Concurrent entry")["success"]
    finally:
        release.set()
        assert finished.wait(10)
    assert "Prefers concise replies" not in (home / "memories/USER.md").read_text()


def test_crash_after_side_effect_cannot_replay(review, monkeypatch):
    wa, jobs, home = review
    from tools import memory_tool as mt
    monkeypatch.setattr(wa, "_review_call", lambda *a: answer())
    real_apply = mt.apply_memory_pending
    def crash(payload, store):
        assert real_apply(payload, store)["success"]
        raise SystemExit("simulated process exit before receipt")
    monkeypatch.setattr(mt, "apply_memory_pending", crash)
    result = staged_memory(wa)
    with pytest.raises(SystemExit):
        jobs[0]()
    assert wa.get_pending("memory", result["pending_id"])["review"]["state"] == "applying"
    monkeypatch.setattr(wa, "_review_call", lambda *a: pytest.fail("Replayed crashed proposal"))
    wa._process_review("memory", result["pending_id"], home)
    assert (home / "memories/USER.md").read_text().count("Prefers concise replies.") == 1


@pytest.mark.parametrize("mode", ["shared", "sequential_quiet", "sequential_verbose", "concurrent"])
@pytest.mark.parametrize("tool", ["memory", "skill_manage"])
def test_actual_dispatchers_capture_original_evidence(review, skill_owner, monkeypatch, mode, tool):
    from types import SimpleNamespace as NS
    from unittest.mock import MagicMock, patch
    from run_agent import AIAgent
    from tools.memory_tool import MemoryStore
    from agent.agent_runtime_helpers import invoke_tool
    from agent.tool_executor import execute_tool_calls_sequential, execute_tool_calls_concurrent
    wa, jobs, home = review
    with (
        patch("run_agent.get_tool_definitions", return_value=[
            {"type": "function", "function": {"name": tool, "description": "Test",
             "parameters": {"type": "object", "properties": {}}}}]),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
        patch("agent.model_metadata.fetch_model_metadata", return_value={}),
    ):
        agent = AIAgent(api_key=FAKE_AUTH, base_url="https://example.invalid/v1", provider="custom",
                        model="test-model", quiet_mode=mode != "sequential_verbose",
                        skip_context_files=True, skip_memory=True)
    agent._memory_store = MemoryStore()
    agent._memory_manager = None
    agent._flush_messages_to_session_db = MagicMock(return_value=True)
    agent._append_guardrail_observation = MagicMock(side_effect=lambda _n, _a, r, **kw: r)
    agent._record_file_mutation_result = MagicMock()
    agent._subdirectory_hints.check_tool_call = MagicMock(return_value="")
    agent._tool_result_content_for_active_model = MagicMock(side_effect=lambda _n, r: r)
    args = ({"action": "add", "target": "user", "content": "Prefers concise replies."}
            if tool == "memory" else {"action": "patch", "name": "probe", "old_string": "Step 1.", "new_string": "Step 2."})
    call = NS(id="write1", type="function", function=NS(name=tool, arguments=json.dumps(args)))
    assistant = NS(tool_calls=[call])
    messages = [{"role": "user", "content": "Original current turn evidence."}]
    if mode == "shared":
        invoke_tool(agent, tool, args, "task", tool_call_id="write1", messages=messages)
    else:
        execute = execute_tool_calls_concurrent if mode == "concurrent" else execute_tool_calls_sequential
        execute(agent, assistant, messages, "task", finalize=False)
    subsystem = "memory" if tool == "memory" else "skills"
    records = wa.list_pending(subsystem)
    assert len(records) == 1, messages
    context = records[0]["review"]["context"]
    assert context["source"] == [{"id": "source:0", "role": "user", "text": "Original current turn evidence."}]
    assert wa._evidence.get() is None
    assert len(jobs) == 1
    assert messages[0] == {"role": "user", "content": "Original current turn evidence."}


def test_background_candidate_prompt_is_not_original_evidence(review):
    from types import SimpleNamespace
    wa, jobs, home = review
    @wa.capture_review_evidence
    def invocation(agent, messages):
        from tools.memory_tool import memory_tool, MemoryStore
        return json.loads(memory_tool(action="add", content="Fact", store=MemoryStore()))
    agent = SimpleNamespace(_durable_review_source=[
        {"role": "user", "content": "Original user evidence."},
        {"role": "assistant", "content": "Candidate-author claims."},
    ])
    result = invocation(agent, [{"role": "user", "content": "Synthetic background review request."}])
    context = wa.get_pending("memory", result["pending_id"])["review"]["context"]
    assert context["source"] == [{"id": "source:0", "role": "user", "text": "Original user evidence."}]


def test_background_skill_apply_preserves_read_and_ownership_guards(review, skill_owner, monkeypatch):
    import contextvars
    from tools.skill_provenance import set_current_write_origin
    from tools import skill_manager_tool as sm, skill_usage
    wa, jobs, home = review
    skill_usage.mark_agent_created("probe")
    monkeypatch.setattr(wa, "_review_call", lambda *a: answer())
    def propose_background():
        set_current_write_origin("background_review")
        sm._reset_background_review_read_marks()
        with wa.review_evidence([{"role": "user", "content": "Repeated verification demonstrates this defect."}]):
            return json.loads(sm.skill_manage(action="patch", name="probe", old_string="Step 1.", new_string="Step 2."))
    result = contextvars.Context().run(propose_background)
    assert result["staged"]
    jobs.pop(0)()
    assert "Step 1." in (skill_owner / "SKILL.md").read_text()
    assert wa.get_pending("skills", result["pending_id"])["review"]["state"] == "defer"
    def propose_read_background():
        set_current_write_origin("background_review")
        sm._reset_background_review_read_marks()
        sm.mark_background_review_skill_read(skill_owner / "SKILL.md")
        with wa.review_evidence([{"role": "user", "content": "Repeated verification demonstrates this defect."}]):
            return json.loads(sm.skill_manage(action="patch", name="probe", old_string="Step 1.", new_string="Step 2."))
    result = contextvars.Context().run(propose_read_background)
    assert result["staged"]
    jobs.pop(0)()
    assert "Step 2." in (skill_owner / "SKILL.md").read_text()


def test_candidate_tool_echoes_are_not_independent_evidence(review):
    wa, jobs, home = review
    from tools.memory_tool import memory_tool, MemoryStore
    messages = [
        {"role": "user", "content": "Inspect the problem."},
        {"role": "assistant", "tool_calls": [{"id": "author", "function": {"name": "skill_manage", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "author", "content": "Author-created claim."},
        {"role": "assistant", "tool_calls": [{"id": "test", "function": {"name": "terminal", "arguments": '{"command":"run-tests"}'}}]},
        {"role": "tool", "tool_call_id": "test", "content": "The validation passed."},
    ]
    with wa.review_evidence(messages):
        result = json.loads(memory_tool(action="add", content="Fact", store=MemoryStore()))
    source = wa.get_pending("memory", result["pending_id"])["review"]["context"]["source"]
    assert "Author-created claim" not in json.dumps(source)
    assert source[1]["tool_name"] == "terminal"
    assert source[1]["tool_request"] == '{"command":"run-tests"}'
    assert source[1]["text"] == "The validation passed."


@pytest.mark.parametrize("kind", ["provider", "blank_model", "model_alias", "invalid_enabled", "input_limit"])
def test_invalid_reviewer_configuration_cannot_fall_back(review, kind):
    from hermes_cli.config import load_config, save_config
    wa, jobs, home = review
    cfg = load_config()
    key, value = {
        "provider": ("provider", "openai"), "blank_model": ("model", ""),
        "model_alias": ("model", "moa:review"), "invalid_enabled": ("enabled", "yes"),
        "input_limit": ("max_input_bytes", 999999999),
    }[kind]
    cfg["durable_write_review"][key] = value
    save_config(cfg)
    result = staged_memory(wa)
    assert not result["success"]
    assert not jobs


def test_oauth_route_refuses_non_codex_endpoint_before_call(review, monkeypatch):
    from types import SimpleNamespace as NS
    import agent.auxiliary_client as aux
    wa, jobs, home = review
    result = staged_memory(wa)
    record = wa.get_pending("memory", result["pending_id"])
    raw = NS(api_key=FAKE_AUTH, base_url="https://api.openai.com/v1")
    client = aux.CodexAuxiliaryClient(raw, "gpt-6-astra")
    monkeypatch.setattr(aux, "resolve_provider_client", lambda *a, **kw: (client, "gpt-6-astra"))
    with pytest.raises(ValueError, match="OAuth"):
        wa._review_call(record["review"]["context"], record["review"]["config"])


def test_exception_after_apply_keeps_uncertain_fence(review, monkeypatch):
    from tools import memory_tool as mt
    from hermes_cli.write_approval_commands import handle_pending_subcommand
    wa, jobs, home = review
    monkeypatch.setattr(wa, "_review_call", lambda *a: answer())
    real_apply = mt.apply_memory_pending
    def fail_after_write(payload, store):
        real_apply(payload, store)
        raise RuntimeError("failed after replacement")
    monkeypatch.setattr(mt, "apply_memory_pending", fail_after_write)
    result = staged_memory(wa)
    jobs[0]()
    assert wa.get_pending("memory", result["pending_id"])["review"]["state"] == "applying"
    output = handle_pending_subcommand("memory", ["approve", result["pending_id"]], memory_store=mt.MemoryStore())
    assert "Approved 0" in output


def test_receipt_failure_cannot_turn_applied_write_back_into_pending_authority(review, monkeypatch):
    from tools.memory_tool import MemoryStore
    wa, jobs, home = review
    monkeypatch.setattr(wa, "_review_call", lambda *a: answer())
    monkeypatch.setattr(wa, "_finish_review", lambda *a, **kw: (_ for _ in ()).throw(OSError("receipt unavailable")))
    result = staged_memory(wa)
    jobs[0]()
    assert wa.get_pending("memory", result["pending_id"])["review"]["state"] == "applying"
    assert (home / "memories/USER.md").read_text().count("Prefers concise replies.") == 1


def test_missing_process_lock_defers_automatic_review(review, monkeypatch):
    from tools import memory_tool as mt
    wa, jobs, home = review
    monkeypatch.setattr(mt, "fcntl", None)
    monkeypatch.setattr(mt, "msvcrt", None)
    result = staged_memory(wa)
    assert result["staged"]
    assert wa.get_pending("memory", result["pending_id"])["review"]["state"] == "defer"
    assert not jobs
    assert not (home / "memories/USER.md").exists()


def test_human_prompt_does_not_hold_write_lock(review):
    import threading
    from hermes_cli.config import load_config, save_config
    from tools.memory_tool import MemoryStore, memory_tool
    from tools.terminal_tool import set_approval_callback
    wa, jobs, home = review
    cfg = load_config()
    cfg["durable_write_review"]["enabled"] = False
    cfg["memory"]["write_approval"] = True
    save_config(cfg)
    finished = threading.Event()
    observed = []
    def write_other_target():
        try:
            MemoryStore().add("memory", "Concurrent entry")
        finally:
            finished.set()
    worker = threading.Thread(target=write_other_target)
    def approve(*a, **kw):
        worker.start()
        observed.append(finished.wait(5))
        return "once"
    set_approval_callback(approve)
    try:
        result = json.loads(memory_tool(action="add", target="user", content="Preference", store=MemoryStore()))
    finally:
        set_approval_callback(None)
        if worker.ident:
            worker.join(10)
    assert result["success"]
    assert observed == [True]


def test_missing_affected_skill_file_defers_before_model_call(review, skill_owner):
    from tools.skill_manager_tool import skill_manage
    wa, jobs, home = review
    with wa.review_evidence([{"role": "user", "content": "Fix the demonstrated defect in the supporting file."}]):
        result = json.loads(skill_manage(action="patch", name="probe", file_path="references/missing.md",
                                        old_string="old", new_string="new"))
    assert result["staged"]
    assert not jobs
    assert wa.get_pending("skills", result["pending_id"])["review"]["state"] == "defer"
