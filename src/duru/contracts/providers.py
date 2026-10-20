"""Small opt-in ABCs: capability support never implies authorization."""

from abc import ABC, abstractmethod
from typing import BinaryIO

from .models import Page, ResourceInfo


class Provider(ABC):
    @property
    @abstractmethod
    def identity(self) -> str: ...

    @abstractmethod
    def stat(self, uri: str) -> ResourceInfo: ...

    @abstractmethod
    def open(self, uri: str, *, expected_revision: str | None = None) -> BinaryIO:
        """Return a caller-owned readable binary stream, or fail before returning.

        When supplied, expected_revision must match the actual returned content,
        not just metadata read before opening. Raise Conflict for a mismatch;
        reject unsupported conditional reads explicitly. The caller closes the
        stream, including when later reading or processing raises an exception.
        """


class Listable(ABC):
    @abstractmethod
    def list(self, uri: str, *, cursor: str | None = None, limit: int = 100) -> Page:
        """Return a page, without promising a collection snapshot."""


class Writable(ABC):
    @abstractmethod
    def write(
        self, uri: str, content: bytes, *, expected_revision: str | None = None
    ) -> ResourceInfo: ...


class ConditionalWritable(Writable):
    """Expected revisions provide compare-and-replace among cooperating clients."""


class Creatable(ABC):
    @abstractmethod
    def create(self, parent_uri: str, name: str, content: bytes) -> ResourceInfo: ...


class Renamable(ABC):
    @abstractmethod
    def rename(self, uri: str, name: str) -> ResourceInfo: ...


class Movable(ABC):
    @abstractmethod
    def move(self, uri: str, destination_uri: str) -> ResourceInfo:
        """Move into a parent collection; destination is not a new name."""


class Removable(ABC):
    @abstractmethod
    def delete(self, uri: str) -> None: ...


def capabilities(provider: Provider) -> frozenset[str]:
    names = {"read", "stat"}
    for capability, name in (
        (Listable, "list"),
        (Writable, "write"),
        (ConditionalWritable, "conditional_write"),
        (Creatable, "create"),
        (Renamable, "rename"),
        (Movable, "move"),
        (Removable, "delete"),
    ):
        if isinstance(provider, capability):
            names.add(name)
    return frozenset(names)
