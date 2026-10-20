"""Serialize local compare-and-replace writers across worker processes."""

import os
import stat
from contextlib import contextmanager
from pathlib import Path

from .descriptors import open_directory


@contextmanager
def mutation_lock(directory: Path):
    path = directory / "mutation.lock"
    if path.is_symlink():
        raise ValueError("Source lock must not be a symbolic link")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    if os.open in os.supports_dir_fd:
        # Walk absolute directories with no-follow descriptors, including the
        # state directory. Never follow a replaced parent to an external lock.
        parent = open_directory(directory)
        try:
            descriptor = os.open("mutation.lock", flags, 0o600, dir_fd=parent)
        finally:
            os.close(parent)
    else:
        descriptor = os.open(path, flags, 0o600)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError("Source lock must be a regular file")
    with os.fdopen(descriptor, "r+b", buffering=0) as stream:
        if os.name == "nt":
            import msvcrt

            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b"\0")
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
