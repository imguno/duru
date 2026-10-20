"""Optional local mutations, serialized among cooperating provider instances."""

import os

from ...contracts import (
    ConditionalWritable,
    Creatable,
    Movable,
    Removable,
    Renamable,
    ResourceInfo,
)
from ...errors import Conflict, UnsupportedOperation
from .atomic import replace_content, synchronize
from .locking import mutation_lock
from .provider import ReadOnlyLocalProvider, local_errors


class LocalProvider(
    ReadOnlyLocalProvider, ConditionalWritable, Creatable, Renamable, Movable, Removable
):
    """File mutations with no coordination guarantee for unrelated OS writers.

    Collection creation/move/delete, cross-provider operations, and POSIX
    metadata preservation are deliberately unsupported.
    """

    def _file_key(self, uri: str) -> str:
        key = self.key(uri)
        if not key:
            raise UnsupportedOperation("Operation requires a file resource")
        self.tree.path(key)
        return key

    def _child(self, parent_uri: str, name: str) -> str:
        if not isinstance(name, str) or len(self.tree.parts(name)) != 1:
            raise ValueError("Local display name must be one path component")
        parent = self.key(parent_uri)
        with self.tree.directory(parent):
            pass
        return f"{parent}/{name}" if parent else name

    def write(
        self, uri: str, content: bytes, *, expected_revision: str | None = None
    ) -> ResourceInfo:
        if not isinstance(content, bytes):
            raise TypeError("Resource writes require bytes")
        key = self._file_key(uri)
        with local_errors(), mutation_lock(self.tree.state_path()):
            current = self.stat(uri)
            if current.kind != "file":
                raise UnsupportedOperation("Collection content cannot be written")
            if expected_revision is not None and current.revision != expected_revision:
                raise Conflict("Local resource revision changed")
            with self.tree.parent(key) as (parent, target):
                replace_content(parent, target, content)
        return self.file_info(key, content)

    def create(self, parent_uri: str, name: str, content: bytes) -> ResourceInfo:
        if not isinstance(content, bytes):
            raise TypeError("Resource creation requires bytes")
        with local_errors(), mutation_lock(self.tree.state_path()):
            key = self._child(parent_uri, name)
            with self.tree.parent(key) as (parent, target):
                replace_content(parent, target, content, create=True)
        return self.file_info(key, content)

    def _relocate(self, uri: str, *, parent_uri: str | None, name: str | None):
        key = self._file_key(uri)
        with local_errors(), mutation_lock(self.tree.state_path()):
            content = self.tree.read(key)
            old_parent, _, old_name = key.rpartition("/")
            destination_parent = (
                parent_uri if parent_uri is not None else self.uri(old_parent)
            )
            destination = self._child(
                destination_parent, name if name is not None else old_name
            )
            if destination == key:
                return self.file_info(key, content)
            with self.tree.parent(key) as (source_fd, source):
                with self.tree.parent(destination) as (target_fd, target):
                    try:
                        os.stat(target, dir_fd=target_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        pass
                    else:
                        raise Conflict("Local destination already exists")
                    os.rename(
                        source, target, src_dir_fd=source_fd, dst_dir_fd=target_fd
                    )
                    synchronize(target_fd)
                    if old_parent != self.key(destination_parent):
                        synchronize(source_fd)
        return self.file_info(destination, content)

    def rename(self, uri: str, name: str) -> ResourceInfo:
        return self._relocate(uri, parent_uri=None, name=name)

    def move(self, uri: str, destination_uri: str) -> ResourceInfo:
        return self._relocate(uri, parent_uri=destination_uri, name=None)

    def delete(self, uri: str) -> None:
        key = self._file_key(uri)
        with local_errors(), mutation_lock(self.tree.state_path()):
            current = self.stat(uri)
            if current.kind != "file":
                raise UnsupportedOperation("Collection deletion is unsupported")
            with self.tree.parent(key) as (parent, target):
                os.unlink(target, dir_fd=parent)
                synchronize(parent)
