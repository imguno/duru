# Duru

Access local files, Google Drive documents, and Slack messages through small,
URI-based Python interfaces. Implement one provider contract and opt into the
capabilities your storage supports.

**English** · [한국어](README.ko.md)

## Status

This library is under development and requires Python 3.12 or later.
The package and Python import are both `duru`. It uses the [BSD 3-Clause license](LICENSE).

The package has no runtime dependencies. Applications supply credentials and
configuration explicitly. It can be used independently of any framework.

## Installation

Install from PyPI:

```sh
python -m pip install duru
```

For a local checkout, use `python -m pip install .` instead.

## Quick start

This example creates its own temporary directory and sample file. All mutations
stay inside that directory.

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from duru import LocalProvider, Registry

with TemporaryDirectory() as directory:
    root = Path(directory) / "documents"
    root.mkdir()
    (root / "guide.md").write_text("Hello, resources!", encoding="utf-8")

    provider = LocalProvider(root)
    registry = Registry()
    registry.register("local", provider)

    uri = provider.uri("guide.md")
    selected = registry.resolve(uri)
    info = selected.stat(uri)
    with selected.open(uri, expected_revision=info.revision) as content:
        print(info.name, content.read().decode("utf-8"))

    updated = provider.write(uri, b"Updated guide", expected_revision=info.revision)
    renamed = provider.rename(updated.uri, "manual.md")
    print(renamed.name)
```

Expected output:

```text
guide.md Hello, resources!
manual.md
```

Use the URI returned by a mutation for subsequent calls. A URI identifies a
resource; its display name is a separate value. Their relationship belongs to
the provider. The registry only dispatches by URI scheme.

## Providers and capabilities

| Provider | Read, stat, list | Mutations |
| --- | --- | --- |
| `ReadOnlyLocalProvider` | Yes | None |
| `LocalProvider` | Yes | File create, write, rename, move, delete |
| `GoogleDriveProvider` | Yes | None |
| `SlackProvider` | Yes | None |

Applications inject tokens and resource IDs. Providers do not load framework
settings, discover credentials, or acquire and renew OAuth tokens.

```python
from duru import GoogleDriveProvider, SlackProvider

def configure_providers(drive_token, folder_id, slack_token, workspace_id, channel_id):
    drive = GoogleDriveProvider(
        access_token=drive_token,
        account_id="work",
        folder_id=folder_id,
        export_formats={"application/vnd.google-apps.document": "text/plain"},
    )
    slack = SlackProvider(
        token=slack_token,
        workspace_id=workspace_id,
        channel_ids=(channel_id,),
    )
    return drive, slack
```

Drive native documents require an explicit export format. Slack messages are
JSON resources. Configured folders and channel IDs are starting locations, not
authorization boundaries. Read the [provider guide](src/duru/providers/README.md)
for URI conventions, pagination, API costs, transport limits, and upstream links.

## Extend the contract

Subclass `Provider` and implement `identity`, `stat(uri)`, and
`open(uri, expected_revision=...)`. Return `ResourceInfo` for metadata and a
caller-owned binary stream for content. The caller closes the stream, preferably
with `with`.

A checked open must verify the actual returned bytes against the requested
revision or reject the operation. Checking metadata before returning an
unchecked, mutable stream is insufficient. Providers define resource identity
and revision semantics explicitly.

Inherit additional ABCs only for supported operations:

| Contract | Operation |
| --- | --- |
| `Listable` | `list(uri, cursor=None, limit=100) -> Page` |
| `Writable` | `write(uri, content, expected_revision=None)` |
| `ConditionalWritable` | Compare-and-replace writes among cooperating clients |
| `Creatable` | `create(parent_uri, name, content)` |
| `Renamable` | `rename(uri, name)` |
| `Movable` | `move(uri, destination_uri)` into a parent collection |
| `Removable` | `delete(uri)` |

`capabilities(provider)` reports implemented contracts, not access permissions.
Unsupported operations fail explicitly. Mutations that return a resource return
its resulting URI and display name. Cross-provider moves are unsupported; the
library does not emulate them with a non-atomic copy and delete.

For example, register a read-only provider serving one immutable document:

```python
import hashlib
import io

from duru import Conflict, NotFound, Provider, Registry, ResourceInfo

class GuideProvider(Provider):
    identity = "guide-demo:v1"
    uri = "guide://manual"
    content = b"A document supplied by your application."

    def stat(self, uri):
        if uri != self.uri:
            raise NotFound("Unknown guide")
        snapshot = self.content
        return ResourceInfo(
            uri, "manual.txt",
            revision=hashlib.sha256(snapshot).hexdigest(),
            size=len(snapshot),
        )

    def open(self, uri, *, expected_revision=None):
        if uri != self.uri:
            raise NotFound("Unknown guide")
        snapshot = self.content
        revision = hashlib.sha256(snapshot).hexdigest()
        if expected_revision is not None and expected_revision != revision:
            raise Conflict("Guide revision changed")
        return io.BufferedReader(io.BytesIO(snapshot))

registry = Registry()
registry.register("guide", GuideProvider())
provider = registry.resolve("guide://manual")
info = provider.stat("guide://manual")
with provider.open(info.uri, expected_revision=info.revision) as content:
    print(content.read().decode("utf-8"))
```

## Consistency and limits

- Listing cursors are opaque and collection-scoped. Listings are not snapshots;
  a missing item is not evidence of deletion.
- `ResourceError` is the common provider error base. `NotFound` also inherits
  `FileNotFoundError`, and `AccessDenied` also inherits `PermissionError`.
  `AuthenticationRequired`, `Conflict`, and `UnsupportedOperation` distinguish
  other failures. Ordinary stream IO errors retain their IO exception types.
- `EffectUnknown` means a mutation may already have occurred. Reconcile the
  resource state before retrying; an exception alone does not prove rollback.
- Local revisions are SHA256 digests. Reads buffer the entire file into a
  read-only snapshot. Memory use grows with file size; use `write` to mutate
  content rather than the stream returned by `open`.
- Linux access uses no-follow descriptors for every absolute directory
  component and rejects symlinks and non-regular file content. Writes publish
  fully written temporary files atomically; durability failures after a mutation
  raise `EffectUnknown`. Locks coordinate cooperating providers, not unrelated
  OS writers. Windows uses checked paths without equivalent protection against
  concurrent directory replacement. Linux is the hardened deployment target.
- Local collection mutation is unsupported. Local URIs are path-derived and
  may change after rename or move. Reserved `.framework-state` and
  `.framework-write-` names are excluded from listings.

Scheduling, durable checkpoints, retry policy, document permissions, parsing,
and indexing belong to the application. Native watches, copy, mkdir, locking
APIs, POSIX attributes, and network mount protocols are outside the common
interface.

## Development

From this checkout, install development tools and run the checks:

```sh
python -m pip install -e '.[test]'
python -m pytest
python -m ruff check src tests
python -m ruff format --check src tests
```

Tests cover provider substitution, names and URIs, checked snapshots, cursor
scope, mutation conflicts, concurrent conditional writers, local confinement,
and unknown mutation outcomes. Linux-specific security and locking tests are
skipped on Windows. Service tests use local HTTP fixtures; they do not verify
live Google Drive or Slack accounts.

## Contributing

For a new provider or capability, describe its URI and revision semantics,
supported operations, and behavior after an ambiguous mutation. Keep credentials
injected and provider API code separate from application scheduling and policy.
Include focused contract tests and update the provider guide and both README
translations when public behavior changes. Use the checks above before sharing
a change. Contributions use the BSD 3-Clause license.

See [contributing](docs/CONTRIBUTING.md), [security reporting](docs/SECURITY.md),
and the [release procedure](docs/RELEASE.md).
