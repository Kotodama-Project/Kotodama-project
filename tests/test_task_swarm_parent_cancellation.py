"""Synthetic pipes/signals only; no model/provider or Task state mutation."""
import os
from pathlib import Path
import signal
import sys
import threading

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs under the required Task swarm pytest job")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from task_swarm.cancellation import ParentCancellation
from task_swarm.protocol import SwarmError


@pytest.mark.skipif(os.name == "posix", reason="non-POSIX refusal")
def test_windows_refuses_before_opening_or_owning_parent_state():
    with pytest.raises(SwarmError) as raised:
        with ParentCancellation(-1):
            pytest.fail("must refuse")
    assert raised.value.code == "POSIX_REQUIRED"


@pytest.mark.skipif(os.name != "posix", reason="POSIX Task runner only")
def test_parent_eof_requests_stop_and_scope_restores_signal_handlers():
    reader, writer = os.pipe()
    prior = signal.getsignal(signal.SIGTERM)
    try:
        scope = ParentCancellation(reader)
        with scope:
            assert not scope.event.is_set()
            with pytest.raises(SwarmError) as nested:
                with ParentCancellation(reader):
                    pytest.fail("signal ownership must remain exclusive")
            assert nested.value.code == "CANCELLATION_SCOPE_INVALID"
            os.write(writer, b"heartbeat")
            assert not scope.event.wait(.15)
            os.close(writer)
            writer = None
            assert scope.event.wait(2) and scope.reason == "parent_eof"
        assert signal.getsignal(signal.SIGTERM) == prior
        assert not scope._thread.is_alive()
        # The scope closes only its duplicate, not the caller's descriptor.
        os.fstat(reader)
    finally:
        os.close(reader)
        if writer is not None:
            os.close(writer)


@pytest.mark.skipif(os.name != "posix", reason="POSIX Task runner only")
@pytest.mark.parametrize("number,reason", [(signal.SIGTERM, "sigterm"), (signal.SIGINT, "sigint")])
def test_owned_signal_requests_cancellation_without_abrupt_exit(number, reason):
    reader, writer = os.pipe()
    try:
        with ParentCancellation(reader) as scope:
            os.kill(os.getpid(), number)
            assert scope.event.wait(2) and scope.reason == reason
        assert not scope._thread.is_alive()
    finally:
        os.close(reader)
        os.close(writer)


@pytest.mark.skipif(os.name != "posix", reason="POSIX Task runner only")
def test_regular_file_and_worker_thread_cannot_acquire_signal_ownership(tmp_path):
    filename = tmp_path / "input"
    filename.write_bytes(b"synthetic")
    with filename.open("rb") as stream, pytest.raises(SwarmError) as raised:
        with ParentCancellation(stream.fileno()):
            pytest.fail("must refuse")
    assert raised.value.code == "PARENT_PIPE_REQUIRED"
    reader, writer = os.pipe()
    errors = []
    def enter():
        try:
            with ParentCancellation(reader):
                pass
        except SwarmError as error:
            errors.append(error.code)
    thread = threading.Thread(target=enter)
    try:
        thread.start()
        thread.join(timeout=2)
        assert errors == ["CANCELLATION_SCOPE_INVALID"]
    finally:
        os.close(reader)
        os.close(writer)
