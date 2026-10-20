import hashlib

import pytest

from duru import (
    Conflict,
    LocalProvider,
    NotFound,
    ReadOnlyLocalProvider,
    Writable,
    capabilities,
)


def test_uri_roundtrip_and_snapshot_revision(tmp_path):
    path = tmp_path / "한 글 %2F.txt"
    path.write_bytes(b"original")
    provider = LocalProvider(tmp_path)
    uri = provider.uri(path.name)
    assert provider.key(uri) == path.name
    assert provider.key(provider.root_uri) == ""
    assert provider.stat(provider.root_uri).kind == "collection"
    info = provider.stat(uri)
    assert info.name == path.name
    assert info.revision == hashlib.sha256(b"original").hexdigest()
    stream = provider.open(uri, expected_revision=info.revision)
    path.write_bytes(b"replacement")
    with stream:
        assert stream.read() == b"original"
        assert stream.readable() and stream.seekable() and not stream.writable()
        with pytest.raises(OSError):
            stream.write(b"not a remote write")
    with pytest.raises(Conflict):
        provider.open(uri, expected_revision=info.revision)
    assert stream.closed


def test_readonly_has_no_mutation_capabilities(tmp_path):
    provider = ReadOnlyLocalProvider(tmp_path)
    assert not isinstance(provider, Writable)
    assert not hasattr(provider, "write")
    assert capabilities(provider) == {"read", "stat", "list"}


@pytest.mark.parametrize(
    "key",
    [
        "../a",
        "a/../b",
        "/a",
        "a\\b",
        "a//b",
        ".",
        ".framework-state/x",
        ".framework-write-x",
        "a:b",
    ],
)
def test_keys_are_confined_and_reserved(tmp_path, key):
    provider = LocalProvider(tmp_path)
    with pytest.raises(ValueError):
        provider.uri(key)


def test_uri_cannot_change_provider_or_smuggle_components(tmp_path):
    provider = LocalProvider(tmp_path)
    for uri in (
        "local://foreign/a",
        provider.root_uri + "%2e%2e/outside",
        provider.root_uri + "a%2Fb",
        provider.root_uri + "a?query=x",
        provider.root_uri + "a#fragment",
    ):
        with pytest.raises(ValueError):
            provider.key(uri)


def test_pages_scope_cursors_and_hide_internal_files(tmp_path):
    (tmp_path / ".framework-state").mkdir()
    (tmp_path / ".framework-state" / "secret").write_bytes(b"hidden")
    (tmp_path / ".framework-write-temporary").write_bytes(b"hidden")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "child").write_bytes(b"child")
    for name in ("a", "b", "c"):
        (tmp_path / name).write_bytes(name.encode())
    provider = LocalProvider(tmp_path)
    first = provider.list(provider.root_uri, limit=2)
    assert [item.name for item in first.items] == ["a", "b"]
    second = provider.list(provider.root_uri, cursor=first.next_cursor, limit=2)
    assert [item.name for item in second.items] == ["c", "nested"]
    assert second.next_cursor is None
    assert set(provider.tree.keys()) == {"a", "b", "c", "nested/child"}
    with pytest.raises(ValueError):
        provider.list(provider.uri("nested"), cursor=first.next_cursor)
    with pytest.raises(NotFound):
        provider.open(provider.uri("missing"))


def test_write_create_rename_move_delete(tmp_path):
    (tmp_path / "destination").mkdir()
    provider = LocalProvider(tmp_path)
    info = provider.create(provider.root_uri, "initial", b"first")
    with pytest.raises(Conflict):
        provider.create(provider.root_uri, "initial", b"overwrite")
    replacement = provider.write(info.uri, b"second", expected_revision=info.revision)
    with pytest.raises(Conflict):
        provider.write(info.uri, b"stale", expected_revision=info.revision)
    renamed = provider.rename(replacement.uri, "renamed")
    assert renamed.name == "renamed" and renamed.revision == replacement.revision
    with pytest.raises(NotFound):
        provider.stat(info.uri)
    moved = provider.move(renamed.uri, provider.uri("destination"))
    assert moved.name == "renamed"
    assert provider.key(moved.uri) == "destination/renamed"
    with provider.open(moved.uri) as stream:
        assert stream.read() == b"second"
    provider.delete(moved.uri)
    with pytest.raises(NotFound):
        provider.stat(moved.uri)


def test_rename_never_overwrites_cooperating_destination(tmp_path):
    provider = LocalProvider(tmp_path)
    a = provider.create(provider.root_uri, "a", b"a")
    provider.create(provider.root_uri, "b", b"b")
    with pytest.raises(Conflict):
        provider.rename(a.uri, "b")
    assert (tmp_path / "a").read_bytes() == b"a"
    assert (tmp_path / "b").read_bytes() == b"b"
