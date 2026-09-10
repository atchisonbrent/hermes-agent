# Durable-write review

## Fork ownership

Classification: local-product-delta. The storage-tier acceptance policy and
Codex-only review route are intentionally local policy, not an upstream default.
Maintenance owner: fork maintainer. Update hazards: pending-write replay, tool
dispatch provenance, background-review prompts, and Codex auxiliary transport.
Rollback: set `durable_write_review.enabled: false` to stop automatic review;
retain subsystem write approval if human staging is desired. Revert the feature
commits for source rollback; do not replay uncertain pending applications.
Upstream base: `2e25b472108d0f36e02a95bae212255ae76fac0e`.
Upstream status: not-filed. Reconsider upstreaming the generic mechanism when a
supported proposal-review extension point or portable policy interface exists.
No additional service, periodic reviewer, or host sandbox is owned by this delta.

## Configuration

An opt-in, proposal-only gate for supported memory and profile-local skill writes.
Every acting model follows the same policy. Ordinary tasks do not invoke the
reviewer; staged proposals run asynchronously through the existing pending store.

```yaml
durable_write_review:
  enabled: true
  provider: openai-codex
  model: gpt-6-astra
  max_input_bytes: 65536
```

The reviewer model is configurable. This implementation supports the Codex OAuth
route only: no API endpoint, model fallback, virtual context-window alias, tools,
or autonomous rewrite. Each proposal makes at most one request, with a
120-second transport deadline and two active reviewers per process. The endpoint
does not support an output-token cap; none is promised. Input is bounded by the
configured byte limit, including instructions (default 64 KiB; range 1–128 KiB).

## What gets reviewed

- Exact proposed operations, complete current USER/MEMORY, and complete affected
  local skill packages, including supporting files.
- The complete current human message, a bounded contiguous suffix of earlier
  human messages, and recent attributable current-turn whole tool results.
  Earlier messages are verbatim antecedents, not assistant claims or generated
  summaries. Selection stops before an oversized earlier human message so a
  newer correction cannot be skipped in favor of an older preference. Omissions
  are declared. Runtime synthetic user-role messages are excluded using the
  existing human-message classifier. No full transcript replay, persistence-tool
  echo, or delegated-agent result. Messages already removed by compaction are
  not reconstructed; missing evidence still defers.
- Cron and delegated goals are not human testimony. Background candidate authors
  preserve the original source provenance rather than supplying their own prompt.

The reviewer accepts, rejects, or defers the entire proposal. Acceptance requires
valid source citations. Missing proof, malformed responses, unavailable OAuth,
oversized required files, detected secrets, symlinks, or external owners cannot
produce an automatic write. Full owner context is never silently truncated.

Storage policy: stable user preferences in USER; compact stable environment facts
and broadly useful pointers in MEMORY; validated recurring procedures or repairs
to demonstrated procedural defects in the existing skill owner. Detailed
architecture belongs in project docs; task results and incident receipts belong
in history/artifacts. Duplicates, speculative generalizations, and policy already
present in instructions do not warrant another write.

## Application and recovery

Supported writers share a reentrant thread/process lock. The model call holds no
write lock. Before application, the worker rechecks the exact payload, complete
context/file identities, and config version under that lock. Changed state
defers the proposal; existing validators and batch rollback remain authoritative.
Copied origin/read-mark context preserves background skill ownership guards.

The pending record is claimed before review and fenced as `applying` before any
side effect. No startup scanner or automatic retry replays old approvals.
Interrupted or uncertain `applying` records require target inspection and discard;
manual approval cannot replay them. This is not a crash-atomic multi-file
filesystem transaction.

Successful writes and rejections move to compact receipts under
`pending/<subsystem>/receipts/`, with decision, model, hashes and returned usage.
Other outcomes remain visible through `/memory pending` or `/skills pending`.
Busy reviewer slots produce an explicit deferred reason without a model call.
Manual approval can override ready, reviewing, accepted, or deferred proposals;
a separate `<subsystem>.write_approval: true` still requires human approval.

## Boundaries

This is not an OS sandbox. Shell/file writes, external plugin stores, and
repository-managed/shared skill publication retain their existing controls.
Shared owners are not automatically writable under a profile-local lock.
Large owner packages and ambiguous evidence may still require manual review;
there is no periodic queue sweeper or escalating reviewer committee.

Conservative secret detection can defer documentation containing credential-like
assignments. It cannot identify every arbitrary unlabeled secret. Whole-config
versioning intentionally defers even on unrelated concurrent config changes.
Accepted writes do not refresh an active conversation's frozen prompt or toolset,
and do not mirror into external memory providers. Native Windows locking requires
platform-specific validation; unsupported locking defers automatic review.

Tests: `tests/tools/test_durable_write_review.py` and
`tests/tools/test_durable_review_evidence.py`, plus the existing memory, staging,
skill batch/provenance and background-review regression suites.
