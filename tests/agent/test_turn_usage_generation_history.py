"""Each completed call records how long the provider actually streamed, beside its latency and output.

A throughput readout that divides output tokens by the whole call charges the model for queueing and
prompt processing. ``_api_generation_history`` holds first-chunk-to-end seconds, appended in step with
``_api_latency_history`` and ``_api_output_history`` so consumers can pair the three by position."""
from types import SimpleNamespace

import pytest


def _agent(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from run_agent import AIAgent
    return AIAgent(api_key="k", base_url="https://inference-api.nousresearch.com/v1", provider="nous",
                   api_mode="chat_completions", model="anthropic/claude-fable-5.1", session_id="t", platform="cli",
                   quiet_mode=True, skip_context_files=True, skip_memory=True, save_trajectories=False, enabled_toolsets=["file"])


def _response(output_tokens=120):
    return SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=output_tokens, total_tokens=1000 + output_tokens,
                              prompt_tokens_details=None, completion_tokens_details=None),
        id=None, model="anthropic/claude-fable-5.1")


def _record(agent, *, api_duration, api_start_time=None, response=None):
    from agent import turn_usage
    turn_usage.record_response_usage(
        agent, response or _response(), messages=[{"role": "user", "content": "hi"}], api_call_count=1,
        api_duration=api_duration, compression_attempts=0, max_compression_attempts=3, api_start_time=api_start_time)


def test_generation_excludes_the_wait_before_the_first_chunk(tmp_path, monkeypatch):
    a = _agent(tmp_path, monkeypatch)
    try:
        a._last_api_first_chunk_at = 1000.0 + 6.0  # six seconds of queueing and prompt processing
        _record(a, api_duration=10.0, api_start_time=1000.0)
        assert list(a._api_latency_history) == [10.0]
        assert list(a._api_output_history) == [120]
        assert list(a._api_generation_history) == [pytest.approx(4.0)]
    finally:
        a.close()


@pytest.mark.parametrize("first_chunk_at, api_start_time", [
    (None, 1000.0),      # nothing timed: non-streaming transport
    (1006.0, None),      # caller did not say when the call began
    (999.0, 1000.0),     # stale stamp from before this call
    (1011.0, 1000.0),    # stamp after the call ended
    (True, 1000.0),      # not a timestamp
])
def test_generation_falls_back_to_the_whole_call(tmp_path, monkeypatch, first_chunk_at, api_start_time):
    a = _agent(tmp_path, monkeypatch)
    try:
        a._last_api_first_chunk_at = first_chunk_at
        _record(a, api_duration=10.0, api_start_time=api_start_time)
        assert list(a._api_generation_history) == [10.0]
    finally:
        a.close()


def test_the_three_histories_stay_paired_and_bounded(tmp_path, monkeypatch):
    a = _agent(tmp_path, monkeypatch)
    try:
        for call in range(12):
            a._last_api_first_chunk_at = 1000.0 + 1.0
            _record(a, api_duration=3.0, api_start_time=1000.0, response=_response(output_tokens=call))
        assert len(a._api_latency_history) == len(a._api_output_history) == len(a._api_generation_history) == 10
        assert list(a._api_output_history) == list(range(2, 12))
        assert all(seconds == pytest.approx(2.0) for seconds in a._api_generation_history)
    finally:
        a.close()


def test_a_usage_less_response_records_no_generation_entry(tmp_path, monkeypatch):
    a = _agent(tmp_path, monkeypatch)
    try:
        a._last_api_first_chunk_at = 1001.0
        _record(a, api_duration=3.0, api_start_time=1000.0, response=SimpleNamespace(usage=None))
        assert a.session_api_calls == 1
        assert not a._api_latency_history and not a._api_output_history and not a._api_generation_history
    finally:
        a.close()


def test_the_real_turn_loop_records_only_the_streaming_window():
    """End to end through ``run_conversation``: a provider that waits before its first chunk is
    charged for the wait in the latency history but not in the generation history."""
    import time
    from unittest.mock import MagicMock, patch

    from run_agent import AIAgent

    wait_before_first_chunk = 0.4
    tool_defs = [{"type": "function", "function": {
        "name": "web_search", "description": "web_search tool", "parameters": {"type": "object", "properties": {}}}}]

    def _make_stream_chunk(content=None, finish_reason=None, model=None, usage=None):
        delta = SimpleNamespace(content=content, tool_calls=None, reasoning_content=None, reasoning=None)
        return SimpleNamespace(choices=[SimpleNamespace(index=0, delta=delta, finish_reason=finish_reason)],
                               model=model, usage=usage)

    def _slow_to_start():
        time.sleep(wait_before_first_chunk)  # health: allow HX013 -- the wait before the first chunk is the fixture under test
        yield _make_stream_chunk(content="Hello")
        yield _make_stream_chunk(
            content=" world", finish_reason="stop", model="test-model",
            usage=SimpleNamespace(prompt_tokens=50, completion_tokens=2, total_tokens=52,
                                  prompt_tokens_details=None, completion_tokens_details=None))

    with (
        patch("model_tools.get_tool_definitions", return_value=tool_defs),
        patch("model_tools.check_toolset_requirements", return_value={}),
        patch("agent.process_bootstrap.OpenAI"),
        patch("run_agent.AIAgent._create_request_openai_client") as create_client,
        patch("run_agent.AIAgent._close_request_openai_client"),
    ):
        agent = AIAgent(api_key="test-key-1234567890", base_url="https://openrouter.ai/api/v1",
                        quiet_mode=True, skip_context_files=True, skip_memory=True)
        agent.client = MagicMock()
        agent._cached_system_prompt = "You are helpful."
        agent._use_prompt_caching = False
        agent.compression_enabled = False
        agent.save_trajectories = False
        client = MagicMock()
        client.chat.completions.create.return_value = _slow_to_start()
        create_client.return_value = client
        # A registered stream consumer forces the streaming path with a Mock client.
        agent.stream_delta_callback = lambda _text: None
        with (
            patch.object(agent, "_persist_session"),
            patch.object(agent, "_save_trajectory"),
            patch.object(agent, "_cleanup_task_resources"),
        ):
            try:
                result = agent.run_conversation("hi")
            finally:
                agent.close()

    assert result["final_response"] == "Hello world"
    assert list(agent._api_output_history) == [2]
    (latency,), (generation,) = agent._api_latency_history, agent._api_generation_history
    assert latency >= wait_before_first_chunk
    assert 0.0 <= generation <= latency - wait_before_first_chunk * 0.9
