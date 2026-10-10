"""One py-qa run at a time in a work tree.

Two runs over one tree contend for its caches and coverage data, and a fixing run rewrites files
the other is reading, so neither verdict can be trusted. The lock is an advisory flock(2), which
the kernel releases when its holder exits however it exits, so a lock file left on disk never
means a lock is held.
"""

from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING

from py_qa.affected import git_path

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from py_qa.config import Config


class LockHeldError(Exception):
    """Another run holds the lock; the message names its holder."""


def lock_path(config: Config) -> Path | None:
    """Return the lock file: the configured one, or one in the git directory, or none."""
    if not config.lock:
        return None
    if config.lock_path is not None:
        return config.root / config.lock_path
    return git_path(config.root, "py-qa/run.lock")


@contextlib.contextmanager
def run_lock(path: Path | None) -> Iterator[None]:
    """Hold the lock at path for the duration; raise LockHeldError at once if a run has it."""
    if path is None:
        yield
        return
    import fcntl  # deferred: POSIX only, and needed only when a lock is taken

    path.parent.mkdir(parents=True, exist_ok=True)
    # Opened for append, so a refused run cannot erase the holder's stamp before it reads it.
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            holder = path.read_text(encoding="utf-8").strip() or "pid unknown"
            msg = f"another py-qa run holds {path} ({holder}); wait for it to finish"
            raise LockHeldError(msg) from error
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"pid={os.getpid()}\n".encode())
        yield
    finally:
        os.close(descriptor)
