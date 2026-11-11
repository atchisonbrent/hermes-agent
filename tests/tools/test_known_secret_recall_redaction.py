"""Tools that pull stored text back into context mask the process's known secret values.

``session_search`` returns stored session rows and ``search_files`` returns file lines; either may
hold a value a secret source supplied. All values are synthetic.
"""

import json
from pathlib import Path

import pytest

from agent import known_secret_values as ksv

VALUE = "synthetic-recall-value-7Qm2"
MARK = "«redacted-secret:SERVICE_SIGNING_TOKEN»"


@pytest.fixture(autouse=True)
def _registered():
    ksv.clear_known_secrets()
    ksv.register_known_secrets(None, {"SERVICE_SIGNING_TOKEN": VALUE})
    yield
    ksv.clear_known_secrets()


def _store(db_path: Path, content: str) -> None:
    from hermes_state import SessionDB
    db = SessionDB(db_path)
    try:
        db.create_session("recall-source", source="cli")
        db.append_message("recall-source", role="user", content="list the signing secrets")
        db.append_message("recall-source", role="assistant", content=content)
    finally:
        db.close()


def _search(args: dict) -> str:
    from tools.registry import registry
    import tools.session_search_tool  # registers the tool
    raw = registry.get_entry("session_search").handler(args)
    assert json.loads(raw)["success"] is True, raw
    return raw


def test_session_search_results_are_masked():
    from hermes_constants import get_hermes_home
    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    _store(home / "state.db", f'The signing listing: [{{"key": "SERVICE_SIGNING_TOKEN", "value": "{VALUE}"}}]')
    for args in ({"session_id": "recall-source"}, {"query": "signing"}):
        raw = _search(args)
        assert VALUE not in raw and MARK in raw, args


def test_recall_from_another_profile_uses_the_union_lookup(tmp_path, monkeypatch):
    """A value registered under another profile's home (as that profile's own process or a served scope
    would) is masked in this profile's recall of that profile's rows. Recall itself registers nothing."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    home = tmp_path / ".hermes"
    other = home / "profiles" / "recall-target"
    other.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    ksv.register_known_secrets(other, {"TARGET_TOKEN": "synthetic-target-profile-value"})
    _store(other / "state.db", "The signing listing holds synthetic-target-profile-value")
    raw = _search({"session_id": "recall-source", "profile": "recall-target"})
    assert "synthetic-target-profile-value" not in raw and "«redacted-secret:TARGET_TOKEN»" in raw


def test_recalled_json_listing_with_a_quoted_value_stays_valid_json():
    from hermes_constants import get_hermes_home
    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    quoted = 'synthetic"quoted\\value'
    ksv.register_known_secrets(None, {'service."cred': quoted})
    _store(home / "state.db", "The signing listing: " + json.dumps([{"key": 'service."cred', "value": quoted}]))
    raw = _search({"session_id": "recall-source"})
    content = json.loads(raw)["messages"][1]["content"]
    prefix, listing = content.split(": ", 1)
    assert prefix == "The signing listing"
    assert json.loads(listing) == [{"key": 'service."cred', "value": "«redacted-secret:service._cred»"}]


def test_search_files_results_are_masked(tmp_path):
    from tools.file_tools import search_tool

    (tmp_path / "service.log").write_text(f"started with signing value {VALUE}\n", encoding="utf-8")
    raw = search_tool("signing value", path=str(tmp_path), task_id="known-secret-search")
    assert json.loads(raw)["total_count"] == 1, raw
    assert VALUE not in raw and MARK in raw


def test_session_search_error_results_are_redacted():
    from hermes_constants import get_hermes_home
    from tools.registry import registry
    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    _store(home / "state.db", "nothing secret here")
    prefixed = "ghp_" + "a1B2c3D4e5" * 4  # a pattern-recognised credential pasted as an argument
    import tools.session_search_tool  # registers the tool
    raw = registry.get_entry("session_search").handler({"query": "signing", "after": prefixed})
    assert json.loads(raw).get("success") is False and "invalid time bound" in raw, raw
    assert prefixed not in raw
