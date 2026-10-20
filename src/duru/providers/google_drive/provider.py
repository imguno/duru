"""Drive IDs form URIs independently of display names. No credential discovery."""

import hashlib
import io
import re
from urllib.parse import urlsplit

from duru.contracts import Listable, Page, Provider, ResourceInfo
from duru.errors import (
    Conflict,
    NotFound,
    ResourceError,
    UnsupportedOperation,
)
from duru.providers.http import HttpTransport
from duru.providers.pagination import pack_cursor, unpack_cursor

_FOLDER = "application/vnd.google-apps.folder"
_FIELDS = "id,name,mimeType,version,size,modifiedTime,trashed,parents"
_ID = re.compile(r"[A-Za-z0-9_-]+\Z")


class GoogleDriveProvider(Provider, Listable):
    """Read/list Drive using an externally acquired OAuth access token.

    account_id is a non-secret application label that distinguishes credential
    scopes. folder_id is a root convenience, not a security sandbox. Native Docs
    require an explicit native-MIME -> export-MIME map; unsupported exports fail.
    stat/list download each file to hash the exact returned representation. This
    deliberately favors truthful content revisions over inexpensive metadata.
    No OAuth refresh, retries, write operations, or shortcut following are hidden.
    """

    def __init__(
        self,
        access_token: str,
        *,
        account_id: str,
        folder_id: str = "root",
        export_formats: dict[str, str] | None = None,
        transport: HttpTransport | None = None,
    ):
        if not account_id or not _ID.fullmatch(folder_id):
            raise ValueError("Account label and valid folder ID required")
        self._identity = "google-drive:" + account_id
        self.root_uri = self.uri(folder_id)
        self._exports = dict(export_formats or {})
        if any(
            not isinstance(k, str) or not isinstance(v, str) or not v
            for k, v in self._exports.items()
        ):
            raise ValueError("Invalid export format mapping")
        self._http = transport or HttpTransport(
            "https://www.googleapis.com/drive/v3", access_token
        )

    @property
    def identity(self) -> str:
        return self._identity

    @staticmethod
    def uri(file_id: str) -> str:
        if not _ID.fullmatch(file_id):
            raise ValueError("Invalid Drive ID")
        return "drive://" + file_id

    @staticmethod
    def _id(uri: str) -> str:
        parsed = urlsplit(uri)
        if (
            parsed.scheme != "drive"
            or parsed.path
            or parsed.query
            or parsed.fragment
            or not _ID.fullmatch(parsed.netloc)
        ):
            raise ValueError("Invalid Drive URI")
        return parsed.netloc

    def _metadata(self, file_id: str) -> dict:
        data = self._http.json(
            "/files/" + file_id, {"fields": _FIELDS, "supportsAllDrives": "true"}
        )
        if (
            not isinstance(data.get("id"), str)
            or not _ID.fullmatch(data["id"])
            or (file_id != "root" and data["id"] != file_id)
            or not isinstance(data.get("name"), str)
            or not isinstance(data.get("mimeType"), str)
            or not isinstance(data.get("version"), str)
        ):
            raise ResourceError("Invalid Drive file metadata")
        if data.get("trashed"):
            raise NotFound("Drive resource is trashed")
        return data

    def _representation(self, file_id: str) -> tuple[dict, bytes, str]:
        before = self._metadata(file_id)
        mime = before["mimeType"]
        if mime == _FOLDER:
            raise UnsupportedOperation("Drive collection has no byte content")
        if mime.startswith("application/vnd.google-apps."):
            output_mime = self._exports.get(mime)
            if output_mime is None:
                raise UnsupportedOperation(
                    "Native Drive resource needs explicit export format"
                )
            content = self._http.get(
                "/files/" + file_id + "/export", {"mimeType": output_mime}
            )
        else:
            output_mime = mime
            content = self._http.get(
                "/files/" + file_id, {"alt": "media", "supportsAllDrives": "true"}
            )
        after = self._metadata(file_id)
        if after["version"] != before["version"]:
            raise Conflict("Drive resource changed during read")
        return after, content, output_mime

    def _info(
        self, data: dict, content: bytes | None = None, mime: str | None = None
    ) -> ResourceInfo:
        collection = data["mimeType"] == _FOLDER
        return ResourceInfo(
            uri=self.uri(data["id"]),
            name=data["name"],
            kind="collection" if collection else "file",
            revision=None
            if content is None
            else "sha256:" + hashlib.sha256(content).hexdigest(),
            media_type=mime or data["mimeType"],
            size=None if content is None else len(content),
            metadata={
                "provider": "google-drive",
                "source_media_type": data["mimeType"],
                "version": data["version"],
            },
        )

    def stat(self, uri: str) -> ResourceInfo:
        file_id = self._id(uri)
        data = self._metadata(file_id)
        if data["mimeType"] == _FOLDER:
            return self._info(data)
        data, content, mime = self._representation(file_id)
        return self._info(data, content, mime)

    def open(
        self, uri: str, *, expected_revision: str | None = None
    ) -> io.BufferedReader:
        _, content, _ = self._representation(self._id(uri))
        if (
            expected_revision is not None
            and expected_revision != "sha256:" + hashlib.sha256(content).hexdigest()
        ):
            raise Conflict("Drive content revision differs")
        return io.BufferedReader(io.BytesIO(content))

    def list(self, uri: str, *, cursor: str | None = None, limit: int = 100) -> Page:
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 1000
        ):
            raise ValueError("Drive page limit must be between 1 and 1000")
        file_id = self._id(uri)
        if self._metadata(file_id)["mimeType"] != _FOLDER:
            raise UnsupportedOperation("Drive listing requires a collection")
        params = {
            "q": f"'{file_id}' in parents and trashed = false",
            "pageSize": limit,
            "fields": "nextPageToken,incompleteSearch,files(id)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        upstream_cursor = unpack_cursor(self.identity, uri, cursor)
        if upstream_cursor is not None:
            params["pageToken"] = upstream_cursor
        result = self._http.json("/files", params)
        if result.get("incompleteSearch") is True:
            raise ResourceError("Drive search was incomplete")
        files, next_cursor = result.get("files"), result.get("nextPageToken")
        if not isinstance(files, list) or (
            next_cursor is not None and not isinstance(next_cursor, str)
        ):
            raise ResourceError("Invalid Drive listing response")
        if len(files) > limit:
            raise ResourceError("Drive listing exceeds requested page limit")
        items = []
        for item in files:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("id"), str)
                or not _ID.fullmatch(item["id"])
            ):
                raise ResourceError("Invalid Drive listing item")
            items.append(self.stat(self.uri(item["id"])))
        if next_cursor is not None and len(next_cursor) > 8192:
            raise ResourceError("Invalid Drive page cursor")
        return Page(tuple(items), pack_cursor(self.identity, uri, next_cursor))
