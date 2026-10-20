# API providers

Both providers implement `Provider` and `Listable` only. They neither import the
framework nor discover credentials from environment variables or files. The app
supplies token values, account/workspace IDs, and starting collection IDs.

```python
from duru.providers import GoogleDriveProvider, SlackProvider

drive = GoogleDriveProvider(
    access_token=app_secrets.drive_token,
    account_id="company-account",
    folder_id="folder-id-from-settings",
    export_formats={"application/vnd.google-apps.document": "text/plain"},
)
slack = SlackProvider(
    token=app_secrets.slack_token,
    workspace_id="T123",
    channel_ids=("C123",),
)

page = drive.list(drive.root_uri)
for item in page.items:
    if item.kind == "file":
        with drive.open(item.uri, expected_revision=item.revision) as content:
            use_bytes(content.read())

page = slack.list(slack.uri("C123"))
```

## Representation and addressing

Drive addresses are `drive://file-id`. Names are separately returned metadata.
`root` is Google's alias; metadata returns the canonical ID. The optional folder
is a starting address, not an access sandbox. `account_id` is a non-secret label
chosen by the caller to distinguish configured provider scopes. Token rotation
does not change it. Drive shortcuts are not followed automatically. Workspace
documents need an explicit source-MIME to export-MIME mapping; no guessed format
or parser is applied. Unsupported resources fail explicitly, including in a list.

Drive `stat` and `list` download file representations and hash their exact bytes.
This costs bandwidth and requests, but a successful `open(expected_revision=...)`
returns precisely content matching that SHA256. Metadata is checked before and
after downloads for version changes; a conflict is surfaced without automatic
retry. Native export has upstream size/format limits. Reads buffer at most the
configured response limit, default 32 MiB. This implementation deliberately does
not support arbitrary large files with unverified lazy streams.

Slack addresses are `slack://workspace/channel`, with top-level messages at
`/channel/timestamp`. Messages are canonical UTF-8 JSON objects, not flattened
text; SHA256 revisions identify those exact bytes. Embedded file links are
metadata and never fetched. A channel page includes thread collections at
`/channel/threads/root-timestamp` when replies exist. Those collections list
replies at `/channel/threads/root-timestamp/reply-timestamp`, excluding the root
message to avoid duplicates. Channel page `limit` controls upstream messages;
additional thread collection entries can increase returned item count. The
workspace ID is caller-declared; this API does not verify a token's workspace.
Channel IDs are configuration conveniences, not access-control restrictions.

Pagination cursors are opaque, provider/collection-scoped envelopes. They are
routing guards, not signed credentials. Lists are not snapshots. Incomplete
Drive search and missing Slack continuation information fail explicitly instead
of being reported as complete. One failed child read fails the page. Callers own
cursor persistence, scheduling, rate-limit retry policy, and stream closing.

## HTTP and authentication

OAuth token acquisition, renewal, scopes and secret storage belong to the caller.
Only fixed official HTTPS origins are used by default. An explicitly injected
`HttpTransport` can supply a trusted API gateway or local fixture endpoint. No
redirects, proxy environment variables, upstream URLs in payloads, automatic
retries, or credential-bearing exception payloads are followed/exposed. HTTP
timeouts are per socket operation, not an absolute whole-request deadline.

```python
from duru.providers.http import HttpTransport

transport = HttpTransport(
    "https://www.googleapis.com/drive/v3",
    token,
    timeout=10,
    max_bytes=8 * 1024 * 1024,
)
```

401/403/404 map to authentication/access/not-found errors; 429 and transient
upstream errors are `ResourceError` for application policy to handle. Slack's
JSON-level errors are mapped too. No live-account access was used in tests;
local HTTP fixtures verify endpoint/query mappings, cursor scope, exact revisions,
exports, threads, errors, limits, and credential isolation across redirects.

## Upstream contracts

- [Drive files metadata](https://developers.google.com/workspace/drive/api/reference/rest/v3/files)
- [Drive list](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list)
- [Drive downloads and exports](https://developers.google.com/workspace/drive/api/guides/manage-downloads)
- [Slack history](https://docs.slack.dev/reference/methods/conversations.history/)
- [Slack channel info](https://docs.slack.dev/reference/methods/conversations.info/)
- [Slack replies](https://docs.slack.dev/reference/methods/conversations.replies/)
