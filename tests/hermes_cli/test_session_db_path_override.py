from __future__ import annotations

from pathlib import Path


def test_session_db_path_override_separates_state_from_hermes_home(tmp_path, monkeypatch):
    import hermes_state

    isolated_home = tmp_path / "isolated-home"
    durable_db = tmp_path / "durable" / "review-state.db"
    isolated_home.mkdir()
    durable_db.parent.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(isolated_home))
    monkeypatch.setenv("HERMES_SESSION_DB_PATH", str(durable_db))

    db = hermes_state.SessionDB()
    try:
        db.create_session("review-visible", source="cli", model="review-model")
    finally:
        db.close()

    assert durable_db.exists()
    assert not (isolated_home / "state.db").exists()


def test_repointed_default_db_path_wins_over_session_db_environment(tmp_path, monkeypatch):
    import hermes_state

    pinned = tmp_path / "pytest-pinned" / "state.db"
    requested = tmp_path / "integration" / "state.db"
    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", pinned)
    monkeypatch.setenv("HERMES_SESSION_DB_PATH", str(requested))

    assert hermes_state._default_db_path() == pinned


def test_chat_parser_accepts_explicit_session_db_path(tmp_path):
    from hermes_cli._parser import build_top_level_parser

    parser, _subparsers, _chat_parser = build_top_level_parser()
    target = tmp_path / "state.db"
    args = parser.parse_args(["chat", "--session-db", str(target)])

    assert args.session_db == str(target)


def test_top_level_oneshot_parser_accepts_session_db_path(tmp_path):
    from hermes_cli._parser import build_top_level_parser

    parser, _subparsers, _chat_parser = build_top_level_parser()
    target = tmp_path / "state.db"
    args = parser.parse_args(["--session-db", str(target), "-z", "review"])

    assert args.session_db == str(target)
