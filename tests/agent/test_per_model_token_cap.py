"""A per-model cap exception must not change other models or switch previews."""
from types import SimpleNamespace

import pytest

from agent.context_compressor import ContextCompressor


def test_live_config_applies_and_removes_model_cap_exception():
    from tui_gateway.session_compression import _apply_live_compression_config
    cc = ContextCompressor(model="internal-model", config_context_length=1048576,
                           threshold_percent=0.75, threshold_tokens_cap=450000,
                           quiet_mode=True)
    agent = SimpleNamespace(context_compressor=cc, model="internal-model", provider="custom",
                            api_mode="chat_completions", base_url="", _config_context_length=None)
    cfg = {"model": {"default": "internal-model", "provider": "custom", "context_length": 1048576},
           "compression": {"threshold":0.75, "threshold_tokens":450000,
                           "model_threshold_tokens":{"internal-model":0}}}
    _apply_live_compression_config(agent, cfg)
    assert cc.threshold_tokens == 786432
    del cfg["compression"]["model_threshold_tokens"]
    _apply_live_compression_config(agent, cfg)
    assert cc.threshold_tokens == 450000


@pytest.mark.parametrize("value", [True, False, -1, 0.5, "0", None, [], {}])
def test_invalid_model_cap_keeps_global_cap(value):
    cc = ContextCompressor(model="internal-model", config_context_length=1048576,
                           threshold_percent=0.75, threshold_tokens_cap=450000,
                           model_threshold_tokens={"internal-model":value}, quiet_mode=True)
    assert cc.threshold_tokens == 450000


def test_exact_route_precedes_exact_model_and_caps_to_window():
    cc = ContextCompressor(model="internal-model", provider="custom", config_context_length=1048576,
                           threshold_percent=0.75, threshold_tokens_cap=450000,
                           model_threshold_tokens={"custom:internal-model":600000,
                                                   "internal-model":0}, quiet_mode=True)
    assert cc.threshold_tokens == 600000
    assert cc.preview_threshold_tokens("internal-model",1048576,"other") == 786432
    assert cc.preview_threshold_tokens("internal-model-extra",1048576,"custom") == 450000
    cc.update_model("internal-model", 200000, provider="custom")
    assert cc.threshold_tokens < 200000



def test_model_cap_exception_survives_model_switch_and_preview():
    cc = ContextCompressor(
        model="internal-model", provider="custom", config_context_length=1048576, threshold_percent=0.5,
        threshold_tokens_cap=450000, model_thresholds={"internal-model":0.75},
        model_threshold_tokens={"internal-model":0}, quiet_mode=True,
    )
    assert cc.threshold_tokens == 786432
    assert cc.preview_threshold_tokens("other-model", 1048576) == 450000
    cc.update_model("other-model", 1048576)
    assert cc.threshold_tokens == 450000
    assert cc.preview_threshold_tokens("internal-model", 1048576, "saved-internal") == 786432
    cc.update_model("internal-model", 1048576, provider="saved-internal")
    assert cc.threshold_tokens == 786432
