"""GPT-6.1 SOL shares the existing 900K opt-in and live-ceiling safeguards."""

import pytest

from agent import model_metadata as metadata
from hermes_cli.codex_models import _finalize_codex_models


@pytest.mark.parametrize("base", ["gpt-6.1-sol", "gpt-6.1-sol-2026-09-29"])
def test_gpt61_sol_picker_variant_normalizes_to_base(base):
    variant = f"{base}-900k"
    assert _finalize_codex_models([base]) == [base, variant]
    assert metadata.strip_codex_context_variant_suffix(f"openai/{variant}") == f"openai/{base}"
    assert not metadata.is_codex_900k_base(f"{base}-pro")


def test_gpt61_sol_offline_context_preserves_opt_in_boundary():
    assert metadata._resolve_codex_oauth_context_length_with_source("gpt-6.1-sol")[0] == \
        metadata._CODEX_OAUTH_STALE_ADVERTISED_CTX
    assert metadata._resolve_codex_oauth_context_length_with_source("gpt-6.1-sol-900k")[0] == \
        metadata._verified_codex_ctx_for_slug("gpt-6.1-sol-900k")
    new_ceiling = metadata._verified_codex_ctx_for_slug("gpt-6.1-sol-900k")
    old_ceiling = metadata._verified_codex_ctx_for_slug("gpt-6-sol-900k")
    assert new_ceiling is not None and old_ceiling is not None
    assert metadata._CODEX_OAUTH_STALE_ADVERTISED_CTX < new_ceiling == old_ceiling


def test_gpt61_sol_variant_respects_lower_live_catalog_ceiling(monkeypatch):
    token = "test-catalog-token"
    published_ceiling = 800_000
    monkeypatch.setattr(metadata, "_fetch_codex_oauth_context_lengths_with_source",
                        lambda _: ({"gpt-6.1-sol": metadata._CODEX_OAUTH_STALE_ADVERTISED_CTX}, True))
    monkeypatch.setattr(metadata, "_codex_oauth_max_context_cache", {
        metadata._codex_oauth_token_fingerprint(token): {"gpt-6.1-sol": published_ceiling}})
    assert metadata._resolve_codex_oauth_context_length_with_source(
        "gpt-6.1-sol-900k", token) == (published_ceiling, "live")
