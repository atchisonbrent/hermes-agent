from __future__ import annotations

from pathlib import Path

import pytest


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


def test_external_session_db_keeps_profile_prompt_paths(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from agent.system_prompt import _agent_home, _agent_skills_dir
    from hermes_state import SessionDB

    home = tmp_path / "profile"
    target = tmp_path / "storage" / "state.db"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_SESSION_DB_PATH", str(target))
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    token = set_hermes_home_override(None)
    try:
        # The global test fixture deliberately repoints DEFAULT_DB_PATH after
        # the module's first import; explicitly select the integration DB here.
        with SessionDB(target) as db:
            assert db.db_path == target
            agent = SimpleNamespace(_session_db=db)
            assert _agent_home(agent) == home
            assert _agent_skills_dir(agent) == home / "skills"
    finally:
        reset_hermes_home_override(token)


def test_terminal_children_do_not_inherit_external_session_database(tmp_path, monkeypatch):
    from tools.environments.local import _make_run_env, _sanitize_subprocess_env

    target = str(tmp_path / "external.db")
    monkeypatch.setenv("HERMES_SESSION_DB_PATH", target)
    assert "HERMES_SESSION_DB_PATH" not in _make_run_env({})
    assert "HERMES_SESSION_DB_PATH" not in _sanitize_subprocess_env({"HERMES_SESSION_DB_PATH": target})


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


def _run_dispatch(tmp_path, program, extra_env=None):
    import os
    import subprocess
    import sys

    home = tmp_path / "isolated"
    target = tmp_path / "retained" / "state.db"
    env = {"HOME": str(tmp_path), "HERMES_HOME": str(home),
           "PATH": os.environ["PATH"], "TARGET_DB": str(target), **(extra_env or {})}
    result = subprocess.run([sys.executable, "-c", program], env=env,
                            capture_output=True, text=True, timeout=30, check=False)
    return result, home, target


_REFUSAL_PROGRAM = '''
import os
from hermes_cli import main
from hermes_cli import gateway_chat_startup
from hermes_cli._parser import build_top_level_parser
def launched(*args, **kwargs):
    raise AssertionError("a launch path ran before --session-db was refused")
gateway_chat_startup.launch_gateway_chat = launched
main._resolve_chat_session_args = launched
parser, _, _ = build_top_level_parser()
args = parser.parse_args(ARGV)
DISPATCH(args)
'''


def test_oneshot_dispatch_refuses_session_db_before_any_launch(tmp_path):
    """The gateway owns the profile's database, so a client-side pin must fail closed."""
    program = (_REFUSAL_PROGRAM
               .replace("ARGV", '["--session-db", os.environ["TARGET_DB"], "-z", "test"]')
               .replace("DISPATCH", "main._run_oneshot_from_args"))
    result, home, target = _run_dispatch(tmp_path, program)

    assert result.returncode == 2, result.stderr
    assert "--session-db is no longer supported" in result.stderr
    assert "AssertionError" not in result.stderr
    assert not target.exists()
    assert not (home / "state.db").exists()


def test_chat_dispatch_refuses_session_db_before_any_launch(tmp_path):
    program = (_REFUSAL_PROGRAM
               .replace("ARGV", '["chat", "--session-db", os.environ["TARGET_DB"], "-q", "test"]')
               .replace("DISPATCH", "main.cmd_chat"))
    result, home, target = _run_dispatch(tmp_path, program)

    assert result.returncode == 2, result.stderr
    assert "--session-db is no longer supported" in result.stderr
    assert "AssertionError" not in result.stderr
    assert not target.exists()
    assert not (home / "state.db").exists()


def test_dispatch_without_session_db_reaches_the_launcher(tmp_path):
    """Control: the refusal is tied to the flag, not to one-shot dispatch itself."""
    program = (_REFUSAL_PROGRAM
               .replace("ARGV", '["-z", "test"]')
               .replace("DISPATCH", "main._run_oneshot_from_args"))
    result, _home, _target = _run_dispatch(tmp_path, program)

    assert result.returncode == 1
    assert "a launch path ran before --session-db was refused" in result.stderr


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_session_db_value_is_refused_too(tmp_path, value):
    """Presence of the flag is what is retired, not a particular value."""
    program = (_REFUSAL_PROGRAM
               .replace("ARGV", repr(["--session-db", value, "-z", "test"]))
               .replace("DISPATCH", "main._run_oneshot_from_args"))
    result, _home, _target = _run_dispatch(tmp_path, program)

    assert result.returncode == 2, result.stderr
    assert "--session-db is no longer supported" in result.stderr
    assert "AssertionError" not in result.stderr


@pytest.mark.parametrize("dispatch,argv", [
    ("main._run_oneshot_from_args", ["-z", "test"]),
    ("main.cmd_chat", ["chat", "-q", "test"]),
])
def test_chat_launch_refuses_an_inherited_database_variable(tmp_path, dispatch, argv):
    """The client would read one database while the gateway it starts writes another."""
    program = _REFUSAL_PROGRAM.replace("ARGV", repr(argv)).replace("DISPATCH", dispatch)
    result, _home, target = _run_dispatch(
        tmp_path, program, extra_env={"HERMES_SESSION_DB_PATH": str(tmp_path / "other.db")})

    assert result.returncode == 2, result.stderr
    assert "HERMES_SESSION_DB_PATH is set" in result.stderr
    assert "AssertionError" not in result.stderr
    assert not target.exists()


def test_non_chat_command_refuses_session_db_through_main(tmp_path):
    """`hermes --session-db X <any command>` must not run the command against the profile store."""
    program = '''
import os, sys
from hermes_cli import main
def ran(*args, **kwargs):
    raise AssertionError("the command ran before --session-db was refused")
main._prepare_agent_startup = ran
sys.argv = ["hermes", "--session-db", os.environ["TARGET_DB"], "sessions", "list"]
main.main()
'''
    result, _home, target = _run_dispatch(tmp_path, program)

    assert result.returncode == 2, result.stderr
    assert "--session-db is no longer supported" in result.stderr
    assert "AssertionError" not in result.stderr
    assert not target.exists()


def test_non_chat_command_keeps_the_database_variable(tmp_path, monkeypatch):
    """Control: outside chat launches the variable stays usable (an operator-started gateway)."""
    from argparse import Namespace
    from hermes_cli.main_session_db import refuse_session_db

    monkeypatch.setenv("HERMES_SESSION_DB_PATH", str(tmp_path / "other.db"))
    refuse_session_db(Namespace(session_db=None))
    with pytest.raises(SystemExit):
        refuse_session_db(Namespace(session_db=None), chat_launch=True)
