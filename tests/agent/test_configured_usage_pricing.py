"""Profile-local reference prices for a deliberately keyless custom endpoint."""
from decimal import Decimal

import hermes_yaml as yaml
import pytest

from agent.usage_pricing import CanonicalUsage, estimate_usage_cost
from hermes_constants import get_hermes_home


def test_custom_reference_prices_apply_to_exact_endpoint_and_model(monkeypatch):
    # Real config loading; isolate only remote catalog I/O.
    monkeypatch.setattr("agent.usage_pricing.fetch_endpoint_model_metadata", lambda *a, **k: {})
    config = {
        "providers": {
            "internal": {
                "base_url": "http://inference.example.test:8000/v1",
                "models": {
                    "served-model": {
                        "pricing": {
                            "input_cost_per_million": "2",
                            "output_cost_per_million": "10",
                            "cache_read_cost_per_million": "0.20",
                            "cache_write_cost_per_million": "2",
                        }
                    }
                },
            }
        }
    }
    (get_hermes_home() / "config.yaml").write_text(yaml.safe_dump(config))
    usage = CanonicalUsage(input_tokens=1000, output_tokens=100, cache_read_tokens=500)
    result = estimate_usage_cost("served-model", usage, provider="custom",
                                base_url="http://inference.example.test:8000/v1")
    assert result.status == "estimated"
    assert result.source == "user_override"
    assert result.amount_usd == Decimal("0.0031")
    for model, base in [
        ("other-model", "http://inference.example.test:8000/v1"),
        ("served-model", "http://inference.example.test:9000/v1"),
        ("served-model", "http://inference.example.test:8000/other"),
    ]:
        result = estimate_usage_cost(model, usage, provider="custom", base_url=base)
        assert result.status == "unknown"


@pytest.mark.parametrize("rate", ["NaN", "Infinity", "-1", True, {}, "not-a-rate", "1e999999"])
def test_invalid_rates_do_not_create_estimates(monkeypatch, rate):
    monkeypatch.setattr("agent.usage_pricing.fetch_endpoint_model_metadata", lambda *a, **k: {})
    config = {"providers": {"internal": {
        "base_url": "http://inference.example.test/v1",
        "models": {"served-model": {"pricing": {
            "input_cost_per_million": rate, "output_cost_per_million": 10,
        }}},
    }}}
    (get_hermes_home() / "config.yaml").write_text(yaml.safe_dump(config))
    result = estimate_usage_cost("served-model", CanonicalUsage(input_tokens=1),
                                provider="custom", base_url="http://inference.example.test/v1")
    assert result.status == "unknown"


def test_profile_binding_keeps_reference_rates_separate(monkeypatch, tmp_path):
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    monkeypatch.setattr("agent.usage_pricing.fetch_endpoint_model_metadata", lambda *a, **k: {})
    endpoint = "http://inference.example.test/v1"
    for index, rate in enumerate([2, 7]):
        home = tmp_path / str(index)
        home.mkdir()
        config = {"providers": {"internal": {"base_url": endpoint, "models": {
            "served-model": {"pricing": {"input_cost_per_million": rate, "output_cost_per_million": 10}}
        }}}}
        (home / "config.yaml").write_text(yaml.safe_dump(config))
        token = set_hermes_home_override(home)
        try:
            result = estimate_usage_cost("served-model", CanonicalUsage(input_tokens=1000000),
                                        provider="custom", base_url=endpoint)
            assert result.amount_usd == Decimal(rate)
        finally:
            reset_hermes_home_override(token)


@pytest.mark.parametrize("url_key", ["api", "url", "base_url"])
def test_reference_match_uses_runtime_url_alias_and_model_forms(url_key):
    from agent.usage_pricing_config import configured_pricing_entry
    entry = {url_key: "http://INFERENCE.example.test:80/v1/",
             "models": [{"id":"served-model", "pricing":{
                 "input_cost_per_million":2, "output_cost_per_million":10}}]}
    if url_key != "base_url":
        entry["base_url"] = "http://wrong.example.test/v1"
    (get_hermes_home()/"config.yaml").write_text(yaml.safe_dump({"providers":{"internal":entry}}))
    assert configured_pricing_entry("served-model", "custom", "http://inference.example.test/v1")
    if url_key != "base_url":
        assert configured_pricing_entry("served-model", "custom", "http://wrong.example.test/v1") is None


@pytest.mark.parametrize("enabled", [False, "false", "no", "0"])
def test_disabled_provider_has_no_reference_price(enabled):
    from agent.usage_pricing_config import configured_pricing_entry
    entry = {"enabled":enabled, "base_url":"http://inference.example.test/v1",
             "models":{"served-model":{"pricing":{
                 "input_cost_per_million":2, "output_cost_per_million":10}}}}
    (get_hermes_home()/"config.yaml").write_text(yaml.safe_dump({"providers":{"internal":entry}}))
    assert configured_pricing_entry("served-model", "custom", entry["base_url"]) is None


def test_official_route_does_not_consult_configured_reference_prices(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("official pricing must not consult custom reference config")
    monkeypatch.setattr("agent.usage_pricing_config.configured_pricing_entry", unexpected)
    monkeypatch.setattr("agent.usage_pricing.fetch_endpoint_model_metadata", unexpected)
    monkeypatch.setattr("agent.usage_pricing._models_dev_pricing_entry", unexpected)
    from agent.usage_pricing import get_pricing_entry
    result = get_pricing_entry("gpt-4o", provider="openai", base_url="https://api.openai.com/v1")
    assert result is not None and result.source == "official_docs_snapshot"


def test_ambiguity_named_identity_and_missing_cache_rate(monkeypatch):
    from agent.usage_pricing_config import configured_pricing_entry
    monkeypatch.setattr("agent.usage_pricing.fetch_endpoint_model_metadata", lambda *a, **k: {})
    endpoint = "http://inference.example.test/v1"
    entry = {"base_url":endpoint, "models":{"served-model":{"pricing":{
        "input_cost_per_million":2,"output_cost_per_million":10}}}}
    (get_hermes_home()/"config.yaml").write_text(yaml.safe_dump({"providers":{"a":entry,"b":entry}}))
    assert configured_pricing_entry("served-model","custom",endpoint) is None
    for identity in ("a","custom:a"):
        assert configured_pricing_entry("served-model",identity,endpoint)
    assert configured_pricing_entry("served-model","wrong",endpoint) is None
    result = estimate_usage_cost("served-model",CanonicalUsage(cache_read_tokens=1),provider="custom:a",base_url=endpoint)
    assert result.status == "unknown"


@pytest.mark.parametrize("key", ["deepseek", "bedrock"])
def test_builtin_provider_key_cannot_supply_custom_reference_prices(key):
    from agent.usage_pricing_config import configured_pricing_entry
    endpoint = "https://api.deepseek.com/v1"
    entry = {"base_url": endpoint, "models": {"served-model": {"pricing": {
        "input_cost_per_million": 2, "output_cost_per_million": 10}}}}
    (get_hermes_home() / "config.yaml").write_text(yaml.safe_dump({"providers": {key: entry}}))
    for identity in (key, f"custom:{key}", "custom"):
        assert configured_pricing_entry("served-model", identity, endpoint) is None


def test_reference_scan_skips_unrelated_and_reserved_keys(monkeypatch):
    from agent.usage_pricing_config import configured_pricing_entry
    endpoint = "http://inference.example.test/v1"
    entry = {"base_url": endpoint, "models": {"served-model": {"pricing": {
        "input_cost_per_million": 2, "output_cost_per_million": 10}}}}
    config = {"providers": {"auto": entry, "": entry,
                           "unrelated": {**entry, "base_url": "http://other.example.test/v1"},
                           "internal": entry}}
    (get_hermes_home() / "config.yaml").write_text(yaml.safe_dump(config))
    checked = []
    def shadow(key):
        checked.append(key)
        assert key == "internal"
        return False
    monkeypatch.setattr("hermes_cli.runtime_provider_custom._shadowed_by_builtin", shadow)
    assert configured_pricing_entry("served-model", "custom", endpoint)
    assert checked == ["internal"]


def test_provider_scan_exception_does_not_break_accounting(monkeypatch):
    from agent.usage_pricing_config import configured_pricing_entry
    endpoint = "http://inference.example.test/v1"
    entry = {"base_url": endpoint, "models": {"served-model": {"pricing": {
        "input_cost_per_million": 2, "output_cost_per_million": 10}}}}
    (get_hermes_home() / "config.yaml").write_text(yaml.safe_dump({"providers": {"internal": entry}}))
    def unavailable(*args, **kwargs):
        raise RuntimeError("test: provider registry unavailable")
    monkeypatch.setattr("hermes_cli.runtime_provider_custom._shadowed_by_builtin", unavailable)
    assert configured_pricing_entry("served-model", "custom", endpoint) is None


def test_config_read_failure_does_not_break_pricing(monkeypatch):
    from agent.usage_pricing_config import configured_pricing_entry
    def unavailable():
        raise OSError("test: profile unavailable")
    monkeypatch.setattr("hermes_cli.config.load_config_readonly",unavailable)
    assert configured_pricing_entry("served-model","custom","http://inference.example.test/v1") is None
