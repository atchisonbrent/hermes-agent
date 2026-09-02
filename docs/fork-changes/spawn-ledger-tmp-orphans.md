# Spawn-ledger temp-file orphans on cancelled MCP helper registration

## Upstream Candidate

Classification: upstream-candidate
Upstream base: upstream/main (NousResearch/hermes-agent) at the fork's reviewed baseline after the 2026-09-02 reconciliation
Problem: `$HERMES_HOME/spawn-ledger.json.tmp<pid>` files accumulate indefinitely — 431 on one host after four days — each a complete, valid copy of the ledger that was written but never renamed over the real file.
Reproduction: run any short-lived Hermes process that starts a stdio MCP server and then exits before the event loop finishes the registration step (e.g. `hermes mcp test <server>`, a cron preflight, or a one-shot `hermes chat -q` with MCP servers configured). Observe a new `spawn-ledger.json.tmp<pid>` left behind whose `mcp-helper` entry names the child that process spawned. The two long-lived processes (gateway, WebUI) never leave one.
Expected behavior: `_append_entry` either completes the atomic `tmp → path` replace or best-effort removes its temp file when Python unwinds the write block. An uncatchable process kill inside that tiny window may still leave benign residue.
Actual behavior: `hermes_cli/process_identity._append_entry` writes `tmp` then calls `os.replace(tmp, path)` inside `try: … except OSError:`. A `BaseException` delivered between those synchronous calls—for example `KeyboardInterrupt` while a short-lived CLI is interrupted—bypasses both that handler and `except Exception` wrappers at callers, leaving the completed temp file. Evidence: every orphan's `<pid>` suffix belongs to a short-lived CLI process; none belong to the gateway or WebUI pids; the orphan contents equal the ledger plus one `mcp-helper` entry; a direct `register_child` call from a plain script leaves nothing behind. Plain asyncio task cancellation normally cannot interrupt inside this synchronous block; it was an over-specific initial hypothesis, not the established mechanism.
Root cause: no `finally`-scoped best-effort cleanup of the temp path when control leaves the write block before `os.replace` completes.
Change: `_append_entry` now owns a pid-scoped `tmp` variable outside the write block and unlinks it in `finally`. Successful `os.replace` leaves no path, ordinary `OSError` retains the existing best-effort `False` contract, and `BaseException` propagates only after cleanup. Cleanup `OSError` is logged and suppressed so it cannot replace the original exception or violate `register_child`'s never-raises-on-ordinary-I/O contract.
Verification: tests assert the temp source exists when patched `os.replace` raises a `BaseException`, require that exception to propagate with no residue, cover ordinary `OSError` returning `False` with cleanup, and prove a cleanup `OSError` does not escape. The focused file suite passes 25 tests. Deployment verification removes the 17 pre-fix orphans, runs short-lived MCP/CLI activity, and checks no new temp file appears.
Compatibility / risk: cleanup only; the ledger write contract (`_LEDGER_LOCK`, atomic replace) is unchanged. A concurrent writer uses a different pid suffix, so unlinking our own temp file cannot race another writer.
Maintenance owner: Brent Atchison (fork `atchisonbrent/hermes-agent`)
Rollback: revert the commit; orphans resume accumulating (harmless clutter).
Upstream status: PR-ready
Private details removed: yes

## Operational note (private deployment)

Implemented in the fork after closing audit proved 17 files had already regenerated. A stale-tmp sweep was intentionally not added: it widens the change and kill-window residue is harmless. Existing residue can be deleted once before deployment; recurring files under ordinary graceful/interrupt shutdown are a regression, while rare hard-kill-window residue remains possible.
