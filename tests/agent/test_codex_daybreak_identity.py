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
CATALOG = [{"slug": slug, "context_window": 272000,
            "available_access_programs": {"cyber": ["standard", "daybreak_blue"]}}
           for slug in ("gpt-6-sol", "gpt-5.6-sol")]  # the second is native-compaction eligible


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


def _agent(daybreak, model="gpt-6-sol", transport=None):
    transport = transport or ResponsesApiTransport()
    return SimpleNamespace(
        provider="openai-codex", api_mode="codex_responses", base_url=BASE, api_key=_token(),
        model=model, daybreak=daybreak, request_overrides={}, session_id="s1", max_tokens=None,
        text_verbosity=None, log_prefix="", tools=[], codex_responses_native_compaction=True,
        _get_transport=lambda: transport,
        _prepare_messages_for_non_vision_model=lambda messages: messages,
        _resolved_api_call_timeout=lambda: 30,
        _endpoint_reasoning_payload=lambda: None,
    )


def _build(daybreak, model="gpt-6-sol", messages=None):
    """One request through the production builder; returns (kwargs, transport)."""
    agent = _agent(daybreak, model)
    kwargs = helpers._build_codex_kwargs(
        agent, messages or [{"role": "user", "content": "hello"}], [], None,
        effective_request_overrides(agent), "s1")
    return kwargs, agent._get_transport()


def _history_after_a_turn(daybreak, model="gpt-6-sol"):
    """A session's history after one real turn in the given mode: the transport that built the
    request normalizes the provider's answer, which stamps the encrypted reasoning item."""
    _, transport = _build(daybreak, model)
    answer = transport.normalize_response(SimpleNamespace(status="completed", usage=None, output=[
        SimpleNamespace(type="reasoning", id="rs_a", encrypted_content="sealed-blob", summary=[]),
        SimpleNamespace(type="message", role="assistant", status="completed", id="msg_a",
                        content=[SimpleNamespace(type="output_text", text="done")]),
    ]))
    return [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "done",
         "codex_reasoning_items": answer.provider_data["codex_reasoning_items"]},
        {"role": "user", "content": "next"},
    ]


def _blobs(items):
    return [i["encrypted_content"] for i in items if i.get("type") == "reasoning"]


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


@pytest.mark.parametrize("minted_with_switch", [True, False])
def test_reasoning_minted_in_one_mode_is_replayed_only_in_that_mode(minted_with_switch):
    history = _history_after_a_turn(daybreak=minted_with_switch)
    same, _ = _build(daybreak=minted_with_switch, messages=history)
    other, _ = _build(daybreak=not minted_with_switch, messages=history)
    assert _blobs(same["input"]) == ["sealed-blob"]
    assert _blobs(other["input"]) == []


@pytest.mark.parametrize("daybreak", [True, False])
def test_compaction_precheck_sees_the_same_items_the_request_sends(daybreak):
    """The native-compaction pre-check rebuilds the wire items itself; it must name the same
    identity as the transport, or it counts (or drops) items the real request does not."""
    from agent.codex_responses_adapter import _native_responses_replay_items

    model = "gpt-5.6-sol"
    history = _history_after_a_turn(daybreak, model)
    sent, _ = _build(daybreak, model, messages=history)
    assert sent.get("context_management"), "fixture must be native-compaction eligible"
    assert _blobs(sent["input"]) == ["sealed-blob"]
    assert _blobs(_native_responses_replay_items(_agent(daybreak, model), history)) == ["sealed-blob"]
    assert _blobs(_native_responses_replay_items(_agent(not daybreak, model), history)) == []
