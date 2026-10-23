"""Codex Daybreak access-program routes stay explicit from picker to wire."""

from types import SimpleNamespace

import pytest

from agent import model_metadata
from agent.auxiliary_client import _CodexCompletionsAdapter, _build_codex_client, aux_probe_mode
from agent.codex_model_variants import (
    codex_access_program_for_model,
    strip_codex_access_program_suffix,
)
from agent.codex_runtime import _codex_wire_model, run_codex_app_server_turn
from agent.codex_responses_adapter import _reasoning_model_identity
from agent.reasoning_effort import CODEX_ASTRA_EFFORTS, codex_supported_efforts, is_astra_model
from agent.transports.codex import ResponsesApiTransport


CODEX_BASE = "https://chatgpt.com/backend-api/codex"


def _request(model: str) -> dict:
    transport = ResponsesApiTransport()
    return transport.build_kwargs(
        model,
        [{"role": "user", "content": "hi"}],
        provider="openai-codex",
        base_url=CODEX_BASE,
        is_codex_backend=True,
    )


def test_daybreak_context_route_sends_base_model_and_access_program():
    request = _request("gpt-6-sol-900k-daybreak-blue")

    assert request["model"] == "gpt-6-sol"
    assert request["extra_body"]["access_programs"] == {"cyber": "daybreak_blue"}


def test_standard_route_does_not_enable_daybreak():
    request = _request("gpt-6-sol-900k")

    assert request["model"] == "gpt-6-sol"
    assert "access_programs" not in request.get("extra_body", {})


def test_standard_route_cannot_enable_daybreak_through_extra_body_override():
    transport = ResponsesApiTransport()
    request = transport.build_kwargs(
        "gpt-6-sol",
        [{"role": "user", "content": "hi"}],
        provider="openai-codex",
        base_url=CODEX_BASE,
        is_codex_backend=True,
        request_overrides={"extra_body": {
            "metadata": {"kept": True},
            "access_programs": {"cyber": "daybreak_blue", "other": "kept"},
        }},
    )

    assert request["extra_body"] == {
        "metadata": {"kept": True},
        "access_programs": {"other": "kept"},
    }

    only_cyber = transport.build_kwargs(
        "gpt-6-sol",
        [{"role": "user", "content": "hi"}],
        provider="openai-codex",
        base_url=CODEX_BASE,
        is_codex_backend=True,
        request_overrides={"extra_body": {"access_programs": {"cyber": " Daybreak_Blue "}}},
    )
    assert "extra_body" not in only_cyber or "access_programs" not in only_cyber["extra_body"]


def test_standard_and_daybreak_routes_do_not_share_opaque_state_identity():
    standard = _request("gpt-6-sol")
    daybreak = _request("gpt-6-sol-daybreak-blue")

    assert _reasoning_model_identity("gpt-6-sol") == "gpt-6-sol"
    assert _reasoning_model_identity("gpt-6-sol-daybreak-blue") == (
        "gpt-6-sol#access_program=daybreak_blue"
    )
    assert standard["prompt_cache_key"] != daybreak["prompt_cache_key"]


def test_daybreak_route_preserves_other_extra_body_fields():
    transport = ResponsesApiTransport()
    request = transport.build_kwargs(
        "gpt-6-luna-daybreak-blue",
        [{"role": "user", "content": "hi"}],
        provider="openai-codex",
        base_url=CODEX_BASE,
        is_codex_backend=True,
        request_overrides={"extra_body": {"metadata": {"owner": "test"}}},
    )

    assert request["extra_body"] == {
        "metadata": {"owner": "test"},
        "access_programs": {"cyber": "daybreak_blue"},
    }


def test_daybreak_route_owns_cyber_program_but_preserves_other_programs():
    transport = ResponsesApiTransport()
    request = transport.build_kwargs(
        "gpt-6-luna-daybreak-blue",
        [{"role": "user", "content": "hi"}],
        provider="openai-codex",
        base_url=CODEX_BASE,
        is_codex_backend=True,
        request_overrides={"extra_body": {
            "access_programs": {"cyber": "standard", "other": "kept"},
        }},
    )

    assert request["extra_body"]["access_programs"] == {
        "cyber": "daybreak_blue",
        "other": "kept",
    }


def test_model_override_cannot_silently_downgrade_daybreak_route():
    transport = ResponsesApiTransport()
    with pytest.raises(ValueError, match="silently downgrade"):
        transport.build_kwargs(
            "gpt-6-sol-daybreak-blue",
            [{"role": "user", "content": "hi"}],
            provider="openai-codex",
            base_url=CODEX_BASE,
            is_codex_backend=True,
            request_overrides={"model": "gpt-6-luna"},
        )


def test_daybreak_context_route_keeps_900k_context_contract():
    model = "openai/gpt-6-sol-900k-daybreak-blue"

    assert codex_access_program_for_model(model) == "daybreak_blue"
    assert model_metadata.is_codex_context_variant(model)
    assert model_metadata.strip_codex_context_variant_suffix(model) == "openai/gpt-6-sol"
    assert model_metadata._verified_codex_ctx_for_slug(model) == 900_000


def test_daybreak_route_fails_closed_on_non_codex_responses_backend():
    transport = ResponsesApiTransport()
    with pytest.raises(ValueError, match="Daybreak Blue"):
        transport.build_kwargs(
            "gpt-6-sol-daybreak-blue",
            [{"role": "user", "content": "hi"}],
            provider="openai",
            base_url="https://api.openai.com/v1",
            is_codex_backend=False,
        )


def test_codex_app_server_rejects_daybreak_route_it_cannot_activate():
    agent = SimpleNamespace(model="gpt-6-sol-daybreak-blue", provider="openai-codex")
    with pytest.raises(ValueError, match="Daybreak Blue"):
        _codex_wire_model(agent, None)


def test_codex_app_server_rejects_daybreak_before_session_mutation(monkeypatch):
    sentinel_session = SimpleNamespace(close=lambda: (_ for _ in ()).throw(AssertionError("closed")))
    agent = SimpleNamespace(
        model="gpt-6-sol-daybreak-blue",
        provider="openai-codex",
        compression_checkpoint_required=False,
        _codex_session=sentinel_session,
    )
    monkeypatch.setattr(
        "agent.codex_runtime._ensure_codex_session",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("session mutated")),
    )

    result = run_codex_app_server_turn(
        agent,
        user_message="hi",
        original_user_message="hi",
        messages=[{"role": "user", "content": "hi"}],
        effective_task_id="test",
    )

    assert result["completed"] is False
    assert "Daybreak Blue" in result["error"]
    assert agent._codex_session is sentinel_session


def test_auxiliary_codex_request_keeps_daybreak_program():
    client = SimpleNamespace(base_url=CODEX_BASE)
    adapter = _CodexCompletionsAdapter(client, "gpt-6-sol-900k-daybreak-blue")

    request, selected_model, _timeout = adapter._build_responses_kwargs({
        "messages": [{"role": "user", "content": "summarize"}],
    })

    assert selected_model == "gpt-6-sol-900k-daybreak-blue"
    assert request["model"] == "gpt-6-sol"
    assert request["_issuer_model"] == "gpt-6-sol#access_program=daybreak_blue"
    assert request["extra_body"]["access_programs"] == {"cyber": "daybreak_blue"}


def test_auxiliary_codex_gateway_uses_effective_provider_identity():
    client = SimpleNamespace(
        base_url="https://gateway.example/codex",
        _hermes_aux_effective_provider="openai-codex",
    )
    adapter = _CodexCompletionsAdapter(client, "gpt-6-sol-daybreak-blue")

    request, _selected_model, _timeout = adapter._build_responses_kwargs({
        "messages": [{"role": "user", "content": "summarize"}],
    })

    assert request["extra_body"]["access_programs"] == {"cyber": "daybreak_blue"}


def test_codex_client_builder_tags_real_gateway_client(monkeypatch):
    real_client = SimpleNamespace(
        api_key="fixture", base_url="https://gateway.example/codex", close=lambda: None,
    )
    monkeypatch.setattr(
        "agent.auxiliary_client._resolve_codex_credential_and_base",
        lambda: ("fixture", "https://gateway.example/codex"),
    )
    monkeypatch.setattr("agent.auxiliary_client._create_openai_client", lambda **_kwargs: real_client)

    wrapped, model = _build_codex_client("gpt-6-sol-daybreak-blue")

    assert model == "gpt-6-sol-daybreak-blue"
    assert wrapped is not None
    assert wrapped._real_client is real_client
    assert real_client._hermes_aux_effective_provider == "openai-codex"


def test_codex_client_builder_probe_mode_does_not_require_dynamic_attributes(monkeypatch):
    monkeypatch.setattr(
        "agent.auxiliary_client._resolve_codex_credential_and_base",
        lambda: ("fixture", "https://gateway.example/codex"),
    )

    with aux_probe_mode():
        wrapped, model = _build_codex_client("gpt-6-sol")

    assert wrapped is not None
    assert model == "gpt-6-sol"


def test_daybreak_suffix_preserves_model_effort_identity():
    assert is_astra_model("gpt-6-astra-daybreak-blue")
    assert codex_supported_efforts("gpt-6-astra-daybreak-blue") == CODEX_ASTRA_EFFORTS
    assert (
        codex_supported_efforts("gpt-6.1-sol-900k-daybreak-blue")
        == codex_supported_efforts("gpt-6.1-sol-900k")
    )


@pytest.mark.parametrize("model", [
    "-daybreak-blue",
    "gpt-daybreak-blue",
    "gpt-daybreak-blue-daybreak-blue",
    "gpt-daybreak-blue-latest-daybreak-blue",
])
def test_invalid_or_legacy_daybreak_aliases_are_not_stripped(model):
    assert codex_access_program_for_model(model) is None
    assert strip_codex_access_program_suffix(model) == model
