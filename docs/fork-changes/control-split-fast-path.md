# Fast path for control-split token misses

## Upstream Candidate

Classification: upstream-candidate
Product base: `origin/main` at `f5d9b40daa9854b46d3dddae4f3d8996fc6a52db`
Upstream comparison: `upstream/main` at `53a6ced422214d07255302a5b900c313af3b677a` (the same eager index-map construction remains)
Problem: redaction of large log-like text evaluates the control-character regex and allocates an original-index entry for every source character before it knows whether any control-split token exists.
Reproduction: call `_mask_control_split_tokens()` with text containing a control character and a known prefix that does not form a valid token. Observe one regex `.match()` invocation per character despite there being no match to mask.
Expected behavior: preserve every masked result exactly, including the first valid token and repeated records, while avoiding irrelevant per-character index-map work.
Actual behavior: a no-match result can require a Python and regex pass over every character of a large text field.
Root cause: `_mask_control_split_tokens()` builds `orig_idx` and the output character list before enumerating the prefix matches, including when no prefix match exists.
Change: peek at the first prefix match before allocating `orig_idx`. Return immediately if there is no match. Otherwise, use `itertools.chain((first_match,), matches_iter)` so the first match retains its place and is neither dropped nor duplicated.
Verification:
- The new no-match regression failed on the unmodified base: the control regex was called for each of 29 characters; the genuine matched-token regression passed there.
- `scripts/run_tests.sh tests/agent/test_control_split_index_map.py tests/agent/test_redact.py tests/gateway/test_pii_redaction.py tests/e2e/core/security/test_secret_redaction.py tests/e2e/core/security/test_secret_redaction_gateway.py tests/monitoring/test_export_redaction.py tests/cron/test_cron_delivery_redaction.py -q`: 290 passed after strengthening the multi-token controls. Exact output, callback order/count, intervening prose, and a rejected first match followed by a valid match are covered.
- `python scripts/check`: all 12 checks passed, with zero blocking and zero advisory health findings for the changed Python files.
- In the isolated paired projection-equivalence run, output equality was required and held for every object: 5,889 retained messages and 3,902 tool calls were preserved. The measured projection time improved from 13,235.9 ms to 11,517.7 ms. This is a single-run observation, not a latency guarantee.
- The same frozen-input full public projection produced an identical result under the maintained current-version and optimized implementations. No model/provider execution, configuration preferences, or redaction policy changes are involved.
Compatibility / risk: affects only the allocation and early return order of an existing private redaction helper. Successful matches use the original mapping and substitution logic. Partial prefixes, zero-width separators, newlines, empty strings and repeated inputs retain the existing guards. It does not expand or disable any secret pattern, shorten history, bypass redaction, or select a different model/provider.
Maintenance owner: Brent Atchison / fork maintainers. The expected maintenance surface is the one helper and its focused tests. This is not a preference change or an experiment.
Rollback: revert this change. The previous slower behavior is the fallback; it has identical output semantics. Deployment must continue to use the existing approved drain and pinned-source procedures rather than modifying a live checkout in place.
Upstream status: issue-ready, not filed. The affected function is also present at the compared upstream revision, so this is a separable performance improvement suitable for an upstream discussion rather than a merge of unrelated newer redaction behavior.
Private details removed: yes. No private paths, hostnames, credentials, transcript text, session identifiers or deployment-specific controllers are in this record or the regression fixtures.

## Evidence boundary

The large-session fixture is private and is not included in the repository. Reviewable deterministic controls use public synthetic prefixes already present in the Agent's own redaction matcher. Performance measurements are representative of that input rather than a guarantee for every profile or machine. Isolated profiling used real function calls, exception-free controls and valid per-thread stack sampling. Empty profile files, sanitized output alone, or exit codes without a meaningful positive control were not treated as evidence.
