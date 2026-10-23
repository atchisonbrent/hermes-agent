"""Explicit catalog aliases supply context and effort metadata, not endpoint authority."""
import json

import pytest

from agent import model_metadata, models_dev
from hermes_constants import get_hermes_home


@pytest.fixture
def catalog(monkeypatch):
    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        "providers:\n  relay:\n    catalog_provider: example-vendor\n", encoding="utf-8"
    )
    registry = {"example-vendor": {"models": {"new-model": {
        "limit": {"context": 131072}, "reasoning": True,
        "reasoning_options": [{"type": "effort", "values": ["low", "high", "max"]}],
    }}}}
    (home / "models_dev_cache.json").write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(models_dev, "_models_dev_cache", registry)
    monkeypatch.setattr(models_dev, "_models_dev_cache_time", float("inf"))
    monkeypatch.setattr(model_metadata, "_resolve_endpoint_context_length", lambda *a, **k: None)
    monkeypatch.setattr(model_metadata, "_query_ollama_api_show", lambda *a, **k: None)
    return registry


def test_coreweave_context_uses_provider_catalog_on_custom_transport(catalog):
    catalog["wandb"] = {"models": {
        "new-model": {"limit": {"context": 131072}},
        "MiniMaxAI/MiniMax-M3": {"limit": {"context": 262144}},
    }}
    for model, entry in catalog["wandb"]["models"].items():
        # resolve_runtime_provider(requested="wandb") uses provider="custom"
        # for the OpenAI-compatible wire. Metadata must retain host identity.
        assert model_metadata.get_model_context_length(
            model, "https://api.inference.wandb.ai/v1", provider="custom") == entry["limit"]["context"]
    assert model_metadata._infer_provider_from_url("https://api.inference.wandb.ai.attacker.test/v1") is None
    assert model_metadata._infer_provider_from_url("https://other.api.inference.wandb.ai/v1") is None
    assert model_metadata._infer_provider_from_url("https://proxy.test/api.inference.wandb.ai/v1") is None


@pytest.mark.parametrize("provider", ["custom:wandb", "custom:named", "custom:openai"])
def test_named_coreweave_identity_keeps_declared_catalog(catalog, provider):
    (get_hermes_home() / "config.yaml").write_text(json.dumps({"providers": {
        "wandb": {"catalog_provider": "wandb"},
        "named": {"catalog_provider": "wandb"},
        "openai": {"catalog_provider": "wandb"},
    }}), encoding="utf-8")
    catalog["wandb"] = {"models": {
        "new-model": {"limit": {"context": 131072}},
        "MiniMaxAI/MiniMax-M3": {"limit": {"context": 262144}},
    }}
    for model, entry in catalog["wandb"]["models"].items():
        assert models_dev.get_model_capabilities(provider, model) is not None
        assert model_metadata.get_model_context_length(
            model, "https://api.inference.wandb.ai/v1", provider=provider) == entry["limit"]["context"]
    assert model_metadata.get_model_context_length("MiniMaxAI/MiniMax-M3", provider="wandb") == 262144
    assert models_dev._models_dev_id("openai", config={"providers": {"openai": {"catalog_provider": "wandb"}}}) == "openai"
    assert models_dev._models_dev_id("custom:wandb", config={"providers": {}}) is None
    assert models_dev._models_dev_id("wandb", config={"providers": {"wandb": {"catalog_provider": "example-vendor"}}}) == "wandb"


@pytest.mark.parametrize("provider", ["minimax", "novita"])
def test_existing_minimax_correction_is_preserved_elsewhere(catalog, provider):
    catalog[models_dev.PROVIDER_TO_MODELS_DEV[provider]] = {"models": {"MiniMaxAI/MiniMax-M3": {"limit": {"context": 262144}}}}
    assert model_metadata.get_model_context_length(
        "MiniMaxAI/MiniMax-M3", provider=provider) == model_metadata.DEFAULT_CONTEXT_LENGTHS["minimax-m3"]


def test_reasoning_efforts_are_explicit_catalog_data(catalog):
    caps = models_dev.get_model_capabilities("relay", "new-model")
    assert caps.reasoning_efforts == ("low", "high", "max")
    entry = catalog["example-vendor"]["models"]["new-model"]
    entry["reasoning_options"] = [{"type": "toggle"}]
    assert models_dev.get_model_capabilities("relay", "new-model").reasoning_efforts == ()
    entry["reasoning_options"] = []
    assert models_dev.get_model_capabilities("relay", "new-model").reasoning_efforts == ()
    del entry["reasoning_options"]
    assert models_dev.get_model_capabilities("relay", "new-model").reasoning_efforts is None
    entry["reasoning_options"] = [
        {"type": "effort", "values": [" Low ", "HIGH", "low", None, ""]},
        {"type": "effort", "values": ["high", "max"]},
    ]
    assert models_dev.get_model_capabilities("relay", "new-model").reasoning_efforts == ("low", "high", "max")
    entry["reasoning"] = False
    assert models_dev.get_model_capabilities("relay", "new-model").reasoning_efforts == ()
