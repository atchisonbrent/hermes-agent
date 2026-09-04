# Fork change record: selective recovery

Maintenance owner: fork maintainer. Upstream status: not-filed. Private details
removed: yes. This is a retained fork release, not an upstream PR or proof of
compatibility with current upstream HEAD. Prepare separate logical upstream PRs
from a freshly fetched upstream base and rerun their tests before contribution.

Release baseline: `f95511365227b3f39550ff665aadd954a9906892` (owned fork main).
The original retained sequence is `58ca6bd42a` then `691bf22139`. Earlier reviews
covered staged candidates; subsequent fixture/comment edits were not re-reviewed
under the stricter fork policy. Publication review therefore covers the complete
final range and this ownership record. Existing history is not relabeled as
having followed a gate it missed.

## Output EOF is not process exit

Classification: upstream-candidate.
Problem / actual behavior: a captured process closes stdout but keeps running;
a timed wait expires and the registry falsely reports completion with no exit
code. Expected behavior: completion requires evidence of actual process exit.
Root cause: `_reader_loop` unconditionally finalized after `wait(timeout=5)`.
Change: wait for actual exit in the existing reader; on wait/poll failure retain
unknown status rather than manufacturing completion.
Reproduction / verification: `tests/tools/test_process_reader_eof.py` uses a real
child that closes output, stays alive beyond five seconds, then exits 7 or is
terminated; also exercises wait/poll failures. Run with the process-registry
suite through the bounded per-file runner (`-j 1`); systemd-only tests are not
applicable on macOS.
Compatibility / risk: no PTY-loop redesign, new polling loop, or durability
promise. Existing PTY EOF and registry-locking concerns are not fixed here.
Rollback: revert `58ca6bd42a` in a separately tested release; false completion
behavior returns. Upstream base: derive the current upstream merge base before
filing; this fixture was qualified on the fork baseline above.

## Shared reference-save policy seam

Classification: upstream-candidate.
Problem: a downstream WebUI config save must retain reference-owned credentials
across rotation without duplicating the core's named-list traversal.
Expected: default CLI editing unchanged; an optional caller policy can preserve
raw references; reordered unique names keep identity; ambiguous naming fails
closed when a policy is supplied.
Root cause: expanded data loses source-reference ownership at the consumer write
boundary; existing traversal had no consumer-specific string policy.
Change: optional keyword-only `string_policy(current, raw, field)` in
`_preserve_env_ref_templates`; `None` retains default semantics.
Reproduction / verification: `tests/test_config_reference_policy.py`,
`tests/hermes_cli/test_config_env_refs.py`, and
`tests/hermes_cli/test_config_env_ref_parity.py`, plus the paired WebUI rotation,
identity, and incompatible-companion tests.
Compatibility / risk: private helper coupling must be checked at each update.
Rollback: roll back the dependent WebUI save consumer before removing this hook;
otherwise its save path deliberately fails closed. Upstream base: fork baseline
above; refresh and review the public API choice before filing.

## Skill-loading and learning policy

Classification: local-product-delta.
Rationale: retained operating preference favors governing-skill selection and
validated durable learning, not skill creation for its own sake. It is not
silently presented as an upstream defect.
Change: prompt guidance makes a justified no-write outcome valid and assigns
stable preferences to user memory, recurring procedures to skills.
Verification: `tests/test_context_learning_policy.py` and
`tests/run_agent/test_review_prompt_class_first.py`. These check instructions,
not measured improvement across models or long-running sessions.
Update hazard / rebase surface: `agent/prompt_builder.py` and
`agent/background_review.py`; preserve safety and compaction-pruning guidance.
Rollback: restore these prompt files from the baseline in a reviewed change;
retain the separate config hook if the WebUI consumer still depends on it.
Reclassification trigger: upstream accepts equivalent policy or provides a
supported configuration seam; then remove or rebase only the residual delta.

## Publication qualification

No new runtime implementation is introduced by this record. Final publication
must verify the full range, deterministic regressions, independent final-tree
review, and the exact remote branch SHA. Test totals and publication receipts
belong to the release evidence, not a claim that every platform was exercised.
