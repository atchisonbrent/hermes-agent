"""Tools that pull stored text back into context mask the process's known secret values.

``session_search`` returns stored session rows and ``search_files`` returns file lines; either may
hold a value a secret source supplied. All values are synthetic.
"""

import json

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


def test_session_search_results_are_masked():
    from hermes_constants import get_hermes_home
    from hermes_state import SessionDB
    from tools.registry import registry
    import tools.session_search_tool  # registers the tool

    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    db = SessionDB(home / "state.db")
    try:
        db.create_session("recall-source", source="cli")
        db.append_message("recall-source", role="user", content="list the signing secrets")
        db.append_message("recall-source", role="assistant",
                          content=f'The signing listing: [{{"key": "SERVICE_SIGNING_TOKEN", "value": "{VALUE}"}}]')
    finally:
        db.close()
    handler = registry.get_entry("session_search").handler
    for args in ({"session_id": "recall-source"}, {"query": "signing"}):
        raw = handler(args)
        assert json.loads(raw)["success"] is True, raw
        assert VALUE not in raw and MARK in raw, args


def test_search_files_results_are_masked(tmp_path):
    from tools.file_tools import search_tool

    (tmp_path / "service.log").write_text(f"started with signing value {VALUE}\n", encoding="utf-8")
    raw = search_tool("signing value", path=str(tmp_path), task_id="known-secret-search")
    assert json.loads(raw)["total_count"] == 1, raw
    assert VALUE not in raw and MARK in raw
