"""A secret source's own access token never reaches a model-run command.

With ``BWS_ACCESS_TOKEN`` in its environment a terminal command can run ``bws secret list`` and
print every value in the store; the sources pass the token to their own CLI explicitly instead.
That holds for the bundled default names and for a name a source is configured with.
"""

import os

import pytest

from tests.tools._child_env_fixtures import child_env, observe_child
from tools.environments import local

UNRELATED = {"UNRELATED_SETTING": "kept-value"}


def _bundled_source_tokens() -> set[str]:
    from agent.secret_sources.registry import list_sources
    return {source.default_token_env for source in list_sources() if source.default_token_env}


def _execute_code_env() -> dict:
    # execute_code admits a non-allowlisted name only through env passthrough; try to register it.
    from tools.code_execution_env import _scrub_child_env
    from tools.env_passthrough import register_env_passthrough
    register_env_passthrough(sorted(os.environ))
    return _scrub_child_env(dict(os.environ))


BUILDERS = {
    "terminal": lambda: local._make_run_env({}),
    "background": lambda: local._sanitize_subprocess_env(dict(os.environ)),
    "hermes_subprocess_env": local.hermes_subprocess_env,
    "execute_code": _execute_code_env,
}


def _assert_stripped(builder: str, tokens: set[str]) -> None:
    observed = observe_child(BUILDERS[builder](), sorted(tokens | set(UNRELATED)))
    assert {k: v for k, v in observed.items() if v is not None} == UNRELATED


@pytest.mark.usefixtures("child_env")
@pytest.mark.parametrize("builder", sorted(BUILDERS))
def test_bundled_source_tokens_are_stripped(monkeypatch, builder):
    tokens = _bundled_source_tokens()
    assert "BWS_ACCESS_TOKEN" in tokens
    for name in tokens:
        monkeypatch.setenv(name, "synthetic-token-" + name.lower())
    monkeypatch.setenv(*next(iter(UNRELATED.items())))
    _assert_stripped(builder, tokens)


@pytest.fixture
def configured_source(monkeypatch):
    """A source configured with a custom token variable whose name no static list could know."""
    from agent.secret_sources import registry as reg
    from agent.secret_sources.base import FetchResult, SecretSource

    reg._reset_registry_for_tests()
    monkeypatch.setattr(reg, "_ensure_builtin_sources", lambda: None)
    monkeypatch.setattr(reg, "_TOKEN_ENV_NAMES", set())

    class _Configured(SecretSource):
        name, label, shape = "configured", "Configured", "bulk"
        token_env_key, default_token_env = "access_token_env", "CONFIGURED_DEFAULT_TOKEN"

        def fetch(self, cfg, home_path):
            return FetchResult()

    reg.register_source(_Configured())
    from hermes_constants import get_hermes_home
    reg.apply_all({"configured": {"enabled": True, "access_token_env": "PROJECT_BOOTSTRAP"}}, get_hermes_home(), environ={})
    yield "PROJECT_BOOTSTRAP"
    reg._reset_registry_for_tests()


@pytest.mark.usefixtures("child_env")
@pytest.mark.parametrize("builder", sorted(BUILDERS))
def test_configured_source_token_name_is_stripped(monkeypatch, configured_source, builder):
    monkeypatch.setenv(configured_source, "synthetic-configured-token")
    monkeypatch.setenv(*next(iter(UNRELATED.items())))
    _assert_stripped(builder, {configured_source})


def _assert_passthrough_refused(tokens: set[str]) -> None:
    from tools.env_passthrough import is_env_passthrough, register_env_passthrough
    register_env_passthrough(sorted(tokens))
    assert not any(is_env_passthrough(name) for name in tokens)


@pytest.mark.usefixtures("child_env")
def test_bundled_source_tokens_cannot_be_registered_for_passthrough():
    _assert_passthrough_refused(_bundled_source_tokens())


@pytest.mark.usefixtures("child_env")
def test_configured_source_token_cannot_be_registered_for_passthrough(configured_source):
    _assert_passthrough_refused({configured_source})
