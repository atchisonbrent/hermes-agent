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
reviewer. Automatic review completes within the calling persistence tool, using
the existing pending store. Its result includes `saved`, `review_state`, and a
specific message; staging is not reported as completed persistence. This trades
background continuation during that one call for reliable outcome delivery on
all tool surfaces. Other sessions and writers remain unblocked during inference.

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
120-second transport deadline and two active reviewers per process. The generic
`timeouts.tools.sequential_call` and `timeouts.tools.concurrent_batch` deadlines
must exceed that review time plus local I/O; their 420-second defaults do. Shorter
configured tool deadlines or user interruption may abandon a still-running tool
with unknown effects. Such a result requires record/target reconciliation, never
an automatic retry. This feature does not override configured timeouts.
The endpoint
does not support an output-token cap; none is promised. Input is bounded by the
configured byte limit, including instructions (default 64 KiB; range 1–128 KiB).
Malformed values fail closed; blocked results name the configuration key, never
its value. Unexpected parser failures retain the generic refusal message.

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
  Sequential dispatch captures evidence at batch entry, so earlier tool results
  from that same batch are not yet available. Concurrent calls capture at their
  own entry and may see already-committed sibling results. Missing evidence
  never authorizes an automatic write. Non-text tool results (images/audio) are
  omitted as whole results and counted, without discarding earlier human text.
  Multimodal human messages retain their verbatim text parts with an explicit
  omitted-part count; image/audio contents are never inferred.
- Cron, delegated, and dispatcher-owned Kanban goals are not human testimony. Background candidate authors
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
Configuration is intentionally re-read when staging, not cached from the initial
gate check. Disabling review between those reads leaves a human-staged proposal,
not permission to apply it without review. The extra local read is preferred to
passing stale authorization through the staging boundary.
Copied origin/read-mark context preserves background skill ownership guards.

The pending record is claimed before review and fenced as `applying` before any
side effect. No startup scanner or automatic retry replays old approvals.
Interrupted or uncertain `applying` records require target inspection and discard;
manual approval cannot replay them. This is not a crash-atomic multi-file
filesystem transaction.

Successful automatic writes and automatic rejections move to compact receipts under
`pending/<subsystem>/receipts/`, with decision, model, hashes and returned usage.
Other outcomes remain visible through `/memory pending` or `/skills pending`,
and are returned directly to the invoking model. Receipts and pending records
retain the originating agent session/platform when available. Process death or
transport cancellation can still interrupt response delivery: inspect the exact
record, receipt and target before retrying; no automatic replay is introduced.
Busy reviewer slots produce an explicit deferred reason without a model call.
`saved` is the persistence authority: true for applied, false for known non-writes,
null for uncertain application/receipt state. `success` can still describe valid
manual staging and is not a substitute for `saved`. Pending CLI lists show the
review state and reason. Background-review action summaries include refusals as
well as applied outcomes, subject to the existing notification-mode setting and
surface callback; no new cross-surface notification service is introduced.
Unattended background memory deletion/replacement remains explicitly manual-only,
even when the automatic reviewer accepts; it cannot bypass that existing guard.
Manual approval can override ready, reviewing, accepted, or deferred proposals;
a separate `<subsystem>.write_approval: true` still requires human approval for
accepted proposals. Rejection is terminal even with that human gate enabled:
it remains in receipts, not the pending queue. A human may author a new proposal;
the rejected proposal is not implicitly recoverable via the pending CLI.

## Boundaries

Direct callers without captured source evidence (including Desktop onboarding
personalization) defer rather than bypass this gate. Onboarding cannot claim
those facts were saved; manual proposal approval remains necessary. This is an
existing integration limitation, not authority to fabricate human evidence.

This is not an OS sandbox. Shell/file writes, external plugin stores, and
repository-managed/shared skill publication retain their existing controls.
Shared owners are not automatically writable under a profile-local lock.
Symlinked profile-home paths also require human review; the deferred pending
record names that reason, and no automatic reviewer is started. This deliberately
preserves the existing trust boundary rather than following a new owner.
Large owner packages and ambiguous evidence may still require manual review;
there is no periodic queue sweeper or escalating reviewer committee.

Conservative secret detection can defer documentation containing credential-like
assignments. It cannot identify every arbitrary unlabeled secret. Whole-config
versioning intentionally defers even on unrelated concurrent config changes.
Accepted/applied reviewed writes do not refresh an active conversation's frozen prompt or toolset,
and remain builtin-only: outcome delivery does not enable external-provider mirroring. Native Windows locking requires
platform-specific validation; unsupported locking defers automatic review.
Windows lock contention is distinct from unsupported locking: the inherited
`msvcrt` lock has a bounded native retry and can raise `OSError` before a writer
enters its mutation body. The shared lock does not promise POSIX-style indefinite
waiting on Windows. Such a failure is not a completed write or an automatic
retry; native Windows contention/recovery validation remains outstanding.

Tests: `tests/tools/test_durable_write_review.py` and
`tests/tools/test_durable_review_evidence.py`, plus the existing memory, staging,
skill batch/provenance and background-review regression suites.
