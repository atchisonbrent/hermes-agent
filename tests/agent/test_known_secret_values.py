"""Exact-value redaction of the secrets the process itself loaded (agent/known_secret_values.py).

Every value here is synthetic. The registry is per profile home, so each test registers under the
temporary HERMES_HOME the test runner isolates.
"""

from __future__ import annotations

import base64
import json
import random
import re
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


def test_a_fetched_value_and_the_bootstrap_token_under_one_name_are_both_masked(synthetic_source):
    synthetic_source["SYNTHETIC_SOURCE_TOKEN"] = "synthetic-value-stored-in-the-source"
    _apply({"SYNTHETIC_SOURCE_TOKEN": "synthetic-bootstrap-token-value"})
    mark = MARK.format("SYNTHETIC_SOURCE_TOKEN")
    assert redact_sensitive_text("synthetic-value-stored-in-the-source synthetic-bootstrap-token-value") == \
        f"{mark} {mark}"


def test_a_source_whose_token_name_raises_still_registers_its_values(synthetic_source, monkeypatch, caplog):
    from agent.secret_sources.base import SecretSource

    def _broken(self, cfg):
        raise ValueError("synthetic malformed token config")

    monkeypatch.setattr(SecretSource, "token_env", _broken)
    synthetic_source["SERVICE_SIGNING_TOKEN"] = "synthetic-fetched-value"
    with caplog.at_level("WARNING"):
        _apply()
    assert redact_sensitive_text("synthetic-fetched-value") == MARK.format("SERVICE_SIGNING_TOKEN")
    assert any("synthetic" in r.getMessage() and "token variable" in r.getMessage() for r in caplog.records)


def test_a_config_backend_outage_is_unreadable_config_not_an_exit(monkeypatch, caplog):
    from hermes_cli import config_backend

    def _down(path):
        raise config_backend.ConfigBackendUnavailable("synthetic backend outage")

    monkeypatch.setattr(config_backend, "read_config_doc_readonly", _down)
    monkeypatch.setattr(ksv, "_config_unreadable_logged", False)
    with caplog.at_level("WARNING", logger=ksv.__name__):
        ksv.register_known_secrets(None, {"SERVICE_TOKEN": "synthetic-outage-value"})
        ksv.register_known_secrets(None, {"OTHER_TOKEN": "synthetic-second-value"})
    assert redact_sensitive_text("synthetic-outage-value") == MARK.format("SERVICE_TOKEN")
    assert [r.getMessage() for r in caplog.records if "key_env" in r.getMessage()] != []
    assert len([r for r in caplog.records if "config unreadable" in r.getMessage()]) == 1


def test_an_environment_that_changes_while_read_does_not_raise(caplog):
    from collections.abc import Mapping

    class _Vanishing(Mapping):  # the name is listed, then gone when its value is read
        def __iter__(self):
            return iter(["OPENROUTER_API_KEY"])

        def __len__(self):
            return 1

        def __getitem__(self, name):
            raise KeyError(name)

    with caplog.at_level("WARNING", logger=ksv.__name__):
        ksv.register_environment_credentials(get_hermes_home(), _Vanishing())
    assert any("not read" in r.getMessage() for r in caplog.records)


def test_encoded_forms_are_masked_whole():
    value = 'synthetic/secret+value=with "quote" é~?'
    ksv.register_known_secrets(None, {"SERVICE_PASSWORD": value})
    raw = value.encode("utf-8")
    std, url = base64.b64encode(raw).decode(), base64.urlsafe_b64encode(raw).decode()
    forms = {
        "json": json.dumps(value)[1:-1],
        "url": quote(value, safe=""),
        "url-lowercase-hex": re.sub(r"%[0-9A-F]{2}", lambda m: m.group(0).lower(), quote(value, safe="")),
        "base64": std, "base64-unpadded": std.rstrip("="),
        "base64url": url, "base64url-unpadded": url.rstrip("="),
    }
    assert std != url and std.endswith("=") and forms["url"] != forms["url-lowercase-hex"]
    for label, form in forms.items():
        assert redact_sensitive_text(f"<{form}>") == f"<{MARK.format('SERVICE_PASSWORD')}>", label
    # `echo "$X" | base64` encodes a trailing newline: all but the last (mixed) group is masked.
    piped = base64.b64encode(raw + b"\n").decode()
    out = redact_sensitive_text(piped)
    assert out.startswith(MARK.format("SERVICE_PASSWORD")) and piped.endswith(out[len(MARK.format("SERVICE_PASSWORD")):])
    assert len(out) - len(MARK.format("SERVICE_PASSWORD")) <= 4


def test_complete_encodings_of_a_short_value_are_masked_but_not_its_partial_prefix():
    ksv.register_known_secrets(None, {"SHORT_TOKEN": "q7Rk2vLp"})  # 8 characters: the shortest registrable
    full = base64.b64encode(b"q7Rk2vLp").decode()
    assert len(full) < ksv.MIN_DERIVED_FORM_LENGTH
    for form in (full, full.rstrip("=")):
        assert redact_sensitive_text(f"<{form}>") == f"<{MARK.format('SHORT_TOKEN')}>", form
    other = base64.b64encode(b"q7Rk2vXX").decode()  # shares the 8-character encoding of the first six bytes
    assert redact_sensitive_text(f"<{other}>") == f"<{other}>"


def test_an_all_digit_value_is_masked_only_outside_a_longer_number():
    ksv.register_known_secrets(None, {"SERVICE_PASSCODE": "73914628"})
    mark = MARK.format("SERVICE_PASSCODE")
    longer = "9739146280 73914628.5 1.73914628"
    assert redact_sensitive_text(longer) == longer
    assert redact_sensitive_text("code 73914628, v73914628 and 73914628.") == f"code {mark}, v{mark} and {mark}."


def test_image_parts_are_returned_as_the_same_object():
    ksv.register_known_secrets(None, {"SERVICE_TOKEN": "synthetic-image-adjacent"})
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,synthetic-image-adjacent"}}
    out = ksv.scrub_known_secrets([{"type": "text", "text": "see synthetic-image-adjacent"}, image])
    assert out[1] is image and out[0]["text"] == "see " + MARK.format("SERVICE_TOKEN")


def test_known_values_are_masked_with_redact_secrets_off(monkeypatch):
    from agent import redact
    monkeypatch.setattr(redact, "_redact_enabled", lambda: False)
    ksv.register_known_secrets(None, {"SERVICE_TOKEN": "synthetic-always-masked"})
    prefixed = "ghp_" + "a1B2c3D4e5" * 4  # a pattern-only secret: left alone with redaction off
    assert redact_sensitive_text(f"synthetic-always-masked {prefixed}") == f"{MARK.format('SERVICE_TOKEN')} {prefixed}"


def test_unencodable_value_is_skipped_without_raising(caplog):
    with caplog.at_level("WARNING", logger=ksv.__name__):
        ksv.register_known_secrets(None, {"BROKEN_TOKEN": "synthetic\udcffvalue", "SERVICE_TOKEN": "synthetic-good-value"})
    assert redact_sensitive_text("synthetic-good-value") == MARK.format("SERVICE_TOKEN")
    assert any("BROKEN_TOKEN" in r.getMessage() for r in caplog.records)


def test_marker_names_are_inert_in_json():
    ksv.register_known_secrets(None, {'service."cred\\key': "synthetic-quoted-key-value"})
    out = redact_sensitive_text(json.dumps({"v": "synthetic-quoted-key-value"}))
    assert json.loads(out) == {"v": "«redacted-secret:service._cred_key»"}


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


def test_lookup_is_the_union_of_every_profile_home(tmp_path):
    other = tmp_path / "other-profile"
    other.mkdir()
    ksv.register_known_secrets(other, {"OTHER_TOKEN": "synthetic-other-profile-value"})
    ksv.register_known_secrets(other, {"OTHER_PIN": "1234"})
    # Masked here too: recalled rows and timer threads do not always run under the owning profile.
    assert redact_sensitive_text("synthetic-other-profile-value") == MARK.format("OTHER_TOKEN")
    assert ksv.uncovered_names() == [] and ksv.uncovered_names(other) == ["OTHER_PIN"]
    token = set_hermes_home_override(other)
    try:
        assert redact_sensitive_text("synthetic-other-profile-value") == MARK.format("OTHER_TOKEN")
    finally:
        reset_hermes_home_override(token)


def test_unmatched_text_is_returned_unchanged_and_cheaply():
    rnd = random.Random(7)
    alphabet = string.ascii_letters + string.digits
    values = {f"SYNTH_{i}_TOKEN": "".join(rnd.choice(alphabet) for _ in range(rnd.randint(16, 64))) for i in range(300)}
    ksv.register_known_secrets(None, values)
    text = "".join(rnd.choice(alphabet + ' \n{}":,') for _ in range(100_000))
    start = time.perf_counter()
    out = ksv.redact_known_secret_values(text)
    elapsed = time.perf_counter() - start
    assert out == text
    assert elapsed < 2.0  # one regex pass; ~20 ms on a laptop for this input
    # The same matcher does mask: a no-op scrub cannot pass this test.
    assert ksv.redact_known_secret_values(text + values["SYNTH_7_TOKEN"]) == text + MARK.format("SYNTH_7_TOKEN")


def _load_profile(monkeypatch, config: str, entries: dict, plugin_secret: str | None = None) -> None:
    """Write a profile's config.yaml, .env and optionally a user platform plugin, then run the loader."""
    from hermes_cli import env_loader
    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(config, encoding="utf-8")
    (home / ".env").write_text("".join(f"{k}={v}\n" for k, v in entries.items()), encoding="utf-8")
    if plugin_secret:
        plugin = home / "plugins" / "platforms" / "chatx"
        plugin.mkdir(parents=True)
        (plugin / "plugin.yaml").write_text(
            f"name: chatx\nkind: platform\nrequires_env:\n  - name: {plugin_secret}\n    password: true\n",
            encoding="utf-8")
    for name in entries:
        monkeypatch.setenv(name, "")  # restored (removed) after the test
    env_loader.reset_secret_source_cache()
    env_loader.load_hermes_dotenv(hermes_home=home)


class TestDeclarationClasses:
    """Each way a profile declares a credential that the static blocklist does not list, through the
    loader (no value is registered directly)."""

    VALUE = "synthetic-declared-credential-x9"

    @pytest.mark.parametrize("config", [
        "auxiliary:\n  compression:\n    key_env: TEAM_SUMMARY_LLM\n",
        "fallback_model:\n  provider: custom\n  key_env: TEAM_SUMMARY_LLM\n",
        "providers:\n  team:\n    apiKeyEnv: TEAM_SUMMARY_LLM\n",
        "custom_providers:\n  - name: team\n    keyEnv: TEAM_SUMMARY_LLM\n",
    ], ids=["auxiliary-task", "legacy-fallback-model", "provider-alias", "custom-provider-alias"])
    def test_a_key_env_pointer_at_any_depth(self, monkeypatch, config):
        _load_profile(monkeypatch, config, {"TEAM_SUMMARY_LLM": self.VALUE})
        assert redact_sensitive_text(self.VALUE) == MARK.format("TEAM_SUMMARY_LLM")

    def test_a_credential_named_in_the_profiles_own_env_file(self, monkeypatch):
        _load_profile(monkeypatch, "{}\n", {"SYNTH_WEBHOOK_SECRET": self.VALUE})
        assert redact_sensitive_text(self.VALUE) == MARK.format("SYNTH_WEBHOOK_SECRET")

    def test_a_secret_declared_by_the_profiles_platform_plugin(self, monkeypatch):
        _load_profile(monkeypatch, "{}\n", {"CHATX_BRIDGE_CODE": self.VALUE}, plugin_secret="CHATX_BRIDGE_CODE")
        assert redact_sensitive_text(self.VALUE) == MARK.format("CHATX_BRIDGE_CODE")

    def test_an_env_file_entry_outside_the_file_is_not_swept(self, monkeypatch):
        monkeypatch.setenv("SYNTH_SHELL_SECRET", self.VALUE)  # secret-named, but not in this profile's .env
        _load_profile(monkeypatch, "{}\n", {"SYNTH_DISPLAY_LABEL": "synthetic-label"})
        assert redact_sensitive_text(self.VALUE) == self.VALUE


@pytest.mark.parametrize("name, value", [
    ("OPENAI_ORGANIZATION", "org-synthetic-team-identifier"),
    ("OPENAI_ORG_ID", "org-synthetic-team-identifier"),
    ("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/synthetic/service-account.json"),
])
def test_isolation_only_variables_are_not_credentials(name, value):
    from tools.environments.local_env_policy import _is_provider_env_blocklisted, credential_env_values
    assert _is_provider_env_blocklisted(name)  # stripped from children for isolation
    assert credential_env_values({name: value, "OPENROUTER_API_KEY": "synthetic-provider-key"}) == {
        "OPENROUTER_API_KEY": "synthetic-provider-key"}


class TestEnvironmentCredentials:
    """The environment feed registers what the child-environment policy strips as a credential and
    the provider keys config names via ``key_env``; nothing by name keyword alone."""

    PROVIDER, CUSTOM, SETTING = "synthetic-provider-credential", "synthetic-custom-endpoint-key", "synthetic-display-setting"

    @pytest.fixture
    def loaded(self, monkeypatch):
        entries = {
            "OPENROUTER_API_KEY": self.PROVIDER,  # on the provider blocklist
            "SYNTH_ENDPOINT_KEY": self.CUSTOM,  # named by model.key_env
            "SYNTH_DISPLAY_LABEL": self.SETTING,  # ordinary setting
            "SSH_AUTH_SOCK": "/tmp/synthetic-agent/agent.sock",  # secret-ish name, path value
            "MAX_TOKENS": "16000000",  # secret-ish name, numeric value
            "OPENAI_BASE_URL": "https://llm.example.invalid/v1",  # blocklisted, exempt suffix
            "TELEGRAM_HOME_CHANNEL": "-100123456789",  # blocklisted, declared non-secret
        }
        _load_profile(monkeypatch, "model:\n  key_env: SYNTH_ENDPOINT_KEY\n", entries)
        return entries

    def test_credentials_are_masked_in_a_non_env_dump_command(self, loaded):
        # The policy strips these variables from the child, so the command prints them from a file.
        dump = get_hermes_home() / "app-settings.txt"
        dump.write_text(f"{self.PROVIDER} {self.CUSTOM} {self.SETTING}", encoding="utf-8")
        output = _terminal_result(_python_command("import sys; print(open(sys.argv[1]).read())", str(dump)))
        assert output == f"{MARK.format('OPENROUTER_API_KEY')} {MARK.format('SYNTH_ENDPOINT_KEY')} {self.SETTING}"

    def test_settings_paths_and_numbers_are_not_registered(self, loaded):
        for name in ("SYNTH_DISPLAY_LABEL", "SSH_AUTH_SOCK", "MAX_TOKENS", "OPENAI_BASE_URL", "TELEGRAM_HOME_CHANNEL"):
            assert redact_sensitive_text(f"<{loaded[name]}>") == f"<{loaded[name]}>", name

    def test_unencodable_environment_value_does_not_abort_registration(self):
        ksv.register_environment_credentials(get_hermes_home(), {
            "OPENROUTER_API_KEY": "synthetic\udcffcredential", "GROQ_API_KEY": "synthetic-groq-credential"})
        assert redact_sensitive_text("synthetic-groq-credential") == MARK.format("GROQ_API_KEY")
