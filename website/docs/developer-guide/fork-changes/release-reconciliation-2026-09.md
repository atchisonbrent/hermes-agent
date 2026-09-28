# September release reconciliation

Classification: local-product-delta (maintenance of existing fork policies and
upstream candidates, not a new upstream feature).
Maintenance owner: fork maintainer.
Current upstream base: release `v2026.9.24`, commit
`f97608f178d1ffeca59860195ab7da295f7c8e5f`.
The historical verification below originally reconciled `v2026.9.14` at
`345cd2b057a452236de401d3534b8502a7465e8d`.
Fork baseline: `809a481178807ab9742cd95ce89804640b7f7277`.
Upstream status: not-filed; individual candidates retain their own records.

## Retained behavior and current owners

- W&B attribution: `agent/agent_init.py`, `agent/client_lifecycle.py`, and
  `agent/auxiliary_client.py`. Main construction, route rebuilds, and synchronous
  and asynchronous auxiliary clients retain the exact-host policy.
- Pricing: existing W&B and Fable rows and W&B billing-route normalization remain
  in `agent/usage_pricing.py`. Upstream already supplies equivalent Astra tiered
  pricing; that duplicate implementation is retired.
- Native compaction: exact-model thresholds remain in `agent/native_compaction.py`,
  construction in `agent/agent_init.py`, gateway cache invalidation in
  `gateway/run.py`, and live TUI adoption in `tui_gateway/session_compression.py`.
  TUI functions are rebound into `tui_gateway.server`; callers use that bound
  runtime entrypoint rather than calling unbound module functions.
- Durable-write review: `tools/write_approval.py`, the existing tool dispatch
  evidence hooks, and `hermes_cli/write_approval_commands.py`. Serialized memory
  writers now live in `tools/memory_tool_store.py`; batch skill staging is in
  `tools/skill_manager_batch.py`. Pending records use upstream's path and atomic
  JSON writer. Original evidence and background ownership/read guards remain.
- Skill loading/learning policy: `agent/prompt_builder.py` and
  `agent/background_review.py`; no-write is valid, recurrence is required, and
  preferences are not duplicated across storage owners. New upstream procedural
  guidance is retained without restoring mandatory-write pressure.
- Leaf-linked skill references: `tools/path_security.py` and the shared reader in
  `tools/skills_tool_plugin.py`, used by ordinary and plugin-qualified views.
- Public reconciled usage API: `agent/insights.py`; additive API, consistent
  snapshot, spanning-session coverage, unchanged existing report contract. The
  cutoff selects sessions, whose lifetime totals are reported; daily buckets
  use session start dates, with `?` for corrupt timestamps. Windows are not
  additive period-usage reports. An open session whose start precedes the cutoff
  is excluded; a NULL end time is not proof of recent activity. This is retained
  selection behavior, not an all-live-sessions report.
- Reference-preserving config saves: `hermes_cli/config.py`; the downstream
  string-policy seam and fail-closed ambiguous named-list handling remain.
- Session database override: parser, chat and one-shot entrypoints, and `hermes_state.py`;
  explicit override is separate from profile configuration isolation.
- Process lifecycle: real exit evidence after output EOF in
  `tools/process_registry.py`. Waiting retains a reader thread until actual exit;
  elapsed time alone must not fabricate completion. Spawn-ledger cleanup is
  supplied by upstream `utils.atomic_json_write`; the obsolete local cleanup
  block is retired and tests inspect the actual upstream temp files.
- Desktop: session-owned reasoning remains in the extracted
  `use-model-menu-controller.ts`; model catalog and fast-mode presets retain
  their existing responsibilities.
- Fork CI: standard runners instead of unprovisioned billable runners; upstream
  mutation workflow remains upstream-only. No test reduction is introduced.

## September 28 production-delta integration (historical checkpoint)

The release candidate also incorporates deployment commits through
`a8d6bfcd5fb566204d7675c32454d033a700b8a9`: W&B DeepSeek V4.1 Flash pricing
and the explicit GPT-6 Sol/Astra Codex variants. Their deployed 890K opt-in
limits and 272K base limits are preserved; no provider call or larger limit
is inferred. Independent source review identified a fourth regression file
with the previous 900K Astra expectation; its failing test was reproduced and
aligned with the deployed 890K contract. All four files then passed 206 tests
in a clean, credential-free environment using the repository's per-file runner
and the existing candidate Python 3.11 environment. The later v2026.9.24
integration adopts upstream's GPT-6 Sol/Luna/Astra autoraise families and limits
the alias accounting claim to Codex OAuth. The all-tree unbounded compilation preamble was
avoided; no installed live pytest guard was present. This is an integration
checkpoint, not qualification or deployment of v2026.9.24.

## September 28 release decisions

The final release reconciliation adopts upstream's model metadata, including
the 900K opt-in fallback for GPT-6 Sol and Astra. The temporary fork-only 890K
cap is retired by explicit operator choice; base slugs still use 272K and
lower live catalog limits remain authoritative. This is adoption of upstream
behavior, not a new full-window provider qualification.

Native compaction uses upstream's official-Codex-OAuth-only gate for exact
Astra. The earlier provider probe established OAuth support, not direct API
support, so the unsubstantiated direct-API extension is retired. Exact-model
threshold configuration remains available on eligible routes. Local Hermes
compression remains the fallback on ineligible routes.

The process registry is byte-identical to this upstream release: its shared
reader-finalization helper supersedes the fork's inline EOF fix. W&B/Fable
pricing and attribution, session-database selection, durable-write guards,
and the no-write/ownership learning policy remain additive local deltas.
Upstream's new memory matching and approval-result contracts are retained.

The approved candidate regression run exercised 64 files on Python 3.11:
1504 passed, zero failed, five skipped. It includes real request construction
for OAuth model-specific thresholds and rejection coverage for direct API,
untrusted relays, and unsupported Astra aliases. Historical checks below are
not evidence for the entire newer upstream release.

## Final release corrections

The expanded gate exercised 78 files: 1,630 passed, zero failed, 16 skipped.
A subsequent focused run covered withdrawal of a category-qualified skill-name
convenience change; review found it widened evidence-path acceptance. The existing
fail-closed name guard and its tests are restored unchanged.

The retained insights API now holds SessionDB's writer lock around its snapshot;
a concurrent-writer reproduction failed before the fix. Live threshold removal
now clears the override rather than inventing a 200K override. Missed fork CI
runner guards and stale autoraise documentation are corrected.

A copied empty-profile database exposed an upstream FTS migration failure:
`executescript()` discarded the savepoint before release. The existing
transactional DDL helper now preserves that savepoint; a fresh empty-index
regression reproduced the failure first. This is an upstream candidate, not
fork policy. Nonempty and empty real-state snapshots both migrated with preserved
row counts and remained readable by the previous code. Publication of this fix
upstream remains a separate action.

## Historical verification and limits

The expanded Python run exercised 56 files: 1335 passed, 6 skipped, zero failures,
using an isolated candidate environment on the production Python 3.11 version.
The preceding 54-file run also passed on Python 3.13. Coverage includes fork regressions plus
neighboring upstream config, approval, memory, background review, prompt, and
TUI hot-reload tests and both neighboring upstream system-prompt files. Separate
downstream WebUI startups used the candidate Python 3.11 and 3.13 environments,
empty disposable state, and private loopback ports; three deep health checks
passed on each, and the process groups exited. These are not full-suite,
authenticated-conversation, exact-production-dependency, or deployment claims.
Desktop regressions passed (62 tests across four files), and renderer typecheck
passed. New timestamp, model-selection, worker-evidence, and prompt regressions
failed before their fixes. The ledger cleanup test also failed with the actual
unlink operation disabled. Release evidence holds exact commands and later
verification results; do not infer coverage from counts alone.

Rollback: before activation retain the known-good source pair, dependency
requirements/environment, and supported state/config backups. Stop affected
runtimes through their existing lifecycle owner before restoring code or
dependencies. Do not replay uncertain pending writes or automatically restore
state that may contain newer work. Reverting the merge alone is not a complete
operational rollback.

Reclassification trigger: upstream equivalents replace the residual delta only
after its behavioral contract and downstream consumers are verified. This record
adds no scheduler, automatic conflict fixer, deployment daemon, or recovery API.
