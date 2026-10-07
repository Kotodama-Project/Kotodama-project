"""One POSIX task-runner lifetime: parent pipe and signals request cancellation.

This requests a stop only. The Task owner must fence publication and observe the
owned process group before recording cancelled rather than uncertain.
"""
from __future__ import annotations

import os
import select
import signal
import socket
import stat
import threading

from .protocol import SwarmError

_active_scope = None


class ParentCancellation:
    def __init__(self, parent_fd: int = 0) -> None:
        self.parent_fd = parent_fd
        self.event = threading.Event()
        self.reason: str | None = None
        self._done = threading.Event()
        self._fd: int | None = None
        self._thread: threading.Thread | None = None
        self._handlers: dict[int, object] = {}

    def request(self, reason: str) -> None:
        if self.reason is None:
            self.reason = reason
        self.event.set()

    def _signal(self, number, _frame) -> None:
        self.request("sigterm" if number == signal.SIGTERM else "sigint")

    def _watch(self) -> None:
        try:
            while not self._done.is_set() and not self.event.is_set():
                if select.select([self._fd], [], [], .1)[0] and not os.read(self._fd, 1024):
                    self.request("parent_eof")
        except (OSError, ValueError):
            if not self._done.is_set():
                self.request("parent_read_failed")

    def __enter__(self) -> "ParentCancellation":
        global _active_scope
        if os.name != "posix":
            raise SwarmError("POSIX_REQUIRED", "parent cancellation requires the POSIX Task runner")
        if threading.current_thread() is not threading.main_thread() or self._fd is not None or self._done.is_set() or _active_scope is not None:
            raise SwarmError("CANCELLATION_SCOPE_INVALID", "use one scope from the runner main thread")
        try:
            mode = os.fstat(self.parent_fd).st_mode
            connected_local_stream = False
            if stat.S_ISSOCK(mode):
                # Node/libuv implements child stdio pipes with socketpair.
                # Accept only an already-connected local byte stream, not an
                # internet listener, datagram, regular file or terminal.
                with socket.socket(fileno=os.dup(self.parent_fd)) as parent:
                    connected_local_stream = parent.family == socket.AF_UNIX and parent.type == socket.SOCK_STREAM
                    if connected_local_stream:
                        try:
                            parent.getpeername()
                        except OSError:
                            connected_local_stream = False
            if not stat.S_ISFIFO(mode) and not connected_local_stream:
                raise SwarmError("PARENT_PIPE_REQUIRED", "the task runner requires its parent liveness pipe")
            self._fd = os.dup(self.parent_fd)
            _active_scope = self
            for number in (signal.SIGTERM, signal.SIGINT):
                self._handlers[number] = signal.signal(number, self._signal)
            self._thread = threading.Thread(target=self._watch, name="swarm-parent-watch", daemon=True)
            self._thread.start()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_exc) -> None:
        global _active_scope
        self._done.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        for number, previous in self._handlers.items():
            signal.signal(number, previous)
        self._handlers.clear()
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        if _active_scope is self:
            _active_scope = None
