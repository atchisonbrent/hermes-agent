# Stable 0.22.2 fork reconciliation

Classification: local-product-delta
Upstream base: NousResearch/hermes-agent v0.22.2, d923a5eb487a17c0a68801bba9ef0f56c81040a8
Fork base: a6125790755f911763c58486a084a3bbea0ec23f
Maintenance owner: fork maintainer
Rollback: retain the previous deployed tree and environment; do not restore state without assessing migrations and concurrent writes.
Upstream status: release reconciliation, not an upstream contribution.
Private details removed: yes.
Reclassification trigger: upstream supplies equivalent supported policy/extension
interfaces. Expected maintenance surface: runtime initialization, durable-write
evidence, profile routing, desktop reasoning and fork CI; no new service is added.

## Contract

Merge the stable release rather than cherry-picking or replacing the fork. Preserve durable-write review, exact-owner/source evidence, fail-closed application receipts, bounded reviewer capacity, serialized writes, configuration reference preservation, session database routing, pricing attribution, native compaction overrides and linked skill references.

Upstream modernizes type annotations, dependency management, runtime initialization, test fixtures, streaming approvals, and desktop speed settings. Textual conflict resolution is not acceptance: exercise both inherited fork behavior and affected upstream behavior.

## Resolution decisions

- Preserve the fork's no-write-is-valid skill-learning policy and owner selection while retaining upstream skill collision and availability handling.
- Preserve the insights snapshot API through upstream typing/refactoring.
- Retain the existing GPT-6.1 SOL dated picker variants and 900K opt-in ceiling. Live catalog caps remain authoritative; no live backend availability claim is inferred from picker tests.
- Combine per-run cancellation signals with upstream per-run approval routing. Preserve executor completion/answer persistence through disconnect.
- Preserve serialized durable writes and add the same lock to upstream's new memory span-patch operation. Retain upstream staged skill-patch preview helpers.
- Preserve session-owned reasoning. Upstream speed/serviceTier persistence and stale-write rollback remain, but global presets never store reasoning. Detached editor interfaces retain their existing capabilities.
- Preserve free standard fork CI runners while retaining upstream slicing and release inputs. Paid provisioned labels remain upstream-only. Retain explicit fork upgrade-baseline resolution.
- Move session-DB environment isolation into upstream's extracted fixture module. Retarget tests to actual defining modules rather than removed compatibility exports.
- Upstream replaces local-model query-cache and installer bootstrap fixtures; use the corresponding upstream tests instead of retaining obsolete atom/installer-stage fixtures. Existing synchronization regressions remain where their underlying API survives.
- Upstream migration-policy parametrization supersedes the old single `_run`-based test; retain the real active-and-sibling configuration migration check using the supported YAML library.

## Qualification boundaries

Review remediation keeps SQL snapshot reads under the database lock but performs
pricing resolution after releasing it. An external conversation database retains
its explicit profile home for prompt identity/skills; terminal children do not
inherit the conversation database pin. This is conversation-history routing, not
a general relocation of all profile-owned goal/delegation stores.

Curator and synthetic standing-goal prompts are not fresh human testimony.
Unknown provenance fails closed for durable writes without breaking unrelated
tool dispatch. Pending evidence and compact receipts use private POSIX modes.
Native threshold hot reload shares construction's normalization; an explicitly
present per-model null/invalid threshold means automatic, while removing that
entry restores global inheritance. Session-requested desktop effort remains
distinct from the route's effective wire effort, which the existing badge exposes.

Fork CI guards cover provisioned runner literals across workflows, and upgrade
baseline selection recognizes both stable CalVer and SemVer ancestors. No paid
runner provisioning or release publication is introduced.

Focused Python regression tests use the release's PM-built Python 3.14 test environment, per-file isolation, empty credential environment, deterministic locale/hash seed and native live-system guards. A host-local invocation skips only the shell runner's all-tree `compileall -j0` prepass and redirects the native per-file runner's scratch root to a task-owned directory; it does not modify test behavior or skip failures.

Desktop verification uses lockfile-installed workspace dependencies with lifecycle scripts disabled, targeted Vitest behavior suites and the project typecheck entrypoint. Actual command outcomes and independent review receipts belong to the release evidence, not guessed pass claims in this document.

Deployment requires separate coupled WebUI compatibility, profile/history preservation, dependency/runtime ABI verification, external idle-gated service restart and post-restart real chat checks. This source merge alone is not a deployment receipt. New upstream automatic session pruning must not silently change the installation's retention policy.
