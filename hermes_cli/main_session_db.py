"""Fork: the retired ``--session-db`` flag, refused before any command or chat launch path runs."""
from __future__ import annotations

import os
import sys


def refuse_session_db(args, *, chat_launch: bool = False) -> None:
    """Fork: ``--session-db`` fails closed, whatever value it was given. Chat turns run inside the
    profile's gateway, which owns that profile's ``state.db``; a path pinned in this client process
    would be silently ignored, and a second gateway pointed at another profile's database would
    break the one-owner rule.

    ``chat_launch``: also refuse an inherited ``HERMES_SESSION_DB_PATH``. This client would list and
    resume sessions from that database while the gateway it starts (which never inherits the
    variable) writes the profile's own. A gateway the operator starts with the variable set is
    coherent and is not a chat launch.
    """
    if getattr(args, "session_db", None) is not None:
        print(
            "Error: --session-db is no longer supported. Chat turns run in the profile's gateway, "
            "which keeps its sessions in that profile's own state.db; choose the profile "
            "(HERMES_HOME or --profile) instead.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if chat_launch and os.environ.get("HERMES_SESSION_DB_PATH", "").strip():
        print(
            "Error: HERMES_SESSION_DB_PATH is set. A chat launch would read sessions from that "
            "database while the profile's gateway writes its own state.db. Unset it, or set it on "
            "the gateway process itself.",
            file=sys.stderr,
        )
        raise SystemExit(2)
