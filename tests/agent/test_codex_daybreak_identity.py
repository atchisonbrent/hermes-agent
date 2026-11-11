"""Fork: the session Daybreak switch is part of a request's reasoning and cache identity, and the
production request builder is what passes it to the transport (no live accounts)."""
import base64
import json
from types import SimpleNamespace

import pytest

from agent import chat_completion_helpers as helpers
from agent import codex_service_tiers as tiers
from agent import model_metadata as mm
from agent.fast_mode import effective_request_overrides
from agent.transports.codex import ResponsesApiTransport

BASE = "https://chatgpt.com/backend-api/codex"
CATALOG = [{"slug": "gpt-6-sol", "context_window": 272000,
            "available_access_programs": {"cyber": ["standard", "daybreak_blue"]}}]


def _token():
    payload = {"https://api.openai.com/auth": {"chatgpt_account_id": "A"}}
    return "test." + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=") + ".test"


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    monkeypatch.setattr(mm, "_codex_oauth_context_cache", {})
    monkeypatch.setattr(tiers, "_catalogs", {})
    monkeypatch.setattr(
        mm.model_metadata_http, "get",
        lambda url, **kwargs: SimpleNamespace(status_code=200, json=lambda: {"models": CATALOG}))


def _build(daybreak, model="gpt-6-sol"):
    """One request through the production builder; returns (kwargs, transport)."""
    transport = ResponsesApiTransport()
    agent = SimpleNamespace(
        provider="openai-codex", api_mode="codex_responses", base_url=BASE, api_key=_token(),
        model=model, daybreak=daybreak, request_overrides={}, session_id="s1", max_tokens=None,
        text_verbosity=None, log_prefix="", tools=[],
        _get_transport=lambda: transport,
        _prepare_messages_for_non_vision_model=lambda messages: messages,
        _resolved_api_call_timeout=lambda: 30,
        _endpoint_reasoning_payload=lambda: None,
    )
    kwargs = helpers._build_codex_kwargs(
        agent, [{"role": "user", "content": "hello"}], [], None, effective_request_overrides(agent), "s1")
    return kwargs, transport


def test_production_builder_carries_the_switch_to_the_wire():
    kwargs, _ = _build(daybreak=True)
    assert kwargs["extra_body"]["access_programs"] == {"cyber": "daybreak_blue"}
    kwargs, _ = _build(daybreak=False)
    assert "access_programs" not in (kwargs.get("extra_body") or {})


def test_switch_changes_reasoning_identity_so_blobs_do_not_cross_modes():
    _, on = _build(daybreak=True)
    _, off = _build(daybreak=False)
    assert off._last_issuer_model == "gpt-6-sol"
    assert on._last_issuer_model == "gpt-6-sol#access_program=daybreak_blue"
    # The switch and the explicit picker route name the same domain.
    _, explicit = _build(daybreak=False, model="gpt-6-sol-daybreak-blue")
    assert explicit._last_issuer_model == on._last_issuer_model


def test_switch_changes_prompt_cache_routing():
    on, _ = _build(daybreak=True)
    off, _ = _build(daybreak=False)
    assert on["prompt_cache_key"] and off["prompt_cache_key"]
    assert on["prompt_cache_key"] != off["prompt_cache_key"]
