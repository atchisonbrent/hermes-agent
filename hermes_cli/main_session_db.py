"""Fork: the retired ``--session-db`` flag, refused before any chat launch path runs."""
from __future__ import annotations

import sys


def refuse_session_db(args) -> None:
    """Fork: ``--session-db`` fails closed. Chat turns run inside the profile's gateway, which owns
    that profile's ``state.db``; a path pinned in this client process would be silently ignored, and
    a second gateway pointed at another profile's database would break the one-owner rule."""
    if str(getattr(args, "session_db", None) or "").strip():
        print(
            "Error: --session-db is no longer supported. Chat turns run in the profile's gateway, "
            "which keeps its sessions in that profile's own state.db; choose the profile "
            "(HERMES_HOME or --profile) instead.",
            file=sys.stderr,
        )
        raise SystemExit(2)
