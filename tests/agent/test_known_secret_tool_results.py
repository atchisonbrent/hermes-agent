"""Every tool result is scrubbed of known secret values as it becomes the message the model sees.

A registered tool, an MCP tool rendering a real ``CallToolResult`` and a tool returning a multimodal
result run through the agent's real executors (registry dispatch included); none of them redacts its
own output. The rows built elsewhere (spill previews, late LSP notes, provider-projected rows, the
outer-loop error result, MCP sampling requests) are covered too. All values are synthetic.
"""

import json
from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult, TextContent
from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageToolCall

from agent import known_secret_values as ksv
from tools.registry import registry

VALUE = "synthetic-dispatch-value-4Hq9"
MARK = "«redacted-secret:SERVICE_SIGNING_TOKEN»"
TOOLSET = "known-secret-probe"


def _plain(args, **kwargs):
    return f"config dump: signing={VALUE}"


def _mcp(args, **kwargs):
    from tools.mcp_tool_handlers import _render_call_tool_result
    result = CallToolResult(content=[TextContent(type="text", text=f"server read {VALUE}")],
                            structuredContent={"credential": VALUE})
    return _render_call_tool_result(result, "fakesrv")


def _multimodal(args, **kwargs):
    return {"_multimodal": True, "text_summary": f"window text {VALUE}",
            "content": [{"type": "text", "text": f"window text {VALUE}"}]}


def _spill(args, **kwargs):
    return "a" * 1480 + VALUE + "b" * 1000  # the value straddles the 1,500-character preview cut


HANDLERS = {"known_secret_plain": _plain, "mcp_fakesrv_read": _mcp, "known_secret_window": _multimodal}
EXTRA = {"known_secret_spill": (_spill, 2000), "known_secret_clean": (lambda args, **kwargs: "ok", None)}


@pytest.fixture
def agent():
    from run_agent import AIAgent
    ksv.clear_known_secrets()
    ksv.register_known_secrets(None, {"SERVICE_SIGNING_TOKEN": VALUE})
    tools = {**{name: (handler, None) for name, handler in HANDLERS.items()}, **EXTRA}
    for name, (handler, max_size) in tools.items():
        registry.register(name=name, toolset=TOOLSET, handler=handler, max_result_size_chars=max_size, schema={
            "name": name, "description": "Return test-owned text.", "parameters": {"type": "object", "properties": {}}})
    try:
        yield AIAgent(model="test-model", provider="openai", api_key="unused-test-key",
                      base_url="http://127.0.0.1:9/v1", enabled_toolsets=[TOOLSET], quiet_mode=True,
                      skip_context_files=True, skip_memory=True, save_trajectories=False)
    finally:
        for name in tools:
            registry.deregister(name)
        ksv.clear_known_secrets()


def _assistant(names):
    calls = [ChatCompletionMessageToolCall.model_validate({
        "id": f"call-{i}", "type": "function", "function": {"name": name, "arguments": "{}"}})
        for i, name in enumerate(names)]
    return ChatCompletionMessage(role="assistant", content=None, tool_calls=calls)


@pytest.mark.parametrize("executor", ["sequential", "concurrent"])
def test_tool_results_are_scrubbed_on_the_dispatch_path(agent, executor):
    from agent import tool_executor
    run = {"sequential": tool_executor.execute_tool_calls_sequential,
           "concurrent": tool_executor.execute_tool_calls_concurrent}[executor]
    messages: list = []
    run(agent, _assistant(list(HANDLERS)), messages, "known-secret-probe", finalize=False)
    tool_rows = [m for m in messages if m.get("role") == "tool"]
    assert len(tool_rows) == len(HANDLERS)
    for row in tool_rows:
        rendered = json.dumps(row["content"], ensure_ascii=False)
        assert VALUE not in rendered, row["name"]
        assert MARK in rendered, row["name"]


def _run_one(agent, name: str) -> dict:
    from agent import tool_executor
    messages: list = []
    tool_executor.execute_tool_calls_sequential(agent, _assistant([name]), messages, "known-secret-probe", finalize=False)
    return next(m for m in messages if m.get("role") == "tool")


def test_a_value_across_the_preview_cut_is_not_partly_visible(agent):
    content = _run_one(agent, "known_secret_spill")["content"]
    assert "too large" in content  # spilled: the model sees the preview
    assert VALUE[:12] not in content


def test_late_lsp_diagnostics_are_scrubbed_on_both_routes(agent):
    from agent.lsp import deferred
    from agent.turn_stop_gates import _late_lsp_verdicts
    note = f"error: unused literal '{VALUE}'"
    deferred.post(agent.session_id, "/synthetic/app.py", note, None)
    content = _run_one(agent, "known_secret_clean")["content"]  # rides the next tool result
    assert "unused literal" in content and VALUE not in content and MARK in content
    deferred.post(agent.session_id, "/synthetic/app.py", note, None)
    turn_end = _late_lsp_verdicts(agent)  # or the turn-end message
    assert "unused literal" in turn_end and VALUE not in turn_end and MARK in turn_end


def _projected_rows() -> list:
    return [{"role": "assistant", "content": None, "tool_calls": [
                {"id": "exec_1", "type": "function", "function": {"name": "exec_command", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "exec_1", "content": f"printed {VALUE}"}]


@pytest.mark.usefixtures("_registered_value")
def test_provider_projected_tool_rows_are_scrubbed():
    from agent.provider_projection import splice_provider_projection
    messages: list = []
    splice_provider_projection(SimpleNamespace(provider="agent-provider"),
                               SimpleNamespace(hermes_projected_messages=_projected_rows()), messages)
    assert messages[-1]["tool_call_id"] == "exec_1" and messages[-1]["content"] == f"printed {MARK}"


@pytest.mark.usefixtures("_registered_value")
def test_codex_projected_rows_and_the_history_seed_are_scrubbed():
    from agent.codex_runtime import _persist_projected_messages
    from agent.codex_runtime_history_seed import render_history_seed
    messages: list = [{"role": "user", "content": "run it"}]
    _persist_projected_messages(SimpleNamespace(_session_db=None),
                                SimpleNamespace(projected_messages=_projected_rows(), submitted_user_text=None), messages)
    assert messages[-1]["content"] == f"printed {MARK}"
    seed = render_history_seed([*messages, {"role": "user", "content": "next"}])
    assert VALUE not in seed and MARK in seed


@pytest.fixture
def _registered_value():
    ksv.clear_known_secrets()
    ksv.register_known_secrets(None, {"SERVICE_SIGNING_TOKEN": VALUE})
    yield
    ksv.clear_known_secrets()


@pytest.mark.usefixtures("_registered_value")
def test_outer_loop_error_result_is_scrubbed_with_its_fields_unchanged():
    from agent.turn_loop_errors import handle_outer_loop_error
    from tests.agent.test_failed_turn_chat_copy import _Agent
    messages = [_projected_rows()[0]]
    try:
        raise RuntimeError(f"upstream echoed {VALUE}")
    except RuntimeError as exc:
        handle_outer_loop_error(_Agent(), e=exc, _outer_error_count=0, api_call_count=1, messages=messages,
                                conversation_history=None, _turn_exit_reason="unknown", failed=False,
                                final_response=None)
    row = messages[-1]
    assert row["role"] == "tool" and row["tool_call_id"] == "exec_1" and row["name"] == "exec_command"
    assert VALUE not in row["content"] and MARK in row["content"]


@pytest.mark.usefixtures("_registered_value")
def test_mcp_sampling_request_text_is_scrubbed(monkeypatch):
    from mcp.types import CreateMessageRequestParams, SamplingMessage
    from agent import auxiliary_client
    from tools.mcp_tool_sampling import SamplingHandler
    sent = {}
    monkeypatch.setattr(auxiliary_client, "call_llm", lambda **kwargs: sent.update(kwargs))
    params = CreateMessageRequestParams(
        messages=[SamplingMessage(role="user", content=TextContent(type="text", text=f"summarise {VALUE}"))],
        maxTokens=64, systemPrompt=f"server context {VALUE}")
    SamplingHandler("fakesrv", {})._build_llm_call(params, "")()
    rendered = json.dumps(sent["messages"], ensure_ascii=False)
    assert VALUE not in rendered and rendered.count(MARK) == 2
