"""Exercise real child outcomes and distinguish process exit from pipe EOF."""
import json
from pathlib import Path
import subprocess
import sys
from unittest import mock

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

from tools.pytest_ci_process_probe import Probe, process_state


def events(directory):
    return [json.loads(line) for line in (directory / "events.jsonl").read_bytes().splitlines()]


@pytest.mark.parametrize("text", [True, False])
def test_success_input_output_and_nonzero_status_remain_subprocess_results(tmp_path, text):
    probe = Probe(tmp_path / "probe")
    original = subprocess.Popen.communicate

    def observed(process, input=None, timeout=None):
        return probe.communicate(original, process, input, timeout, label="fixture")

    payload = "PRIVATE_INPUT_SENTINEL" if text else b"PRIVATE_INPUT_SENTINEL"
    with mock.patch.object(subprocess.Popen, "communicate", observed):
        with pytest.raises(subprocess.CalledProcessError) as caught:
            subprocess.run([sys.executable, "-c", "import sys;sys.stdout.write(sys.stdin.read());sys.exit(7)"],
                input=payload, text=text, capture_output=True, timeout=10, check=True)
    probe.close()
    assert caught.value.returncode == 7 and caught.value.stdout == payload
    rows = events(tmp_path / "probe")
    assert rows[-1]["outcome"] == "completed" and rows[-1]["returncode"] == 7
    assert "PRIVATE_INPUT_SENTINEL" not in (tmp_path / "probe/events.jsonl").read_text()


def test_running_child_timeout_is_preserved_and_run_still_reaps_child(tmp_path):
    probe = Probe(tmp_path / "probe")
    original = subprocess.Popen.communicate
    owned = []

    def observed(process, input=None, timeout=None):
        owned.append(process)
        return probe.communicate(original, process, input, timeout, label="fixture")

    with mock.patch.object(subprocess.Popen, "communicate", observed):
        with pytest.raises(subprocess.TimeoutExpired) as caught:
            subprocess.run([sys.executable, "-c", "import time;time.sleep(10)"],
                capture_output=True, timeout=.1)
    probe.close()
    assert caught.value.timeout == .1
    assert owned[0].poll() is not None
    rows = events(tmp_path / "probe")
    timed_out = next(row for row in rows if row["kind"] == "timeout")
    assert timed_out["state"]["returncode"] is None
    assert any(row.get("outcome") == "timeout" for row in rows)


def test_exited_root_with_inherited_pipe_is_distinct_from_running_child(tmp_path):
    probe = Probe(tmp_path / "probe")
    # The grandchild inherits stdout/stderr and outlives its root. Waiting for
    # the root first establishes exit independently of communicate's pipe EOF.
    release = tmp_path / "release-grandchild"
    grandchild = (
        "import pathlib,time\n"
        f"release = pathlib.Path({str(release)!r})\n"
        "deadline = time.monotonic() + 30\n"
        "while not release.exists() and time.monotonic() < deadline:\n"
        "    time.sleep(.01)\n"
    )
    script = f"import subprocess,sys;subprocess.Popen([sys.executable,'-c',{grandchild!r}])"
    process = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert process.wait(timeout=10) == 0
        with pytest.raises(subprocess.TimeoutExpired):
            probe.communicate(subprocess.Popen.communicate, process, timeout=.05, label="fixture")
    finally:
        release.touch()
        process.communicate(timeout=10)
        probe.close()
    timed_out = next(row for row in events(tmp_path / "probe") if row["kind"] == "timeout")
    assert timed_out["state"]["returncode"] == 0
    assert timed_out["state"]["counters"] is None
    if sys.platform == "win32":
        assert timed_out["state"]["stdout_reader_alive"] is True


def test_diagnostic_failure_does_not_replace_child_outcome(tmp_path):
    probe = Probe(tmp_path / "probe")
    process = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(10)"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with mock.patch("tools.pytest_ci_process_probe.process_state", side_effect=OSError("PRIVATE_ERROR")):
            with pytest.raises(subprocess.TimeoutExpired):
                probe.communicate(subprocess.Popen.communicate, process, timeout=.1, label="fixture")
    finally:
        process.kill()
        process.communicate(timeout=10)
        probe.close()
    summary = json.loads((tmp_path / "probe/summary.json").read_bytes())
    assert summary["complete"] is False and summary["incomplete_reason"] == "sample_failed"
    assert "PRIVATE_ERROR" not in (tmp_path / "probe/events.jsonl").read_text()


@pytest.mark.parametrize("times_out", [False, True])
def test_timer_start_failure_preserves_child_result_and_reaping(tmp_path, times_out):
    probe = Probe(tmp_path / "probe")
    original = subprocess.Popen.communicate
    owned = []

    def observed(process, input=None, timeout=None):
        owned.append(process)
        return probe.communicate(original, process, input, timeout, label="fixture")

    script = "import time;time.sleep(10)" if times_out else "print('child completed')"
    with mock.patch("tools.pytest_ci_process_probe.threading.Timer.start",
            side_effect=RuntimeError("PRIVATE_THREAD_ERROR")):
        with mock.patch.object(subprocess.Popen, "communicate", observed):
            if times_out:
                with pytest.raises(subprocess.TimeoutExpired) as caught:
                    subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=.1)
                assert caught.value.timeout == .1
            else:
                result = subprocess.run([sys.executable, "-c", script],
                    capture_output=True, text=True, timeout=10, check=True)
                assert result.stdout.strip() == "child completed"
    probe.close()
    assert owned[0].poll() is not None
    summary = json.loads((tmp_path / "probe/summary.json").read_bytes())
    assert summary["complete"] is False and summary["incomplete_reason"] == "timer_setup_failed"
    assert "PRIVATE_THREAD_ERROR" not in (tmp_path / "probe/events.jsonl").read_text()


def test_stream_close_failure_is_incomplete_observation(tmp_path):
    probe = Probe(tmp_path / "probe")
    stream = probe.stream
    probe.stream = mock.Mock(wraps=stream)
    probe.stream.close.side_effect = OSError("PRIVATE_CLOSE_ERROR")
    try:
        probe.close()
    finally:
        stream.close()
    summary = json.loads((tmp_path / "probe/summary.json").read_bytes())
    assert summary["complete"] is False and summary["incomplete_reason"] == "close_failed"
    assert "PRIVATE_CLOSE_ERROR" not in (tmp_path / "probe/summary.json").read_text()


def test_closed_stream_and_capacity_are_reported_without_raising(tmp_path):
    probe = Probe(tmp_path / "probe")
    probe.emit("bounded", value="x" * (128 * 1024))
    probe.close()
    assert (tmp_path / "probe/events.jsonl").stat().st_size <= 128 * 1024
    summary = json.loads((tmp_path / "probe/summary.json").read_bytes())
    assert summary["incomplete_reason"] == "capacity_exceeded"


def test_exited_process_counters_are_not_borrowed_from_reused_pid():
    process = mock.Mock(pid=1, returncode=0, stdout_thread=None, stderr_thread=None)
    process.poll.return_value = 0
    with mock.patch("tools.pytest_ci_process_probe.psutil.Process") as inspect:
        assert process_state(process)["counters"] is None
    inspect.assert_not_called()
