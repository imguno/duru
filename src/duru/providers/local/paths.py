"""Confine source paths and keep opened resources inside each operation."""

import os
import stat
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath

from .descriptors import open_directory

STATE_DIRECTORY = ".framework-state"
TEMP_PREFIX = ".framework-write-"


class LocalTree:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise NotADirectoryError(self.root)

    def parts(self, key: str) -> tuple[str, ...]:
        if (
            not isinstance(key, str)
            or not key
            or "\\" in key
            or ":" in key
            or "\0" in key
        ):
            raise ValueError("File keys must be nonempty relative POSIX paths")
        parts = tuple(key.split("/"))
        if (
            PurePosixPath(key).is_absolute()
            or PureWindowsPath(key).drive
            or any(part in {"", ".", "..", STATE_DIRECTORY} for part in parts)
            or any(part.startswith(TEMP_PREFIX) for part in parts)
        ):
            raise ValueError("File key escapes the source or uses a reserved name")
        return parts

    def path(self, key: str) -> Path:
        if self.root.is_symlink() or self.root.is_junction():
            raise ValueError("Source root must not become a link")
        candidate = self.root
        for part in self.parts(key):
            candidate = candidate / part
            if candidate.is_symlink() or candidate.is_junction():
                raise ValueError(
                    "Source paths must not contain symbolic links or junctions"
                )
        if not candidate.resolve().is_relative_to(self.root):
            raise ValueError("File key escapes the source root")
        return candidate

    @contextmanager
    def directory(self, key: str = ""):
        """Open a collection without following directory links on Linux."""
        if key:
            self.path(key)
            parts = self.parts(key)
        else:
            parts = ()
        if os.open not in os.supports_dir_fd:
            path = self.path(key) if key else self.root
            if path.is_symlink() or path.is_junction():
                raise ValueError("Source collection must not be a link")
            yield None, path
            return
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = open_directory(self.root)
        try:
            for part in parts:
                child = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            yield descriptor, descriptor
        finally:
            os.close(descriptor)

    def entries(self, key: str = "") -> tuple[tuple[str, bool], ...]:
        """List direct children, rejecting links instead of traversing them."""
        result = []
        with self.directory(key) as (_, target):
            with os.scandir(target) as entries:
                for entry in entries:
                    if entry.name == STATE_DIRECTORY or entry.name.startswith(
                        TEMP_PREFIX
                    ):
                        continue
                    info = entry.stat(follow_symlinks=False)
                    if entry.is_symlink() or (
                        hasattr(entry, "is_junction") and entry.is_junction()
                    ):
                        raise ValueError("Source paths must not contain links")
                    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                        raise ValueError(
                            "Local sources support regular files/collections"
                        )
                    result.append((entry.name, stat.S_ISDIR(info.st_mode)))
        return tuple(sorted(result))

    @contextmanager
    def parent(self, key: str):
        """Use no-follow directory descriptors on platforms that support them."""
        parts = self.parts(key)
        self.path(key)
        if os.open not in os.supports_dir_fd:
            path = self.path(key)
            yield None, path
            return
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = open_directory(self.root)
        try:
            for part in parts[:-1]:
                child = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            yield descriptor, parts[-1]
        finally:
            os.close(descriptor)

    def read(self, key: str) -> bytes:
        with self.parent(key) as (parent, name):
            flags = (
                os.O_RDONLY
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0)
            )
            descriptor = os.open(name, flags, dir_fd=parent)
            with os.fdopen(descriptor, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError("Local sources only support regular files")
                content = stream.read()
        self.path(key)
        return content

    def keys(self) -> tuple[str, ...]:
        keys = []

        def visit(parent: str) -> None:
            for name, collection in self.entries(parent):
                key = f"{parent}/{name}" if parent else name
                if collection:
                    visit(key)
                else:
                    keys.append(key)

        visit("")
        return tuple(keys)

    def state_path(self) -> Path:
        path = self.root / STATE_DIRECTORY
        if os.open in os.supports_dir_fd:
            with self.directory() as (descriptor, _):
                try:
                    os.mkdir(STATE_DIRECTORY, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                state = os.open(STATE_DIRECTORY, flags, dir_fd=descriptor)
                os.close(state)
            return path
        if path.is_symlink() or path.is_junction():
            raise ValueError("Source state directory must not be a link")
        path.mkdir(exist_ok=True)
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("Source state directory escapes the source root")
        return path
