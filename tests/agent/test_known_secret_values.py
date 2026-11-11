"""Exact-value redaction of the secrets the process itself loaded (agent/known_secret_values.py).

Every value here is synthetic. The registry is per profile home, so each test registers under the
temporary HERMES_HOME the test runner isolates.
"""

from __future__ import annotations

import base64
import json
import random
import shlex
import string
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

import pytest

from agent import known_secret_values as ksv
from agent.redact import redact_sensitive_text
from hermes_constants import get_hermes_home, reset_hermes_home_override, set_hermes_home_override

MARK = "«redacted-secret:{}»"


@pytest.fixture(autouse=True)
def _empty_registry():
    ksv.clear_known_secrets()
    yield
    ksv.clear_known_secrets()


def _terminal_result(command: str) -> str:
    """Run *command* in a real local shell and finalize it the way the terminal tool does."""
    from tools.environments.local import LocalEnvironment
    from tools.terminal_tool_result import finalize_foreground_result
    env = LocalEnvironment(cwd=str(get_hermes_home()), timeout=30)
    try:
        raw = env.execute(command)
    finally:
        env.cleanup()
    assert raw["returncode"] == 0, raw
    return json.loads(finalize_foreground_result(
        command=command, result=raw, env=env, env_type="local", effective_task_id="t", task_id="t",
        session_id="s", session_key="k", workdir=None, command_cwd=None, approval_note=None))["output"]


def _python_command(code: str, *args: str) -> str:
    return shlex.join([Path(sys.executable).as_posix(), "-c", code, *args])


@pytest.fixture
def synthetic_source(monkeypatch):
    """A bulk secret source registered for this test only (no bundled sources)."""
    from agent.secret_sources import registry as reg
    from agent.secret_sources.base import FetchResult, SecretSource

    reg._reset_registry_for_tests()
    monkeypatch.setattr(reg, "_ensure_builtin_sources", lambda: None)
    supplied: dict[str, str] = {}

    class _Synthetic(SecretSource):
        name, label, shape = "synthetic", "Synthetic", "bulk"
        token_env_key, default_token_env = "access_token_env", "SYNTHETIC_SOURCE_TOKEN"

        def fetch(self, cfg, home_path):
            return FetchResult(secrets=dict(supplied))

    reg.register_source(_Synthetic())
    yield supplied
    reg._reset_registry_for_tests()


def _apply(environ: dict | None = None) -> None:
    from agent.secret_sources.registry import apply_all
    apply_all({"synthetic": {"enabled": True}}, get_hermes_home(), environ={} if environ is None else environ)


def test_source_value_in_a_json_listing_is_masked_in_a_terminal_result(synthetic_source):
    value = "q7Rk2vLp9XwZ3mTn8cHd"  # no vendor prefix: no pattern recognises it
    synthetic_source["SERVICE_SIGNING_TOKEN"] = value
    _apply()
    secret_file = get_hermes_home() / "listing-input.txt"
    secret_file.write_text(value, encoding="utf-8")
    # The shape of a secrets-CLI listing; the value is read from a file, so it is not in the command.
    code = ("import json,sys; print(json.dumps([{'id': 'x', 'key': 'SERVICE_SIGNING_TOKEN', "
            "'value': open(sys.argv[1]).read()}], indent=2))")
    output = _terminal_result(_python_command(code, str(secret_file)))
    assert value not in output
    assert MARK.format("SERVICE_SIGNING_TOKEN") in output


def test_source_access_token_is_registered(synthetic_source):
    _apply({"SYNTHETIC_SOURCE_TOKEN": "0.synthetic-bootstrap-credential"})
    assert redact_sensitive_text("token 0.synthetic-bootstrap-credential") == \
        "token " + MARK.format("SYNTHETIC_SOURCE_TOKEN")


def test_encoded_forms_are_masked():
    value = 'synthetic/secret+value=with "quote" é~?'
    ksv.register_known_secrets(None, {"SERVICE_PASSWORD": value})
    raw = value.encode("utf-8")
    forms = {
        "json": json.dumps(value)[1:-1],
        "url": quote(value, safe=""),
        "base64": base64.b64encode(raw).decode(),
        "base64url": base64.urlsafe_b64encode(raw).decode(),
        # `echo "$X" | base64` encodes a trailing newline: the whole-group prefix still matches.
        "base64-newline": base64.b64encode(raw + b"\n").decode(),
    }
    assert forms["base64"] != forms["base64url"]
    for label, form in forms.items():
        out = redact_sensitive_text(f"<{form}>")
        assert form not in out, label
        assert MARK.format("SERVICE_PASSWORD") in out, label


def test_longer_value_containing_a_shorter_one_is_masked_whole():
    inner = "synthetic-inner-value"
    outers = {"PREFIXED_TOKEN": inner + "-extended", "WRAPPED_TOKEN": "prefix-" + inner + "-suffix"}
    ksv.register_known_secrets(None, {"INNER_TOKEN": inner})  # registered first on purpose
    ksv.register_known_secrets(None, outers)
    text = " | ".join([*outers.values(), inner])
    assert redact_sensitive_text(text) == " | ".join(MARK.format(n) for n in [*outers, "INNER_TOKEN"])


def test_non_secret_suffix_and_config_exempt_keys_are_not_registered(synthetic_source):
    (get_hermes_home() / "config.yaml").write_text(
        "security:\n  known_secret_exempt_keys: [deploy-label]\n", encoding="utf-8")
    synthetic_source.update({
        "SERVICE_URL": "https://service.example.invalid/api",
        "db-host": "database.example.invalid",
        "Deployment_Model": "synthetic-model-name",
        "DEPLOY_LABEL": "synthetic-release-label",
        "SUPPORT_TOKEN": "synthetic-support-value",  # ``PORT`` only as a whole word
    })
    _apply()
    text = " ".join(synthetic_source.values())
    assert redact_sensitive_text(text) == text.replace("synthetic-support-value", MARK.format("SUPPORT_TOKEN"))


def test_short_value_is_not_registered_and_its_name_is_reported(synthetic_source, caplog):
    synthetic_source.update({"SERVICE_PIN": "4821", "SERVICE_TOKEN": "synthetic-long-value"})
    _apply()
    assert redact_sensitive_text("pin 4821") == "pin 4821"
    assert ksv.uncovered_names() == ["SERVICE_PIN"]
    with caplog.at_level("INFO", logger=ksv.__name__):
        ksv.log_uncovered_names(get_hermes_home())
        ksv.log_uncovered_names(get_hermes_home())
    lines = [r.getMessage() for r in caplog.records if r.name == ksv.__name__]
    assert len(lines) == 1 and "SERVICE_PIN" in lines[0] and "4821" not in lines[0]


def test_bitwarden_entries_skipped_as_env_vars_are_still_masked(monkeypatch):
    from agent.secret_sources import bitwarden as bw
    listing = [{"key": "SYNTH_API_KEY", "value": "synthetic-exported-value"},
               {"key": "service.signing-key", "value": "synthetic-unexported-value"}]
    monkeypatch.setattr(bw, "run_cli", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, stdout=json.dumps(listing), stderr=""))
    secrets, _warnings = bw._run_bws_list(Path("bws"), "synthetic-access", "project", "", get_hermes_home())
    assert secrets == {"SYNTH_API_KEY": "synthetic-exported-value"}
    assert redact_sensitive_text("x synthetic-unexported-value") == "x " + MARK.format("service.signing-key")


def test_registries_are_per_profile_home(tmp_path):
    other = tmp_path / "other-profile"
    other.mkdir()
    ksv.register_known_secrets(other, {"OTHER_TOKEN": "synthetic-other-profile-value"})
    assert redact_sensitive_text("synthetic-other-profile-value") == "synthetic-other-profile-value"
    token = set_hermes_home_override(other)
    try:
        assert redact_sensitive_text("synthetic-other-profile-value") == MARK.format("OTHER_TOKEN")
    finally:
        reset_hermes_home_override(token)


def test_unmatched_text_is_returned_unchanged_and_cheaply():
    rnd = random.Random(7)
    alphabet = string.ascii_letters + string.digits
    ksv.register_known_secrets(None, {
        f"SYNTH_{i}_TOKEN": "".join(rnd.choice(alphabet) for _ in range(rnd.randint(16, 64))) for i in range(300)})
    text = "".join(rnd.choice(alphabet + ' \n{}":,') for _ in range(100_000))
    start = time.perf_counter()
    out = ksv.redact_known_secret_values(text)
    elapsed = time.perf_counter() - start
    assert out is text
    assert elapsed < 2.0  # one regex pass; ~20 ms on a laptop for this input


class TestDotenvValues:
    TOKEN, SETTING = "synthetic-dotenv-credential", "synthetic-display-setting"

    @pytest.fixture
    def loaded(self, monkeypatch):
        from hermes_cli import env_loader
        home = get_hermes_home()
        home.mkdir(parents=True, exist_ok=True)
        (home / ".env").write_text(
            f"SYNTH_SERVICE_TOKEN={self.TOKEN}\nSYNTH_DISPLAY_LABEL={self.SETTING}\n", encoding="utf-8")
        for name in ("SYNTH_SERVICE_TOKEN", "SYNTH_DISPLAY_LABEL"):
            monkeypatch.setenv(name, "")  # restored (removed) after the test
        env_loader.reset_secret_source_cache()
        env_loader.load_hermes_dotenv(hermes_home=home)

    def test_secret_named_value_is_masked_in_a_non_env_dump_command(self, loaded):
        output = _terminal_result(_python_command(
            "import os; print(os.environ['SYNTH_SERVICE_TOKEN'], os.environ['SYNTH_DISPLAY_LABEL'])"))
        assert output == f"{MARK.format('SYNTH_SERVICE_TOKEN')} {self.SETTING}"
