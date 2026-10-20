"""Local provider: buffered versioned reads and cooperating atomic writers."""

import hashlib
import io
import json
import mimetypes
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from ...contracts import Listable, Page, Provider, ResourceInfo
from ...errors import AccessDenied, Conflict, NotFound, UnsupportedOperation
from .paths import LocalTree


@contextmanager
def local_errors():
    try:
        yield
    except FileNotFoundError as error:
        raise NotFound("Local resource does not exist") from error
    except PermissionError as error:
        raise AccessDenied("Local operation was denied") from error
    except FileExistsError as error:
        raise Conflict("Local destination already exists") from error


class ReadOnlyLocalProvider(Provider, Listable):
    """No-follow Linux access; reads buffer entire files to pin returned bytes.

    Windows uses checked paths and does not provide Linux's descriptor-based
    protection against hostile simultaneous directory replacements.
    """

    def __init__(self, root: str | Path) -> None:
        self.tree = LocalTree(Path(root))

    @property
    def identity(self) -> str:
        root = os.path.normcase(str(self.tree.root))
        return "local:" + hashlib.sha256(root.encode("utf-8")).hexdigest()

    @property
    def root_uri(self) -> str:
        return "local://" + self.identity.removeprefix("local:") + "/"

    def uri(self, key: str) -> str:
        if key:
            self.tree.parts(key)
        return self.root_uri + quote(key, safe="/")

    def key(self, uri: str) -> str:
        parsed = urlsplit(uri)
        if (
            parsed.scheme != "local"
            or parsed.netloc != self.identity.removeprefix("local:")
            or not parsed.path.startswith("/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("URI does not belong to this local provider")
        key = unquote(parsed.path[1:], errors="strict")
        if key:
            self.tree.parts(key)
        if self.uri(key) != uri:
            raise ValueError("Local URI must use canonical encoding")
        return key

    def file_info(self, key: str, content: bytes) -> ResourceInfo:
        return ResourceInfo(
            self.uri(key),
            key.rsplit("/", 1)[-1],
            revision=hashlib.sha256(content).hexdigest(),
            size=len(content),
            media_type=mimetypes.guess_type(key)[0],
        )

    def stat(self, uri: str) -> ResourceInfo:
        key = self.key(uri)
        with local_errors():
            if not key:
                with self.tree.directory():
                    return ResourceInfo(uri, self.tree.root.name, kind="collection")
            with self.tree.parent(key) as (parent, target):
                info = os.stat(target, dir_fd=parent, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    return ResourceInfo(uri, key.rsplit("/", 1)[-1], kind="collection")
            return self.file_info(key, self.tree.read(key))

    def open(
        self, uri: str, *, expected_revision: str | None = None
    ) -> io.BufferedReader:
        key = self.key(uri)
        if not key:
            raise UnsupportedOperation("Collections have no file content")
        with local_errors():
            content = self.tree.read(key)
        if expected_revision is not None:
            revision = hashlib.sha256(content).hexdigest()
            if revision != expected_revision:
                raise Conflict("Local resource revision changed")
        return io.BufferedReader(io.BytesIO(content))

    def list(self, uri: str, *, cursor: str | None = None, limit: int = 100) -> Page:
        key = self.key(uri)
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 10000
        ):
            raise ValueError("Page limit must be between 1 and 10000")
        offset = 0
        if cursor is not None:
            try:
                scope, offset = json.loads(cursor)
                if scope != uri or type(offset) is not int or offset < 0:
                    raise ValueError
            except (ValueError, TypeError):
                raise ValueError("Invalid collection cursor") from None
        with local_errors():
            entries = self.tree.entries(key)
            result = []
            for name, _ in entries[offset : offset + limit]:
                child = f"{key}/{name}" if key else name
                try:
                    result.append(self.stat(self.uri(child)))
                except NotFound:
                    # Listings are not snapshots; disappearance proves nothing.
                    continue
        following = offset + limit
        next_cursor = json.dumps([uri, following]) if following < len(entries) else None
        return Page(tuple(result), next_cursor)
