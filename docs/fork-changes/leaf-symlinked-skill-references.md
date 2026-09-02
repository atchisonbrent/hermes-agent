# Leaf-symlinked skill references

## Upstream Candidate

Classification: upstream-candidate
Upstream base: upstream/main (NousResearch/hermes-agent) at the fork's current reviewed baseline
Problem: `skill_view(name, file_path="references/…")` fails with `Path escapes allowed directory` for any skill installed as a wrapper directory whose individual files are symlinks into a canonical checkout (a Git-owned skills registry, a vendored submodule, or a versioned release cache). The skill's `SKILL.md` loads fine because skill discovery resolves symlinks, but its sibling `references/`, `templates/`, `assets/`, and `scripts/` files are refused, so the agent can see linked files exist and cannot read them.
Reproduction: create `canonical/skill/{SKILL.md,references/guide.md}`; create `~/.hermes/skills/cat/skill/` containing `SKILL.md -> canonical/skill/SKILL.md` and `references/guide.md -> canonical/skill/references/guide.md`; call `skill_view("skill", file_path="references/guide.md")`. See `tests/tools/test_skills_tool.py::TestSkillView::test_view_reads_leaf_linked_reference_in_managed_wrapper`.
Expected behavior: a leaf file that resolves into the canonical subtree that `SKILL.md` resolves into (the skill author's own published tree) is exactly as trusted as `SKILL.md` and should be readable.
Actual behavior: `validate_within_dir(target, skill_dir)` resolves the symlink and rejects it because the resolved path is outside the wrapper directory.
Root cause: `tools/path_security.validate_within_dir` follows symlinks before the containment check and has no notion of the canonical tree the skill was loaded from.
Change: add `tools.path_security.validate_within_dir_or_linked_root(path, root, canonical_root)`. It accepts the path when the strict check passes, or when (a) `path` itself is a symlink, (b) every ancestor of `path` resolves within `root` (so a symlinked *directory* still fails), and (c) the link target resolves within `canonical_root` (`SKILL.md.resolve().parent`). Both `skill_view` code paths (plugin-qualified and standard) use it. Directory-symlink layouts and links escaping the canonical tree remain rejected.
Verification: `.venv/bin/python -m pytest tests/tools/test_skills_tool.py tests/tools/test_credential_files.py tests/tools/test_cronjob_tools.py -q` → 158 passed, including three new test methods covering four scenarios: leaf link into the canonical subtree accepted; leaf link escaping the subtree rejected; reference reached through a symlinked directory rejected; leaf-linked reference beside a real (non-symlink) `SKILL.md` rejected. Symlink creation skips on platforms that forbid it. Live check: `skill_view("deep-research", file_path="references/research-modes.md")` now succeeds against the registry-managed wrapper.
Compatibility / risk: only widens acceptance for leaf symlinks whose target lies inside the subtree `SKILL.md` already resolved into; no change for skills whose `SKILL.md` is a real file. Both `skill_view` serving paths (standard and plugin-qualified) adopt the rule; `_plugin_skill_linked_files` still lists with the strict check, so a plugin wrapper using leaf links may serve a reference it does not list—an accepted discoverability asymmetry, not a trust widening. Other callers of `validate_within_dir` are untouched. The pre-existing validate-then-open window is unchanged.
Maintenance owner: Brent Atchison (fork `atchisonbrent/hermes-agent`)
Rollback: revert the commit; the strict check returns and linked references become unreadable again.
Upstream status: issue-ready
Private details removed: yes
