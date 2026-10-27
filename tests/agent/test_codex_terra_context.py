"""Account-catalog extended context remains an explicit, wire-safe opt-in."""

from unittest.mock import MagicMock

import pytest

from agent import model_metadata as mm
from hermes_cli.codex_models import _add_context_variants


@pytest.mark.parametrize("base", ["gpt-6.1-terra", "gpt-6.1-sol"])
@pytest.mark.parametrize("advertised,maximum,expected", [
    (500_000, 872_000, 872_000), (500_000, 600_000, 600_000),
    (500_000, 1_050_000, 900_000), (500_000, None, 500_000),
    (1_050_000, 1_050_000, 900_000), (500_000, 400_000, 400_000),
])
def test_extended_variant_uses_published_max_without_changing_base(monkeypatch, base, advertised, maximum, expected):
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "models": [{"slug": base, "context_window": advertised, "max_context_window": maximum}]
    }
    monkeypatch.setattr(mm, "_codex_catalog_probe_allowed", lambda *args: True)
    monkeypatch.setattr(mm.model_metadata_http, "get", lambda *args, **kwargs: response)
    monkeypatch.setattr(mm, "_codex_oauth_context_cache", {})
    monkeypatch.setattr(mm, "_codex_oauth_max_context_cache", {})
    variant = base + "-900k"
    assert _add_context_variants([base]) == [base, variant]
    assert mm.strip_codex_context_variant_suffix(variant) == base
    resolve = mm._resolve_codex_oauth_context_length_with_source
    assert resolve(base, "test-catalog-credential")[0] == advertised
    assert resolve(variant, "test-catalog-credential")[0] == expected
    monkeypatch.setattr(mm, "save_context_length", MagicMock())
    assert mm.get_model_context_length(
        variant, provider="openai-codex", api_key="test-catalog-credential",
        base_url="https://chatgpt.com/backend-api/codex",
    ) == expected
    assert not mm.is_codex_context_variant(base + "-pro-900k")


def test_terra_cold_fallback_is_conservative():
    for model in ("gpt-6.1-terra", "gpt-6.1-terra-900k"):
        assert mm._resolve_codex_oauth_context_length_with_source(model) == (500_000, "fallback")


def test_terra_remembers_catalog_max_during_refresh_outage(monkeypatch):
    token = "test-catalog-credential"
    key = mm._codex_oauth_token_fingerprint(token)
    monkeypatch.setattr(mm, "_codex_catalog_probe_allowed", lambda *args: True)
    monkeypatch.setattr(mm, "_codex_oauth_context_cache", {key: ({"gpt-6.1-terra": 500_000}, 0)})
    monkeypatch.setattr(mm, "_codex_oauth_max_context_cache", {key: {"gpt-6.1-terra": 872_000}})
    monkeypatch.setattr(mm.model_metadata_http, "get", lambda *args, **kwargs: MagicMock(status_code=503))
    assert mm._resolve_codex_oauth_context_length_with_source("gpt-6.1-terra-900k", token) == (872_000, "fallback")
