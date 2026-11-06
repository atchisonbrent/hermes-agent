# Covering index for per-session role counts

## Upstream Candidate

Classification: upstream-candidate
Product base: `origin/main` at `300592b63c4c771522a83e2605e17eb97c63530d`
Upstream comparison: `upstream/main` at `6b21d0564d` (2026-11-07). No index covers `messages.role`.

**Problem.** Per-session aggregates of `COUNT(*)`, `COUNT(role = 'user')` and `MAX(timestamp)` read every message row of the sessions involved from the table. On a large store those rows are big because tool output is inline, so the cost is cold page reads. The WebUI sidebar's recent-session projection runs exactly this aggregate over a window of about 160 sessions on every rebuild of its list cache.

**Reproduction.** Run the aggregate on a multi-GB `state.db` with a cold page cache. A fresh APFS clone is a convenient way to get one, because clones do not share the page cache.

**Expected behavior.** The counts are served from an index, independent of row size and of cache state.

**Actual behavior.**
- On a 4.5 GB store (379k messages, about 163k in the window) the query took 7.0 s cold and 0.35 s warm.
- In production it accounted for 10.2 s of a 10.5 s sidebar load.

**Root cause.** No index covers `role`, so `COUNT(CASE WHEN role = 'user' ...)` forces a table read for every row.

**Change.**
1. `idx_messages_session_role ON messages(session_id, role, timestamp)` is added to `SCHEMA_SQL`. Its columns are base columns, so it is safe on legacy stores.
2. When a pre-existing `sqlite_stat1` lacks a row for this index, the index is analyzed. That happens once it has rows; on an empty `messages` table SQLite writes no row, so the check repeats as a no-op of about 0.05 ms per writable open until messages exist. Otherwise the stat-less index would be treated as selective and would reroute unpinned transcript reads, the #119403 class. Stores without stats are left without stats.

**Verification.**
- Cold clone with the index: the plan is `SEARCH m USING COVERING INDEX idx_messages_session_role`, 0.33 s cold and 0.23 s warm. The index is 14.7 MB.
- `TestSessionRoleCountIndex` covers four things:
  - the plan and the counts;
  - recreation on reopen;
  - stale stats gaining a row (the version-independent control), with the `latest` transcript read on `idx_messages_session_id` without a temp sort. Independent review reproduced the stat-less flip on SQLite 3.54.1 from about 49 rows per session; SQLite 3.53.1, used by the dev test venv, does not flip even at 1,500 rows, so there the plan half passes regardless;
  - stat-less stores staying stat-less.
- Removing the analyze step fails the stale-stats test.
- `tests/hermes_state/test_hermes_state.py` fails the same 8 VACUUM/auto-maintenance and read-only-open tests on this change as on the base. `test_session_list_index_choice.py` passes.

**Compatibility / risk.**
- Each message insert updates one more b-tree, about 40 B per row.
- On the first writable open after upgrade, a large store builds the index under the write lock. That was 17 s for 379k messages, against a 20 s open-lock patience, and it scales with message count.
- This one-time cost is accepted, consistent with the existing `SCHEMA_SQL` indexes. Very large installs can pre-create the identical index in a maintenance window. The build at upgrade then becomes a no-op; where stats exist, the targeted ANALYZE (tens of ms) still runs once.
- Transcript writes (60 s) and default writes (20 s) tolerate the measured build. Activity writes (0.5 s) are best-effort.

**Maintenance owner:** Brent Atchison / fork maintainers.

**Rollback:** revert the change. The index can then be dropped with `DROP INDEX idx_messages_session_role`; nothing depends on it for correctness.

**Upstream status:** issue-ready, not filed.

**Private details removed:** yes. No private paths, transcript content or session identifiers are included.
