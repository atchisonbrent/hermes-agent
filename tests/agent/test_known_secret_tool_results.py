"""Every tool result is scrubbed of known secret values as it becomes the message the model sees.

A registered tool, an MCP tool rendering a real ``CallToolResult`` and a tool returning a multimodal
result run through the agent's real executors (registry dispatch included); none of them redacts its
own output. All values are synthetic.
"""

import json

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


HANDLERS = {"known_secret_plain": _plain, "mcp_fakesrv_read": _mcp, "known_secret_window": _multimodal}


@pytest.fixture
def agent():
    from run_agent import AIAgent
    ksv.clear_known_secrets()
    ksv.register_known_secrets(None, {"SERVICE_SIGNING_TOKEN": VALUE})
    for name, handler in HANDLERS.items():
        registry.register(name=name, toolset=TOOLSET, handler=handler, schema={
            "name": name, "description": "Return test-owned text.", "parameters": {"type": "object", "properties": {}}})
    try:
        yield AIAgent(model="test-model", provider="openai", api_key="unused-test-key",
                      base_url="http://127.0.0.1:9/v1", enabled_toolsets=[TOOLSET], quiet_mode=True,
                      skip_context_files=True, skip_memory=True, save_trajectories=False)
    finally:
        for name in HANDLERS:
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
