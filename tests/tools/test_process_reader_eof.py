"""EOF on captured output must not announce completion of a live process."""
import io
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from tools.process_registry import ProcessRegistry, ProcessSession


def test_reader_waits_for_process_after_output_eof(monkeypatch):
    registry = ProcessRegistry()
    entered_wait = threading.Event()
    release = threading.Event()
    finished = []

    class Process:
        stdout = io.StringIO("")
        returncode = None

        def wait(self, timeout=None):
            entered_wait.set()
            if timeout is not None:
                raise subprocess.TimeoutExpired("synthetic still-running process", timeout)
            assert release.wait(3), "test failed to release process"
            self.returncode = 7
            return 7

    session = ProcessSession(id="eof-live", command="synthetic", process=Process())
    monkeypatch.setattr(registry, "_move_to_finished", lambda s: finished.append(s.exit_code))
    reader = threading.Thread(target=registry._reader_loop, args=(session,), daemon=True)
    reader.start()
    try:
        assert entered_wait.wait(2)
        # A timed wait is not process-exit evidence. This synchronization avoids
        # a five-second sleep while reproducing the old EOF/timeout path.
        reader.join(0.05)
        assert not session.exited
        assert not finished
    finally:
        release.set()
        reader.join(3)
    assert not reader.is_alive()
    assert session.exited
    assert session.exit_code == 7
    assert finished == [7]


@pytest.mark.parametrize('poll_raises', [False, True])
def test_wait_failure_without_exit_evidence_is_not_completion(monkeypatch, poll_raises):
    registry = ProcessRegistry()
    finished = []

    def failed_wait():
        raise OSError('synthetic wait failure')

    def poll():
        if poll_raises:
            raise OSError('synthetic poll failure')
        return None

    process = SimpleNamespace(stdout=io.StringIO(''), returncode=None,
                              wait=failed_wait, poll=poll)
    session = ProcessSession(id='unknown-exit', command='synthetic', process=process)
    monkeypatch.setattr(registry, '_move_to_finished', lambda s: finished.append(s.id))
    registry._reader_loop(session)
    assert not session.exited
    assert not finished


@pytest.mark.parametrize('terminate', [False, True])
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX fd closure regression")
def test_real_child_closes_output_but_remains_running(tmp_path, monkeypatch, terminate):
    registry = ProcessRegistry()
    child = subprocess.Popen(
        [sys.executable, "-c", "import os,sys; os.close(1); os.close(2); sys.stdin.buffer.read(1); sys.exit(7)"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True,
    )
    session = ProcessSession(id="live-eof-child", command="synthetic fd closure", process=child)
    finished = []
    monkeypatch.setattr(registry, "_move_to_finished", lambda s: finished.append(s.exit_code))
    reader = threading.Thread(target=registry._reader_loop, args=(session,), daemon=True)
    reader.start()
    try:
        # Exercise the real old five-second timeout. A background-reader wait
        # is event-driven, not an agent polling or losing its notify workflow.
        reader.join(5.5)
        assert child.poll() is None
        assert not session.exited
        assert not finished
        if terminate:
            child.terminate()
        else:
            child.stdin.write("x")
            child.stdin.flush()
        reader.join(3)
        assert not reader.is_alive()
        expected = -15 if terminate else 7
        assert session.exit_code == expected
        assert finished == [expected]
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=3)
        reader.join(3)
        child.stdin.close()
        child.stdout.close()
