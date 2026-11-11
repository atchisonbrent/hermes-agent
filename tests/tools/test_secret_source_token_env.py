"""A secret source's own access token never reaches a model-run command.

With ``BWS_ACCESS_TOKEN`` in its environment a terminal command can run ``bws secret list`` and
print every value in the store; the sources pass the token to their own CLI explicitly instead.
"""

import os

import pytest

from tests.tools._child_env_fixtures import child_env, observe_child
from tools.environments import local


def _bundled_source_tokens() -> set[str]:
    from agent.secret_sources.registry import list_sources
    return {source.default_token_env for source in list_sources() if source.default_token_env}


@pytest.mark.usefixtures("child_env")
@pytest.mark.parametrize("builder", ["foreground", "background", "nonterminal"])
def test_source_token_is_stripped_and_unrelated_variable_survives(monkeypatch, builder):
    tokens = _bundled_source_tokens()
    assert "BWS_ACCESS_TOKEN" in tokens
    for name in tokens:
        monkeypatch.setenv(name, "synthetic-token-" + name.lower())
    monkeypatch.setenv("UNRELATED_SETTING", "kept-value")
    factories = {
        "foreground": lambda: local._make_run_env({}),
        "background": lambda: local._sanitize_subprocess_env(dict(os.environ)),
        "nonterminal": local.hermes_subprocess_env,
    }
    observed = observe_child(factories[builder](), sorted(tokens | {"UNRELATED_SETTING"}))
    assert observed == {**dict.fromkeys(tokens), "UNRELATED_SETTING": "kept-value"}


@pytest.mark.usefixtures("child_env")
def test_source_token_cannot_be_registered_for_passthrough():
    from tools.env_passthrough import is_env_passthrough, register_env_passthrough
    tokens = _bundled_source_tokens()
    register_env_passthrough(sorted(tokens))
    assert not any(is_env_passthrough(name) for name in tokens)
