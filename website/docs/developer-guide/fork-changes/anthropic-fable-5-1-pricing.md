# Native Anthropic Claude Fable 5.1 pricing

## Upstream Candidate

Classification: upstream-candidate
Upstream base: `upstream/main` at `593aa74c6182ce2e5e23bc102daaaae71710c05d`
Problem: Native Anthropic sessions using `claude-fable-5-1` record complete token usage but report unknown estimated cost.
Reproduction: Call `estimate_usage_cost` for `claude-fable-5-1` with provider `anthropic` and nonzero input, output, cache-read, and cache-write usage.
Expected behavior: Hermes returns an estimated USD cost using Anthropic's published rates.
Actual behavior: Hermes returns `status="unknown"`, `source="none"`, and no amount because the static pricing table has no Fable 5.1 row.
Root cause: Direct Anthropic billing uses the official-docs pricing snapshot, which predates the model.
Change: Add the published Fable 5.1 input, output, cache-read, and standard 5-minute cache-write rates plus a regression test covering all four buckets.
Verification: Targeted pricing test; full pricing and model-cost-guard suites; direct pricing probe against recorded usage.
Compatibility / risk: Additive static metadata only. Hermes cannot distinguish optional 1-hour cache writes in its canonical usage schema; this row intentionally prices the standard 5-minute writes Hermes emits. No model routing, aliases, request behavior, or provider configuration changes.
Maintenance owner: Brent Atchison / `atchisonbrent/hermes-agent` fork until upstream accepts or independently ships the row.
Rollback: Revert the retained commit; new Fable 5.1 costs return to unknown without changing recorded token usage.
Upstream status: issue-ready
Private details removed: yes

## Reclassification trigger

Retire the fork delta when upstream ships equivalent Fable 5.1 pricing. Extend the accounting model separately if Hermes begins requesting 1-hour Anthropic cache writes, because those writes have a distinct published rate.
