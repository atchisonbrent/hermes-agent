# Spawn-ledger temp-file orphans on cancelled MCP helper registration

## Upstream Candidate

Classification: upstream-candidate
Upstream base: upstream/main (NousResearch/hermes-agent) at the fork's reviewed baseline after the 2026-09-02 reconciliation
Problem: `$HERMES_HOME/spawn-ledger.json.tmp<pid>` files accumulate indefinitely — 431 on one host after four days — each a complete, valid copy of the ledger that was written but never renamed over the real file.
Reproduction: run any short-lived Hermes process that starts a stdio MCP server and then exits before the event loop finishes the registration step (e.g. `hermes mcp test <server>`, a cron preflight, or a one-shot `hermes chat -q` with MCP servers configured). Observe a new `spawn-ledger.json.tmp<pid>` left behind whose `mcp-helper` entry names the child that process spawned. The two long-lived processes (gateway, WebUI) never leave one.
Expected behavior: `_append_entry` either completes the atomic `tmp → path` replace or removes its temp file; no orphaned temp files.
Actual behavior: `hermes_cli/process_identity._append_entry` writes `tmp` then calls `os.replace(tmp, path)` inside `try: … except OSError:`. The MCP helper registration (`tools/mcp_tool.py`, `register_child(_pid, "mcp-helper")`) runs inside the cancellable `async _run_stdio` task. When the owning process is shutting down, the task is cancelled between `write_text` and `os.replace`; `asyncio.CancelledError` is a `BaseException`, so neither the `except OSError` in `_append_entry` nor the `except Exception` at the call site runs, and the temp file is never unlinked. Evidence: every orphan's `<pid>` suffix belongs to a short-lived CLI process; none belong to the gateway or WebUI pids; the orphan contents equal the ledger plus one `mcp-helper` entry; a direct `register_child` call from a plain script leaves nothing behind.
Root cause: no `finally`-scoped cleanup of the temp path in `_append_entry`; the cancellation path is not an `OSError`.
Change: in `_append_entry`, wrap the write+replace in `try/finally` and `tmp.unlink(missing_ok=True)` in the `finally` when the replace did not complete (guard with a `replaced` flag). Optionally, sweep stale `spawn-ledger.json.tmp*` older than a few minutes at ledger read time, mirroring the existing dead-pid prune.
Verification: unit test that cancels (raises `BaseException` subclass from a patched `os.replace`) and asserts no `*.tmp*` remains; live check that `hermes mcp test unifi-network` leaves no new temp file.
Compatibility / risk: cleanup only; the ledger write contract (`_LEDGER_LOCK`, atomic replace) is unchanged. A concurrent writer uses a different pid suffix, so unlinking our own temp file cannot race another writer.
Maintenance owner: Brent Atchison (fork `atchisonbrent/hermes-agent`)
Rollback: revert the commit; orphans resume accumulating (harmless clutter).
Upstream status: issue-ready
Private details removed: yes

## Operational note (private deployment)

Not yet implemented in the fork; recorded so the finding survives session history. Until fixed, `find $HERMES_HOME -maxdepth 1 -name 'spawn-ledger.json.tmp*' -mmin +10 -delete` is a safe periodic cleanup (the live ledger is never a `.tmp*` path).
