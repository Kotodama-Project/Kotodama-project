"""Hold the actual evidence descriptor across receipt publication."""
import ctypes
import hashlib
import os
from pathlib import Path
import sys
from types import SimpleNamespace

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

from task_swarm import task_runner
from task_swarm.loop_executor_runtime import ExecutorEvidence
from task_swarm.protocol import SwarmError


class NativeCall:
    def __init__(self, function):
        self.function = function

    def __call__(self, *args):
        return self.function(*args)


class ReaderOS:
    """Patch this reader's OS calls without changing pathlib or other threads."""
    def __init__(self, **overrides):
        self.__dict__.update(overrides)

    def __getattr__(self, name):
        return getattr(os, name)


@pytest.fixture(autouse=True)
def isolated_windows_api_binding():
    # Tests below replace WinDLL with different native-call models. Never
    # retain a fake binding into another case or the real Windows test suite.
    task_runner._windows_read_kernel.cache_clear()
    yield
    task_runner._windows_read_kernel.cache_clear()


def held_reader(monkeypatch, on_read):
    """Native Windows handles, or an explicit Win32 sharing model on POSIX."""
    descriptors, closed, reads = {}, [], []

    def legacy_open(path, flags):
        fd = os.open(path, flags)
        descriptors[fd] = (Path(path), False)
        return fd

    def close(fd):
        closed.append(fd)
        descriptors.pop(fd, None)
        os.close(fd)

    def read(fd, maximum):
        reads.append((fd, maximum))
        if len(reads) == 1:
            assert not os.get_inheritable(fd)
            on_read()
        return os.read(fd, maximum)

    reader_os = ReaderOS(open=legacy_open, read=read, close=close)
    if os.name != "nt":
        # This models the platform's sharing rule, not a native Windows result.
        # The baseline os.open denies delete; the new CreateFileW opts in.
        reader_os.name, reader_os.O_BINARY, reader_os.O_NOINHERIT = "nt", 0x8000, 0x80

        def create(path, access, share, security, creation, flags, template):
            assert (access, security, creation, flags, template) == (
                0x80000000, None, 3, 0x200080, None)
            fd = os.open(path, os.O_RDONLY)
            descriptors[fd] = (Path(path), bool(share & 0x4))
            return fd

        kernel = SimpleNamespace(CreateFileW=NativeCall(create), CloseHandle=NativeCall(close))
        monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **kw: kernel, raising=False)
        def transfer(handle, flags):
            assert flags == 0x8080
            return handle

        monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(open_osfhandle=transfer))

    def replace(source, target):
        if os.name != "nt" and any(path == source and not shared for path, shared in descriptors.values()):
            error = PermissionError(13, "modeled Windows sharing violation", str(source))
            error.winerror = 32
            raise error
        os.replace(source, target)

    monkeypatch.setattr(task_runner, "os", reader_os)
    return replace, descriptors, closed, reads


@pytest.mark.parametrize("tamper", [False, True])
def test_receipt_can_publish_while_monitor_holds_bounded_reader(tmp_path, monkeypatch, tamper):
    raw = b'{"receipt":"pinned"}\n'
    pending, final = tmp_path / ".receipt-pending.json", tmp_path / "receipt.json"
    pending.write_bytes(raw)
    evidence = ExecutorEvidence(tmp_path)
    evidence.pin_receipt(pending.name, hashlib.sha256(raw).hexdigest())
    published = []

    def publish():
        replace(pending, final)
        published.append(True)
        assert not pending.exists() and final.read_bytes() == raw
        if tamper:
            final.write_bytes(raw + b" ")

    # A synchronous hook fixes the interleaving while the real reader fd is
    # open; it needs no scheduler timing, worker-start wait or sleep.
    replace, descriptors, closed, reads = held_reader(monkeypatch, publish)
    if tamper:
        with pytest.raises(SwarmError, match="RUN_ARTIFACT_CHANGED"):
            evidence.check()
    else:
        evidence.check()
        assert final.read_bytes() == raw
    assert published == [True] and not descriptors
    assert len(closed) == 2  # pending descriptor, then the checked final path
    assert all(maximum <= 65536 for _, maximum in reads)


@pytest.mark.parametrize("failure", [None, "invalid", "transfer", "interrupt"])
def test_windows_reader_handle_abi_and_transfer_ownership(tmp_path, monkeypatch, failure):
    from ctypes import wintypes

    path, handle = tmp_path / "receipt.json", 0x123456789ABC
    calls, closed = [], []

    def create(*args):
        calls.append(args)
        return wintypes.HANDLE(-1).value if failure == "invalid" else handle

    kernel = SimpleNamespace(CreateFileW=NativeCall(create),
                             CloseHandle=NativeCall(lambda value: closed.append(value)))
    monkeypatch.setattr(ctypes, "WinDLL", lambda name, **kw: kernel, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 32, raising=False)
    monkeypatch.setattr(ctypes, "WinError", lambda code: OSError(code, "native open refused"), raising=False)

    def transfer(value, flags):
        assert (value, flags) == (handle, 0x8080)
        if failure == "transfer":
            raise OSError("transfer refused")
        if failure == "interrupt":
            raise KeyboardInterrupt
        return 7

    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(open_osfhandle=transfer))
    monkeypatch.setattr(task_runner, "os", ReaderOS(name="nt", O_RDONLY=0, O_BINARY=0x8000, O_NOINHERIT=0x80))
    if failure:
        with pytest.raises(KeyboardInterrupt if failure == "interrupt" else OSError):
            task_runner._open_readonly(path)
        assert closed == ([] if failure == "invalid" else [handle])
    else:
        assert task_runner._open_readonly(path) == 7 and closed == []
    assert calls == [(str(path), 0x80000000, 7, None, 3, 0x200080, None)]
    assert kernel.CreateFileW.argtypes == (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    assert kernel.CreateFileW.restype is wintypes.HANDLE
    assert kernel.CloseHandle.argtypes == (wintypes.HANDLE,)
    assert kernel.CloseHandle.restype is wintypes.BOOL


def test_windows_reader_reuses_api_binding_but_opens_each_current_file(tmp_path, monkeypatch):
    path = tmp_path / "proof.json"
    path.write_bytes(b"first")
    loads, opens = [], []

    def create(filename, access, share, security, creation, flags, template):
        assert (access, share, security, creation, flags, template) == (
            0x80000000, 7, None, 3, 0x200080, None)
        opens.append(filename)
        return os.open(filename, os.O_RDONLY)

    kernel = SimpleNamespace(CreateFileW=NativeCall(create), CloseHandle=NativeCall(os.close))

    def load(name, **options):
        loads.append((name, options))
        return kernel

    monkeypatch.setattr(ctypes, "WinDLL", load, raising=False)
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(open_osfhandle=lambda handle, flags: handle))
    monkeypatch.setattr(task_runner, "os", ReaderOS(name="nt", O_BINARY=0x8000, O_NOINHERIT=0x80))
    assert task_runner.read_bytes(path) == b"first"
    path.write_bytes(b"second")
    assert task_runner.read_bytes(path) == b"second"
    assert opens == [str(path), str(path)]
    assert loads == [("kernel32", {"use_last_error": True})]


@pytest.mark.parametrize("change", ["oversize", "hardlink", "append", "replace", "read_error"])
def test_bounded_reader_keeps_refusals_and_closes_descriptor(tmp_path, monkeypatch, change):
    path = tmp_path / "evidence.json"
    raw = b'{"value":1}\n'
    path.write_bytes(raw)
    if change == "hardlink":
        os.link(path, tmp_path / "other-link")
    calls, closed = [], []

    def read(fd, maximum):
        calls.append(maximum)
        if change == "read_error":
            raise OSError("read unavailable")
        value = os.read(fd, maximum)
        if len(calls) == 1:
            if change == "append":
                with path.open("ab") as stream:
                    stream.write(b" ")
            elif change == "replace":
                os.replace(path, tmp_path / "moved")
                path.write_bytes(raw)
        return value

    def close(fd):
        os.close(fd)
        closed.append(fd)

    monkeypatch.setattr(task_runner, "os", ReaderOS(read=read, close=close))
    expected = "RUN_FILE_REFUSED" if change in {"oversize", "hardlink"} else "RUN_FILE_CHANGED"
    with pytest.raises(OSError if change == "read_error" else SwarmError) as raised:
        task_runner.read_bytes(path, len(raw) - 1 if change == "oversize" else len(raw))
    if change != "read_error":
        assert raised.value.code == expected
    assert len(closed) == 1
    with pytest.raises(OSError):
        os.fstat(closed[0])
    if change in {"oversize", "hardlink"}:
        assert calls == []


def test_reparse_point_is_refused_before_open(tmp_path, monkeypatch):
    path = tmp_path / "receipt.json"
    path.write_bytes(b"{}")
    info = path.lstat()
    original = Path.lstat
    monkeypatch.setattr(Path, "lstat", lambda current: SimpleNamespace(
        st_mode=info.st_mode, st_file_attributes=0x400) if current == path else original(current))
    monkeypatch.setattr(task_runner, "_open_readonly", lambda *a: pytest.fail("reparse point was opened"))
    with pytest.raises(SwarmError, match="RUN_FILE_REFUSED"):
        task_runner.read_bytes(path)


def test_exact_byte_limit_remains_bounded_and_non_inheritable(tmp_path, monkeypatch):
    path, raw = tmp_path / "proof", b"x" * (65536 + 3)
    path.write_bytes(raw)
    calls = []

    def read(fd, maximum):
        assert not os.get_inheritable(fd)
        calls.append(maximum)
        return os.read(fd, maximum)

    monkeypatch.setattr(task_runner, "os", ReaderOS(read=read))
    assert task_runner.read_bytes(path, len(raw)) == raw
    assert calls == [65536, 4, 1]
