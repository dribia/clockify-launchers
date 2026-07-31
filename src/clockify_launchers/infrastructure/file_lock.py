"""Nonblocking file locks for sync and timer actions."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO


class LockBusyError(Exception):
    """Another process holds the lock; a skipped run is a normal outcome."""


@contextmanager
def acquire_lock(path: Path) -> Iterator[IO[str]]:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    fh = os.fdopen(fd, "w")
    try:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LockBusyError(str(path)) from exc
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
        yield fh
    finally:
        fh.close()
