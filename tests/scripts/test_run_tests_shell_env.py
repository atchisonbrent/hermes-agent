"""The real shell entrypoint forwards explicit test controls, not ambient env."""
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.name == "nt" or shutil.which("bash") is None, reason="POSIX shell entrypoint")
@pytest.mark.parametrize("baseline", [None, "refs/upstream-release-tags/v2026.9.24"])
def test_upgrade_baseline_survives_clean_shell_environment(tmp_path, baseline):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=10)
    probe = tmp_path / "compile_probe.py"
    probe.write_text("pass\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "compile_probe.py"], check=True, timeout=10)
    source = Path(__file__).resolve().parents[2] / "scripts" / "run_tests.sh"
    shutil.copy2(source, scripts / "run_tests.sh")
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "activate").touch()

    python = venv_bin / "python"
    python.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n', encoding="utf-8")
    python.chmod(0o755)
    (scripts / "run_tests_parallel.py").write_text(
        'import json, os\nprint(json.dumps({k: os.environ.get(k) for k in '
        '["HERMES_E2E_UPGRADE_BASE", "HERMES_TEST_NOT_ALLOWED"]}))\n',
        encoding="utf-8",
    )
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ, HOME=str(home), HERMES_TEST_NOT_ALLOWED="sentinel")
    env.pop("HERMES_E2E_UPGRADE_BASE", None)
    if baseline is not None:
        env["HERMES_E2E_UPGRADE_BASE"] = baseline
    result = subprocess.run(
        ["bash", str(scripts / "run_tests.sh")], env=env,
        capture_output=True, text=True, timeout=30, check=True,
    )
    observed = json.loads(result.stdout.splitlines()[-1])
    assert observed == {"HERMES_E2E_UPGRADE_BASE": baseline, "HERMES_TEST_NOT_ALLOWED": None}
