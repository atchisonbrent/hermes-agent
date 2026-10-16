"""Fork workflows must not request upstream provisioned runners by default."""
from pathlib import Path
import re
import os
import subprocess

from ruamel.yaml import YAML

_PAID = re.compile(r"(?:ubuntu|windows)-latest-32-(?:arm-)?core")
_GUARD = "github.repository == 'NousResearch/hermes-agent' && '"


def _unguarded(value):
    if isinstance(value, dict):
        return [item for child in value.values() for item in _unguarded(child)]
    if isinstance(value, list):
        return [item for child in value for item in _unguarded(child)]
    if not isinstance(value, str):
        return []
    return [match.group() for match in _PAID.finditer(value)
            if not value[:match.start()].endswith(_GUARD)]


def test_all_workflow_runner_literals_are_fork_guarded():
    root = Path(__file__).resolve().parents[2] / '.github/workflows'
    violations = {}
    for path in sorted(root.glob('*.y*ml')):
        findings = _unguarded(YAML(typ='safe').load(path))
        if findings:
            violations[path.name] = findings
    assert not violations, violations


def test_runner_guard_check_rejects_bare_and_wrong_repository_conditions():
    label = 'windows-latest-32-core'
    assert _unguarded({'runner': [label]}) == [label]
    assert _unguarded("${{ github.repository != 'NousResearch/hermes-agent' && '" + label + "' || 'windows-latest' }}") == [label]
    assert _unguarded('${{ ' + _GUARD + label + "' || 'windows-latest' }}") == []


def test_fork_upgrade_baseline_tracks_semver_after_calver(tmp_path):
    root = Path(__file__).resolve().parents[2]
    workflow = YAML(typ='safe').load(root / '.github/workflows/tests.yml')
    script = next(step['run'] for job in workflow['jobs'].values()
                  for step in job.get('steps', [])
                  if step.get('name') == 'Select upstream release baseline on forks')
    env = {**os.environ, 'GITHUB_ENV': str(tmp_path / 'github-env')}

    def git(*args):
        return subprocess.check_output(
            ['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', *args],
            cwd=tmp_path, env=env, text=True, timeout=30,
        ).strip()

    git('init', '-q')
    revisions = []
    for day, tag in enumerate(('v2026.9.1', 'v0.21.5', 'v0.22.0-rc.1', None), 1):
        env['GIT_AUTHOR_DATE'] = env['GIT_COMMITTER_DATE'] = f'2026-10-{day:02}T12:00:00Z'
        git('commit', '--allow-empty', '-qm', f'fixture {day}')
        revisions.append(git('rev-parse', 'HEAD'))
        if tag:
            git('update-ref', 'refs/upstream-release-tags/' + tag, revisions[-1])
    subprocess.run(['bash', '-e', '-c', script], cwd=tmp_path, env=env,
                   text=True, capture_output=True, timeout=30, check=True)
    assert (tmp_path / 'github-env').read_text() == f'HERMES_E2E_UPGRADE_BASE={revisions[1]}\n'
