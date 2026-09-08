"""Model-scoped native thresholds reach real request construction."""
from types import SimpleNamespace

import pytest

from agent.native_compaction import native_compaction_context_management


def test_loaded_astra_config_reaches_wire(tmp_path, monkeypatch):
    from run_agent import AIAgent

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "compression:\n"
        "  codex_responses_native: true\n"
        "  codex_responses_compact_threshold: 400000\n"
        "  codex_responses_model_thresholds:\n"
        "    gpt-6-astra: 204000\n"
        "  model_thresholds:\n"
        "    gpt-6-astra: 0.8\n"
    )
    agent = AIAgent(
        api_key="x", base_url="https://api.openai.com/v1",
        api_mode="codex_responses", model="gpt-6-astra", provider="openai-api",
        quiet_mode=True, skip_context_files=True, skip_memory=True,
        enabled_toolsets=[],
    )
    agent.context_compressor.threshold_tokens = 217_600
    wire = agent._build_api_kwargs([{"role": "user", "content": "hi"}])
    assert wire["context_management"] == [
        {"type": "compaction", "compact_threshold": 204_000}
    ]


@pytest.mark.parametrize("value", [
    None, [], "bad", {}, {"gpt-6-astra": 999_999},
    {"gpt-6-astra": -5}, {"gpt-6-astra": {}},
    {"gpt-6-astra": 204000.0}, {"GPT-6-ASTRA": 204_000},
    {"gpt-5.6-sol": 204_000},
])
def test_missing_invalid_or_high_overrides_preserve_safety_clamp(value):
    agent = SimpleNamespace(
        model="gpt-6-astra", base_url="https://api.openai.com/v1",
        codex_responses_native_compaction=True, compression_enabled=True,
        codex_responses_compact_threshold=400_000,
        codex_responses_model_thresholds=value,
        context_compressor=SimpleNamespace(threshold_tokens=217_600),
    )
    assert native_compaction_context_management(agent, is_codex_backend=False) == [
        {"type": "compaction", "compact_threshold": 209_408}
    ]


def test_model_override_changes_gateway_and_tui_signatures():
    from gateway.run import GatewayRunner
    from tui_gateway.server import _tui_compression_config_signature

    cfg = {"compression": {"codex_responses_model_thresholds": {"gpt-6-astra": 204_000}}}
    assert GatewayRunner._extract_cache_busting_config(cfg)[
        "compression.codex_responses_model_thresholds"
    ] == {"gpt-6-astra": 204_000}
    assert _tui_compression_config_signature(cfg) != _tui_compression_config_signature({})


def test_live_config_adopts_and_unsets_model_override():
    from tui_gateway.server import _apply_live_compression_config

    agent = SimpleNamespace(context_compressor=None)
    _apply_live_compression_config(agent, {
        "compression": {"codex_responses_model_thresholds": {"gpt-6-astra": 204_000}}
    })
    assert agent.codex_responses_model_thresholds == {"gpt-6-astra": 204_000}
    _apply_live_compression_config(agent, {})
    assert agent.codex_responses_model_thresholds == {}
