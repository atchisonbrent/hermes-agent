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


def test_oneshot_dispatch_pins_database_before_resume_lookup(tmp_path):
    """Exercise dispatch and real SessionDB without calling a model."""
    import os
    import subprocess
    import sys

    home = tmp_path / "isolated"
    target = tmp_path / "retained" / "state.db"
    env = {"HOME": str(tmp_path), "HERMES_HOME": str(home),
           "PATH": os.environ["PATH"], "TARGET_DB": str(target)}
    program = '''
import os
from pathlib import Path
from hermes_cli import main
from hermes_cli._parser import build_top_level_parser
from hermes_state import SessionDB
parser, _, _ = build_top_level_parser()
args = parser.parse_args(["--session-db", os.environ["TARGET_DB"], "-z", "test"])
def resolve(args, use_tui):
    assert os.environ.get("HERMES_SESSION_DB_PATH") == os.environ["TARGET_DB"]
def run(*args, **kwargs):
    db = SessionDB()
    db.create_session("oneshot-override", source="cli", model="test")
    db.close()
main._resolve_chat_session_args = resolve
main._run_and_exit_oneshot = run
main._run_oneshot_from_args(args)
assert Path(os.environ["TARGET_DB"]).is_file()
assert not (Path(os.environ["HERMES_HOME"]) / "state.db").exists()
'''
    result = subprocess.run([sys.executable, "-c", program], env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
