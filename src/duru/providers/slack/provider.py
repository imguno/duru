"""Channels and explicit thread collections expose canonical message JSON bytes."""

import hashlib
import io
import json
import re
from urllib.parse import urlsplit

from duru.contracts import Listable, Page, Provider, ResourceInfo
from duru.errors import (
    AccessDenied,
    AuthenticationRequired,
    Conflict,
    NotFound,
    ResourceError,
    UnsupportedOperation,
)
from duru.providers.http import HttpTransport
from duru.providers.pagination import pack_cursor, unpack_cursor

_ID = re.compile(r"[A-Za-z0-9_-]+\Z")
_TS = re.compile(r"[0-9]+\.[0-9]+\Z")


class SlackProvider(Provider, Listable):
    """Externally supplied OAuth token and workspace identity.

    Channel URIs: slack://workspace/channel. Top-level messages append /timestamp.
    Threads: /channel/threads/root-timestamp; replies append /reply-timestamp.
    Channel listings contain each top-level message and, where replies exist, a
    separate thread collection. Thread listings omit the root to avoid duplicate
    message ingestion. Attachments remain JSON metadata; arbitrary download URLs
    are never fetched. Workspace identity is caller-declared, not auto-discovered.
    No write, token refresh, automatic retries, or event scheduling is provided.
    """

    def __init__(
        self,
        token: str,
        *,
        workspace_id: str,
        channel_ids=(),
        transport: HttpTransport | None = None,
    ):
        if not _ID.fullmatch(workspace_id):
            raise ValueError("Invalid workspace ID")
        channel_ids = tuple(channel_ids)
        if any(
            not isinstance(channel, str) or not _ID.fullmatch(channel)
            for channel in channel_ids
        ):
            raise ValueError("Invalid channel IDs")
        self.workspace_id = workspace_id
        self.channel_ids = tuple(channel_ids)
        self._http = transport or HttpTransport("https://slack.com/api", token)

    @property
    def identity(self) -> str:
        return "slack:" + self.workspace_id

    def uri(self, channel_id: str, timestamp: str | None = None) -> str:
        if not _ID.fullmatch(channel_id) or (
            timestamp is not None and not _TS.fullmatch(timestamp)
        ):
            raise ValueError("Invalid Slack identifier")
        uri = "slack://" + self.workspace_id + "/" + channel_id
        return uri if timestamp is None else uri + "/" + timestamp

    def _parts(self, uri: str) -> tuple[str, ...]:
        parsed = urlsplit(uri)
        parts = tuple(parsed.path.lstrip("/").split("/"))
        if (
            parsed.scheme != "slack"
            or parsed.netloc != self.workspace_id
            or parsed.query
            or parsed.fragment
            or parsed.path.startswith("//")
        ):
            raise ValueError("Invalid Slack URI")
        valid = len(parts) in {1, 2, 3, 4} and bool(_ID.fullmatch(parts[0]))
        if len(parts) == 2:
            valid = valid and bool(_TS.fullmatch(parts[1]))
        if len(parts) >= 3:
            valid = valid and parts[1] == "threads" and bool(_TS.fullmatch(parts[2]))
        if len(parts) == 4:
            valid = valid and bool(_TS.fullmatch(parts[3]))
        if not valid:
            raise ValueError("Invalid Slack resource URI")
        return parts

    def _call(self, method: str, params: dict) -> dict:
        data = self._http.json("/" + method, params)
        if data.get("ok") is not True:
            code = data.get("error")
            if code in {
                "invalid_auth",
                "not_authed",
                "token_revoked",
                "token_expired",
                "account_inactive",
            }:
                raise AuthenticationRequired("Slack authentication failed")
            if code in {
                "missing_scope",
                "not_in_channel",
                "no_permission",
                "access_denied",
            }:
                raise AccessDenied("Slack access denied")
            if code in {"channel_not_found", "message_not_found", "thread_not_found"}:
                raise NotFound("Slack resource not found")
            raise ResourceError("Slack API request failed")
        return data

    @staticmethod
    def _messages(data: dict) -> tuple[list[dict], str | None]:
        messages, metadata = data.get("messages"), data.get("response_metadata", {})
        if not isinstance(messages, list) or not isinstance(metadata, dict):
            raise ResourceError("Invalid Slack history response")
        cursor = metadata.get("next_cursor")
        if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 8192):
            raise ResourceError("Invalid Slack page cursor")
        if data.get("has_more") is True and not cursor:
            raise ResourceError(
                "Slack response requires unavailable continuation cursor"
            )
        for message in messages:
            if (
                not isinstance(message, dict)
                or not isinstance(message.get("ts"), str)
                or not _TS.fullmatch(message["ts"])
            ):
                raise ResourceError("Invalid Slack message")
        return messages, cursor or None

    @staticmethod
    def _bytes(message: dict) -> bytes:
        try:
            return json.dumps(
                message,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (ValueError, UnicodeError):
            raise ResourceError("Invalid Slack message representation") from None

    def _message(self, parts: tuple[str, ...]) -> dict:
        if len(parts) == 2:
            timestamp = parts[1]
            data = self._call(
                "conversations.history",
                {
                    "channel": parts[0],
                    "latest": timestamp,
                    "oldest": timestamp,
                    "inclusive": "true",
                    "limit": 1,
                },
            )
        elif len(parts) == 4:
            timestamp = parts[3]
            data = self._call(
                "conversations.replies",
                {
                    "channel": parts[0],
                    "ts": parts[2],
                    "latest": timestamp,
                    "oldest": timestamp,
                    "inclusive": "true",
                    "limit": 2,
                },
            )
        else:
            raise UnsupportedOperation("Slack collection has no byte content")
        messages, _ = self._messages(data)
        for message in messages:
            if message["ts"] == timestamp:
                return message
        raise NotFound("Slack message not found")

    def _info(self, uri: str, message: dict) -> ResourceInfo:
        content = self._bytes(message)
        return ResourceInfo(
            uri=uri,
            name=message["ts"],
            revision="sha256:" + hashlib.sha256(content).hexdigest(),
            media_type="application/json",
            size=len(content),
            metadata={"provider": "slack"},
        )

    def stat(self, uri: str) -> ResourceInfo:
        parts = self._parts(uri)
        if len(parts) in {2, 4}:
            return self._info(uri, self._message(parts))
        if len(parts) == 3:
            self._message((parts[0], parts[2]))
            return ResourceInfo(uri=uri, name="Thread " + parts[2], kind="collection")
        data = self._call("conversations.info", {"channel": parts[0]})
        channel = data.get("channel")
        if not isinstance(channel, dict) or channel.get("id") != parts[0]:
            raise ResourceError("Invalid Slack channel metadata")
        name = channel.get("name", parts[0])
        if not isinstance(name, str):
            raise ResourceError("Invalid Slack channel name")
        return ResourceInfo(uri=uri, name=name, kind="collection")

    def open(
        self, uri: str, *, expected_revision: str | None = None
    ) -> io.BufferedReader:
        content = self._bytes(self._message(self._parts(uri)))
        if (
            expected_revision is not None
            and expected_revision != "sha256:" + hashlib.sha256(content).hexdigest()
        ):
            raise Conflict("Slack message revision differs")
        return io.BufferedReader(io.BytesIO(content))

    def list(self, uri: str, *, cursor: str | None = None, limit: int = 100) -> Page:
        parts = self._parts(uri)
        if len(parts) not in {1, 3}:
            raise UnsupportedOperation("Slack listing requires a collection")
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 999
        ):
            raise ValueError("Slack page limit must be between 1 and 999")
        params = {"channel": parts[0], "limit": limit}
        upstream_cursor = unpack_cursor(self.identity, uri, cursor)
        if upstream_cursor is not None:
            params["cursor"] = upstream_cursor
        method = "conversations.history"
        if len(parts) == 3:
            method = "conversations.replies"
            params["ts"] = parts[2]
        messages, next_cursor = self._messages(self._call(method, params))
        if len(messages) > limit:
            raise ResourceError("Slack listing exceeds requested page limit")
        items = []
        for message in messages:
            ts = message["ts"]
            if len(parts) == 3:
                if ts != parts[2]:
                    items.append(self._info(uri + "/" + ts, message))
                continue
            thread_ts = message.get("thread_ts")
            if thread_ts is not None:
                if not isinstance(thread_ts, str) or not _TS.fullmatch(thread_ts):
                    raise ResourceError("Invalid Slack thread timestamp")
                if thread_ts != ts:
                    # Broadcast replies also appear in history; their canonical
                    # address belongs to the explicit thread collection.
                    continue
            items.append(self._info(self.uri(parts[0], ts), message))
            replies = message.get("reply_count", 0)
            if not isinstance(replies, int) or isinstance(replies, bool) or replies < 0:
                raise ResourceError("Invalid Slack reply count")
            if replies:
                items.append(
                    ResourceInfo(
                        uri=uri + "/threads/" + ts,
                        name="Thread " + ts,
                        kind="collection",
                    )
                )
        return Page(tuple(items), pack_cursor(self.identity, uri, next_cursor))
