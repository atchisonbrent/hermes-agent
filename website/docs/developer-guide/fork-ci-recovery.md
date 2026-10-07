# Fork change record: CI recovery

Classification: local-product-delta. Maintenance owner: fork maintainer.
Upstream status: not-filed. Private details removed: yes.

Fork baseline: `dbf8de5bf71a298d9106c003ef43aa9816f54b58`.
Merged upstream release: `v2026.9.24`,
`f97608f178d1ffeca59860195ab7da295f7c8e5f`.

## Scope and rationale

Restore the fork's existing CI contracts after integration drift; do not relax
approval, persistence, or update acceptance rules. This is not a new
upstream integration or a claim that every historical updater can upgrade to
this revision. Fork prompt expectations and the durable-write review component
are local policy. Generic harness fixes can be submitted separately after
reproducing against current upstream.

- Read durable-write configuration and receipts as UTF-8. Report unavailable
  receipt readback with a fixed-label warning, without logging file contents.
  Non-object JSON receipts produce an unknown outcome instead of a caller crash.
- Keep the one-shot skill test discriminating against the fork's actual
  interactive maintenance guidance.
- Generate an explicit null only when requested by the null-preservation tests;
  truncate at an actual quoted YAML scalar, not an arbitrary character offset.
- Use actual input/approval readiness and the compute supervisor's cold-start
  budget rather than racing startup and cleanup.
- Make desktop polling fixtures agree with the backend registry, drain the
  poller between tests, and intercept writes at the object that owns `setItem`.
- Bound the profile-local MCP fixture with a 15-second discovery override and
  a 30-second response deadline (previously 10 seconds). A deliberately slow
  probe verifies the override; production discovery defaults are unchanged.
- Add the commit author's existing public email to the fork contributor map.
- Wait for mounted rows before TUI unmount tests. Check the existing geometry
  assertions at convergence and again after the original 40ms observation window;
  this is not a claim of renderer quiescence.
- Wait for the model-generated session title, not the instant placeholder,
  before marking the next routing-test leg; retain every host/key assertion.
- Pass the documented state-DB test exemption only to throwaway upgrade-install
  children. Retain the parent sandbox/CI prerequisite and production guard.
  Assert seeded sessions before copying state. Permit SQLite recovery when
  fingerprinting these disposable databases; integrity, row counts and message
  digests still must match. A real killed-writer fixture checks recovery preserves
  committed data rather than silently accepting missing rows.

## Upgrade baseline

The upgrade suite promises the preceding merged release, but a fork's copied
release tags can lag its code. Fetch upstream date-version release tags into
`refs/upstream-release-tags/`, outside both fork tags and branches. Select the
highest reachable release version at `HEAD~1`, verify ancestry, log its ref/SHA
and distance, and pass the resolved SHA through `HERMES_E2E_UPGRADE_BASE`.
The shell runner explicitly forwards that one non-secret control; arbitrary
ambient variables remain stripped. Missing baseline selection fails closed.

This corrects an N-1 fixture, not historical release code. No tag is moved and
no upstream branch is merged. The August baseline's old in-process updater and
absent stale-lock recovery are not repaired or declared supported by this work.
Do not weaken the current suite to accommodate those historical implementations.

## Verification and limits

Use `scripts/run_tests.sh` for the changed Python test files, including
`tests/scripts/test_run_tests_shell_env.py`, and the complete
`tests/e2e/core/upgrade/test_upgrade_path.py` in disposable Linux isolation.
The latter runs real clean, autostash, interrupted and offline upgrades against
local Git origins and a fake model provider. Run the routing matrix in
`tests/e2e/core/tenancy/test_routing_truth_table.py` through the same runner.
Run the desktop Vitest suite and `npm --prefix ui-tui run check` on CI's Node
major, plus Windows-footgun lint. Publication requires both independent reviewers and a
fresh exact-head CI result; local passes do not certify remote CI.

Regression evidence includes ASCII-locale receipt/config failures, malformed
receipt diagnostics without content disclosure, non-vacuous YAML fixtures,
real shell environment forwarding, actual tmux interaction, Storage failure
controls, and SQLite hot-journal recovery. Timing-sensitive historical failures
that cannot be reproduced remain diagnosis limits, not claimed root-cause fixes.

Fingerprinting permits normal SQLite recovery and may checkpoint a WAL; it
checks logical committed-state preservation, not pristine journal files or
absence of uncommitted metadata. A read-only observation failed after an N-1
process returned success; its exact clean-exit trigger is not established.
The suite logs journal presence/mode and the resolved baseline/environment.
Local capability-dropped Linux tests are not a substitute for CI's bwrap/WAL
lane. An explicitly configured baseline that cannot resolve fails rather than
silently skipping coverage.

Rebase surfaces: the fork review component, skill guidance, test fixtures,
`scripts/run_tests.sh`, and `.github/workflows/tests.yml`. Update hazard: future
release naming or runner isolation changes can invalidate the explicit baseline.
Reclassification trigger: equivalent upstream fixes or retirement of the local
policy components. Rollback: revert the reviewed recovery changes in a separately
verified change; no data migration or user configuration rewrite is introduced.
