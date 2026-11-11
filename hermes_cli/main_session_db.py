"""Fork: the retired ``--session-db`` flag, refused before any command or chat launch path runs."""
from __future__ import annotations

import os
import sys


def refuse_session_db(args, *, chat_launch: bool = False) -> None:
    """Fork: ``--session-db`` fails closed, whatever value it was given. Chat turns run inside the
    profile's gateway, which owns that profile's ``state.db``; a path pinned in this client process
    would be silently ignored, and a second gateway pointed at another profile's database would
    break the one-owner rule.

    ``chat_launch``: also refuse an inherited ``HERMES_SESSION_DB_PATH``. A chat launch ignores it
    end to end (this client's session lookups name the profile's ``state.db``, and the gateway it
    starts never inherits the variable), so a caller relying on it would be silently writing to the
    profile store. A gateway the operator starts with the variable set honours it and is not a chat
    launch.
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
            "Error: HERMES_SESSION_DB_PATH is set, and a chat launch ignores it: sessions go to the "
            "profile's own state.db through its gateway. Unset it, or set it on the gateway process "
            "itself.",
            file=sys.stderr,
        )
        raise SystemExit(2)
