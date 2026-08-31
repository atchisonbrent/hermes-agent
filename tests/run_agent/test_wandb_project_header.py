"""Regression tests for the fork's mandatory W&B project attribution."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.auxiliary_client import (
    _apply_wandb_project_header,
    _create_openai_client,
    _to_async_client,
)
from run_agent import AIAgent

WANDB_URL = "https://api.inference.wandb.ai/v1"
EXPECTED = "cw-wb/storage"


@patch("run_agent.OpenAI")
def test_main_wandb_client_always_has_project_header(mock_openai):
    mock_openai.return_value = MagicMock()
    with patch("hermes_cli.config.load_config", return_value={}):
        agent = AIAgent(
            api_key="synthetic-wandb-key",
            base_url=WANDB_URL,
            model="test-model",
            provider="custom",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )

    assert agent._client_kwargs["default_headers"]["OpenAI-Project"] == EXPECTED


@patch("agent.auxiliary_client.OpenAI")
def test_sync_auxiliary_wandb_client_always_has_project_header(mock_openai):
    mock_openai.return_value = MagicMock()
    with patch("agent.auxiliary_client._openai_http_client_kwargs", return_value={}):
        _create_openai_client(
            api_key="synthetic-wandb-key",
            base_url=WANDB_URL,
            default_headers={
                "X-Existing": "preserved",
                "openai-project": "wrong-project",
            },
        )

    headers = mock_openai.call_args.kwargs["default_headers"]
    assert headers["OpenAI-Project"] == EXPECTED
    assert headers["X-Existing"] == "preserved"
    assert "openai-project" not in headers


@patch("openai.AsyncOpenAI")
def test_async_auxiliary_wandb_client_always_has_project_header(mock_async):
    sync_client = SimpleNamespace(
        api_key="synthetic-wandb-key",
        base_url=WANDB_URL,
    )
    with patch("agent.auxiliary_client._openai_http_client_kwargs", return_value={}):
        _to_async_client(sync_client, "test-model")

    assert mock_async.call_args.kwargs["default_headers"]["OpenAI-Project"] == EXPECTED


def test_non_wandb_client_headers_are_untouched():
    kwargs = {"default_headers": {"X-Existing": "preserved"}}
    _apply_wandb_project_header(kwargs, "https://api.openai.com/v1")
    assert kwargs == {"default_headers": {"X-Existing": "preserved"}}

    subdomain_kwargs = {"default_headers": {"X-Existing": "preserved"}}
    _apply_wandb_project_header(
        subdomain_kwargs,
        "https://staging.api.inference.wandb.ai/v1",
    )
    assert subdomain_kwargs == {"default_headers": {"X-Existing": "preserved"}}
