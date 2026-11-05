"""Opt-in, profile-local reference rates for named OpenAI-compatible endpoints."""
from decimal import Decimal, InvalidOperation


_RATE_FIELDS = (
    "input_cost_per_million", "output_cost_per_million",
    "cache_read_cost_per_million", "cache_write_cost_per_million",
)


def configured_pricing_entry(model_name, provider, base_url):
    """Keep optional pricing failures from interrupting a completed model turn."""
    try:
        return _configured_pricing_entry(model_name, provider, base_url)
    except Exception:
        import logging
        logging.getLogger(__name__).debug("Ignoring unavailable configured reference pricing")
        return None


def _configured_pricing_entry(model_name, provider, base_url):
    """Match the exact endpoint/model, including runtime's generic ``custom`` identity.

    These are user estimates, never evidence of an invoice or a free entitlement.
    No process-global cache: multiplexed callers must read their bound profile.
    """
    from agent.usage_pricing import PricingEntry
    from hermes_cli.config import load_config_readonly
    from hermes_cli.config_providers import _normalize_provider_models, is_provider_enabled
    from hermes_cli.route_identity import normalize_route_base_url
    from hermes_cli.runtime_provider_custom import _entry_url, _shadowed_by_builtin

    if not base_url:
        return None
    try:
        providers = load_config_readonly().get("providers", {})
    except Exception:
        return None
    if not isinstance(providers, dict):
        return None
    matches = []
    for key, entry in providers.items():
        if str(key).strip().lower() in {"", "auto"}:
            continue
        if not isinstance(entry, dict) or not is_provider_enabled(entry):
            continue
        if (provider or "").lower() not in {"custom", str(key).lower(), f"custom:{key}".lower()}:
            continue
        if normalize_route_base_url(_entry_url(entry)) != normalize_route_base_url(base_url):
            continue
        models, _ = _normalize_provider_models(entry.get("models", {}))
        model = models.get(model_name)
        if isinstance(model, dict) and "pricing" in model:
            if _shadowed_by_builtin(str(key).strip().lower()):
                continue
            matches.append(model["pricing"])
    # Two named providers sharing an endpoint cannot choose each other's contract.
    if len(matches) != 1 or not isinstance(matches[0], dict):
        return None
    spec = matches[0]
    rates = {}
    for field in _RATE_FIELDS:
        value = spec.get(field)
        if value is None:
            rates[field] = None
            continue
        try:
            rate = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        if not rate.is_finite() or not Decimal(0) <= rate <= Decimal(1000000):
            return None
        rates[field] = rate
    if rates["input_cost_per_million"] is None or rates["output_cost_per_million"] is None:
        return None
    return PricingEntry(**rates, source="user_override", pricing_version="configured-reference-v1")
