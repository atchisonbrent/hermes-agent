# Public reconciled model-usage breakdown

## Upstream Candidate

Classification: upstream-candidate
Upstream base: `upstream/main` at merge base `2e25b472108d0f36e02a95bae212255ae76fac0e`; implemented on fork baseline `94affcd6e1850699daf7c5499a3cbfdad8c1f8a8`.
Problem: External dashboards cannot obtain authoritative per-model ledger usage, daily attribution, totals, and exact session coverage through a supported Agent API.
Reproduction: Build an Insights report for sessions containing model switches or backfilled `session_model_usage` costs; the public API exposes only the full report while consumers must otherwise call private query and reconciliation methods.
Expected behavior: A public read-only method returns one-snapshot reconciled model rows, daily rows, exact totals, session IDs, and ledger-contribution IDs for a cutoff and optional source.
Actual behavior: Consumers must duplicate reconciliation or depend on private `InsightsEngine` and database internals, risking torn reads and incomplete coverage assumptions.
Root cause: `InsightsEngine` had no narrow public model-usage contract for external consumers.
Change: Add `get_model_usage_breakdown`, use one transactional snapshot and one ledger fetch, include zero-usage sessions explicitly, support sessions spanning the cutoff, and keep `generate()` output unchanged.
Verification: `scripts/run_tests.sh tests/agent/test_insights.py -q` (44 passed); Ruff on changed Python files; Python diff checks; cross-repository live read-only WebUI probe.
Compatibility / risk: Additive public method. Existing `generate()` behavior and payload shape remain unchanged. The new method may flush queued counters only on writer connections before opening its snapshot; read-only consumers do not mutate state.
Maintenance owner: Brent Atchison / `atchisonbrent/hermes-agent` fork until upstream accepts or independently provides an equivalent contract.
Rollback: Revert the retained commit; existing Agent reporting remains intact and newer WebUI consumers fall back atomically to legacy aggregation.
Upstream status: issue-ready
Private details removed: yes

## Reclassification trigger

Retire this fork delta when upstream ships an equivalent stable Insights model-usage API. Rework the consumer contract if upstream introduces a versioned analytics endpoint instead of an in-process API.
