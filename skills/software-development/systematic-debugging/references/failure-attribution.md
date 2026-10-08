# Attributing a failing check

Use when deciding whether a failure is introduced, pre-existing, environmental,
or still unexplained. Work within the task's execution authority; a request for
inspection does not authorize dependency changes or executing untrusted code.

1. Read the error first. Missing tools, missing test paths, empty collection,
   permissions, and unavailable services describe a failed experiment, not a
   verdict on the implementation. Preserve the observed failure before repair.
2. Name the question and baseline commit. A merge-base is useful for a change
   comparison; a target tip answers whether that target currently fails. Neither
   is automatically the relevant deployed version. Record what was actually
   tested; do not relabel an old commit as current main.
3. Use `terminal` to create a separate detached worktree or disposable clone at
   that explicit commit, following the workspace's placement rules. Verify the
   control's commit with `git rev-parse HEAD` and cleanliness with
   `git status --porcelain`. Never stash, check out, reset, or clean the candidate
   tree to manufacture a control. If isolation is unavailable, leave attribution
   inconclusive rather than mutate somebody else's work.
4. First reproduce on the candidate using the selection intended for comparison.
   If the narrowed test passes but the full run fails, preserve the order/setup
   needed to reproduce; a narrowed green baseline is not a comparable control.
   Run the same command, flags, fixtures and relevant external conditions on both
   sides through the repository's runner. Record runtime/dependency identities,
   not secret environment values. A clean checkout can lack ignored build inputs.
   If dependency locks differ, use separate compatible environments and report
   that difference; do not alter the candidate's environment for the baseline.
5. Compare named tests and failure signatures, not just totals. Capture both
   exit statuses and decisive output. Repeat both sides when flakiness is plausible
   or report inconclusive attribution; do not retry only until one side is green.

| Observation under comparable conditions | Supported conclusion |
|---|---|
| Same failure on both | Reproduced on baseline; candidate may still worsen it or introduce another defect |
| Baseline passes, candidate fails | Candidate-associated; investigate the cause before assigning blame |
| Different failure or mismatched environment | Attribution remains inconclusive |
| Test exists only on candidate | Not automatically candidate-caused; it may expose an old defect or have a bad expectation |

For a branch-only test, a minimal test-only overlay on baseline code can be useful
when safe and compatible. Record that the control is now modified, identify the
overlay, and keep it separate from the originally clean baseline. An incompatible
new API or unavailable fixture leaves that comparison inconclusive. A failure on
baseline code still does not distinguish an old bug from a faulty test by itself.

Report candidate identity, baseline identity, compared selection, result and
limitations together. For dirty candidates include relevant tracked changes and
untracked input identities. Recheck identities before reusing results; changed
relevant content needs fresh verification. Do not rebase automatically, weaken a
test, or conceal a known failure because it is pre-existing. Stop when evidence is
sufficient for the stated attribution, not when every unrelated test is green.

## Worked decisions (illustrative, not measured results)

- Same test name but missing fixture on baseline: inconclusive, not "pre-existing".
- Both reproduce the same exception: baseline reproduction established; no blanket
  approval of the candidate follows.
- New test calls an API absent on baseline: incompatible control, not proof of a
  new implementation defect.
- One pass and one timeout under variable load: inconclusive without comparable
  repeated evidence; no retry-until-green verdict.
