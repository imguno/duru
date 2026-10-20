"""Real local HTTP fixtures validate mappings, never real account credentials."""

import hashlib
import json
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from duru import (
    AccessDenied,
    AuthenticationRequired,
    Conflict,
    NotFound,
    ResourceError,
    UnsupportedOperation,
)
from duru.providers.google_drive import GoogleDriveProvider
from duru.providers.http import HttpTransport
from duru.providers.slack import SlackProvider


@contextmanager
def server(route):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            uri = urlsplit(self.path)
            params = parse_qs(uri.query)
            requests.append((uri.path, params, self.headers.get("Authorization")))
            status, body, headers = route(uri.path, params)
            if isinstance(body, dict):
                body = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    instance = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{instance.server_port}", requests
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join()


def transport(base, **kwargs):
    return HttpTransport(base, "test-secret", allow_insecure_localhost=True, **kwargs)


class TransportTests(unittest.TestCase):
    def test_no_redirect_or_credential_forwarding(self):
        with server(lambda path, params: (200, b"wrong", {})) as (target, leaked):
            with server(
                lambda path, params: (302, b"", {"Location": target + "/secret"})
            ) as (base, requests):
                with self.assertRaises(ResourceError) as caught:
                    transport(base).get("/file")
                self.assertNotIn("test-secret", str(caught.exception))
                self.assertEqual(len(requests), 1)
            self.assertEqual(leaked, [])

    def test_errors_redacted_and_limits(self):
        for status, error in (
            (401, AuthenticationRequired),
            (403, AccessDenied),
            (404, NotFound),
            (429, ResourceError),
            (503, ResourceError),
        ):
            with (
                self.subTest(status=status),
                server(
                    lambda p, q, s=status: (s, b"test-secret malicious payload", {})
                ) as (base, _),
            ):
                with self.assertRaises(error) as caught:
                    transport(base).get("/x")
                self.assertNotIn("test-secret", str(caught.exception))
        with server(lambda p, q: (200, b"12345", {})) as (base, _):
            with self.assertRaises(ResourceError):
                transport(base, max_bytes=4).get("/x")
        with server(lambda p, q: (200, b"[1]", {})) as (base, _):
            with self.assertRaises(ResourceError):
                transport(base).json("/x")

    def test_plaintext_and_credential_validation(self):
        for base in (
            "http://example.com/api",
            "https://user:pass@example.com",
            "https://example.com?x=1",
        ):
            with self.assertRaises(ValueError):
                HttpTransport(base, "secret")
        with self.assertRaises(ValueError):
            HttpTransport("https://example.com", "secret\r\nheader")


class DriveTests(unittest.TestCase):
    def fixture(self, path, params):
        if path == "/files":
            return 200, {"files": [{"id": "F1"}], "nextPageToken": "next-token"}, {}
        if params.get("alt") == ["media"] or path.endswith("/export"):
            return 200, b"hello", {}
        file_id = path.split("/")[-1]
        mime = (
            "application/vnd.google-apps.folder"
            if file_id in {"root", "folder"}
            else "text/plain"
        )
        return (
            200,
            {
                "id": "folder" if file_id == "root" else file_id,
                "name": "a different name",
                "mimeType": mime,
                "version": "1",
            },
            {},
        )

    def test_read_list_cursor_name_and_revision(self):
        with server(self.fixture) as (base, requests):
            provider = GoogleDriveProvider(
                "unused", account_id="work", transport=transport(base)
            )
            info = provider.stat("drive://F1")
            self.assertEqual(info.name, "a different name")
            self.assertEqual(info.uri, "drive://F1")
            self.assertEqual(
                info.revision, "sha256:" + hashlib.sha256(b"hello").hexdigest()
            )
            with provider.open(info.uri, expected_revision=info.revision) as stream:
                self.assertFalse(stream.writable())
                self.assertEqual(stream.read(), b"hello")
            initial = provider.list(provider.root_uri, limit=2)
            page = provider.list(provider.root_uri, cursor=initial.next_cursor, limit=2)
            self.assertIsNotNone(page.next_cursor)
            self.assertEqual(page.items[0], info)
            listing = [q for p, q, _ in requests if p == "/files"][-1]
            self.assertEqual(listing["pageToken"], ["next-token"])
            self.assertEqual(listing["q"], ["'root' in parents and trashed = false"])
            self.assertTrue(
                all(auth == "Bearer test-secret" for _, _, auth in requests)
            )
            self.assertNotIn("test-secret", provider.identity)
            with self.assertRaises(ValueError):
                provider.list("drive://folder", cursor=page.next_cursor)

    def test_changed_content_and_metadata_during_read(self):
        with server(self.fixture) as (base, _):
            provider = GoogleDriveProvider(
                "unused", account_id="work", transport=transport(base)
            )
            with self.assertRaises(Conflict):
                provider.open("drive://F1", expected_revision="old-revision")
        counter = []

        def changing(path, params):
            status, body, headers = self.fixture(path, params)
            if isinstance(body, dict) and "version" in body:
                counter.append(1)
                body["version"] = str(len(counter))
            return status, body, headers

        with server(changing) as (base, _):
            provider = GoogleDriveProvider(
                "unused", account_id="work", transport=transport(base)
            )
            with self.assertRaises(Conflict):
                provider.open("drive://F1")

    def test_native_export_is_explicit(self):
        def native(path, params):
            status, body, headers = self.fixture(path, params)
            if isinstance(body, dict) and "version" in body:
                body["mimeType"] = "application/vnd.google-apps.document"
            return status, body, headers

        with server(native) as (base, requests):
            provider = GoogleDriveProvider(
                "unused", account_id="work", transport=transport(base)
            )
            with self.assertRaises(UnsupportedOperation):
                provider.stat("drive://F1")
            provider = GoogleDriveProvider(
                "unused",
                account_id="work",
                transport=transport(base),
                export_formats={"application/vnd.google-apps.document": "text/plain"},
            )
            self.assertEqual(provider.stat("drive://F1").media_type, "text/plain")
            self.assertTrue(
                any(
                    p.endswith("/export") and q["mimeType"] == ["text/plain"]
                    for p, q, _ in requests
                )
            )

    def test_invalid_response_and_uri(self):
        with server(lambda p, q: (200, {"files": "invalid"}, {})) as (base, _):
            provider = GoogleDriveProvider(
                "unused", account_id="work", transport=transport(base)
            )
            with self.assertRaises(ResourceError):
                provider.stat("drive://F1")
            for uri in ("https://evil/file", "drive://F1/path", "drive://user@evil"):
                with self.assertRaises(ValueError):
                    provider.open(uri)

    def test_incomplete_search_rejected(self):
        def incomplete(path, params):
            if path == "/files":
                return 200, {"files": [], "incompleteSearch": True}, {}
            return self.fixture(path, params)

        with server(incomplete) as (base, _):
            provider = GoogleDriveProvider(
                "unused", account_id="work", transport=transport(base)
            )
            with self.assertRaises(ResourceError):
                provider.list(provider.root_uri)


class SlackTests(unittest.TestCase):
    def fixture(self, path, params):
        if path == "/conversations.info":
            return 200, {"ok": True, "channel": {"id": "C1", "name": "general"}}, {}
        if path == "/conversations.replies":
            messages = [{"ts": "1.0", "text": "root"}, {"ts": "2.0", "text": "reply"}]
        else:
            messages = [{"ts": "1.0", "text": "hello", "reply_count": 1}]
        return (
            200,
            {
                "ok": True,
                "messages": messages,
                "response_metadata": {"next_cursor": ""},
            },
            {},
        )

    def test_channel_message_thread_and_expected_revision(self):
        with server(self.fixture) as (base, requests):
            provider = SlackProvider(
                "unused",
                workspace_id="T1",
                channel_ids=["C1"],
                transport=transport(base),
            )
            self.assertEqual(provider.stat("slack://T1/C1").name, "general")
            page = provider.list("slack://T1/C1")
            self.assertEqual([i.kind for i in page.items], ["file", "collection"])
            info = page.items[0]
            with provider.open(info.uri, expected_revision=info.revision) as stream:
                self.assertFalse(stream.writable())
                self.assertEqual(json.load(stream)["text"], "hello")
            with self.assertRaises(Conflict):
                provider.open(info.uri, expected_revision="old-revision")
            replies = provider.list(page.items[1].uri)
            self.assertEqual(len(replies.items), 1)
            self.assertEqual(replies.items[0].uri, "slack://T1/C1/threads/1.0/2.0")
            with provider.open(
                replies.items[0].uri, expected_revision=replies.items[0].revision
            ) as stream:
                self.assertEqual(json.load(stream)["text"], "reply")
            self.assertTrue(
                all(auth == "Bearer test-secret" for _, _, auth in requests)
            )

    def test_error_mapping_and_pagination(self):
        for code, error in (
            ("invalid_auth", AuthenticationRequired),
            ("missing_scope", AccessDenied),
            ("channel_not_found", NotFound),
            ("ratelimited", ResourceError),
        ):
            with (
                self.subTest(code=code),
                server(
                    lambda p, q, c=code: (
                        200,
                        {"ok": False, "error": c, "secret": "test-secret"},
                        {},
                    )
                ) as (base, _),
            ):
                provider = SlackProvider(
                    "unused", workspace_id="T1", transport=transport(base)
                )
                with self.assertRaises(error) as caught:
                    provider.stat("slack://T1/C1")
                self.assertNotIn("test-secret", str(caught.exception))

        with server(
            lambda p, q: (
                200,
                {
                    "ok": True,
                    "messages": [],
                    "response_metadata": {"next_cursor": "next"},
                },
                {},
            )
        ) as (base, requests):
            provider = SlackProvider(
                "unused", workspace_id="T1", transport=transport(base)
            )
            first = provider.list("slack://T1/C1", limit=3)
            self.assertIsNotNone(
                provider.list(
                    "slack://T1/C1", cursor=first.next_cursor, limit=3
                ).next_cursor
            )
            self.assertEqual(requests[-1][1]["cursor"], ["next"])
            with self.assertRaises(ValueError):
                provider.list("slack://T1/C2", cursor=first.next_cursor)

    def test_broadcast_reply_not_duplicated_as_channel_item(self):
        def broadcast(path, params):
            return (
                200,
                {
                    "ok": True,
                    "messages": [
                        {"ts": "1.0", "text": "root", "reply_count": 1},
                        {"ts": "2.0", "thread_ts": "1.0", "text": "broadcast reply"},
                    ],
                },
                {},
            )

        with server(broadcast) as (base, _):
            provider = SlackProvider(
                "unused", workspace_id="T1", transport=transport(base)
            )
            self.assertEqual(
                [item.uri for item in provider.list("slack://T1/C1").items],
                ["slack://T1/C1/1.0", "slack://T1/C1/threads/1.0"],
            )

    def test_invalid_history_and_uri(self):
        for messages in (
            {},
            [{"ts": "bad"}],
            [{"ts": "1.0", "reply_count": "invalid"}],
        ):
            with server(
                lambda p, q, m=messages: (200, {"ok": True, "messages": m}, {})
            ) as (base, _):
                provider = SlackProvider(
                    "unused", workspace_id="T1", transport=transport(base)
                )
                with self.assertRaises(ResourceError):
                    provider.list("slack://T1/C1")
        provider = SlackProvider("token", workspace_id="T1")
        for uri in ("slack://OTHER/C1", "slack://T1/C1/../secret", "https://evil"):
            with self.assertRaises(ValueError):
                provider.open(uri)


if __name__ == "__main__":
    unittest.main()
