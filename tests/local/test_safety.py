import concurrent.futures
import os
import stat

import pytest

from duru import Conflict, EffectUnknown, LocalProvider
from duru.providers.local import atomic


@pytest.mark.skipif(os.name == "nt", reason="Linux no-follow ancestor traversal")
def test_replaced_root_ancestor_is_not_followed(tmp_path):
    parent = tmp_path / "parent"
    root = parent / "root"
    root.mkdir(parents=True)
    (root / "file").write_bytes(b"inside")
    outside = tmp_path / "outside"
    (outside / "root").mkdir(parents=True)
    (outside / "root" / "secret").write_bytes(b"outside")
    provider = LocalProvider(root)
    parent.rename(tmp_path / "old-parent")
    parent.symlink_to(outside, target_is_directory=True)
    for operation in (
        lambda: provider.list(provider.root_uri),
        lambda: provider.stat(provider.root_uri),
        lambda: provider.open(provider.uri("secret")),
        lambda: provider.create(provider.root_uri, "new", b"escape"),
    ):
        with pytest.raises((OSError, ValueError)):
            operation()
    assert not (outside / "root" / "new").exists()


@pytest.mark.skipif(os.name == "nt", reason="Linux descriptor and symlink guarantees")
def test_links_and_special_files_are_not_followed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "secret"
    outside.write_bytes(b"outside")
    (root / "link").symlink_to(outside)
    provider = LocalProvider(root)
    with pytest.raises(ValueError):
        provider.open(provider.uri("link"))
    with pytest.raises(ValueError):
        provider.list(provider.root_uri)
    (root / "link").unlink()
    os.mkfifo(root / "fifo")
    with pytest.raises(ValueError):
        provider.open(provider.uri("fifo"))
    assert outside.read_bytes() == b"outside"


@pytest.mark.skipif(os.name == "nt", reason="Linux directory descriptors")
def test_parent_swap_to_symlink_cannot_redirect_read(tmp_path, monkeypatch):
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (nested / "file").write_bytes(b"inside")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file").write_bytes(b"secret")
    provider = LocalProvider(root)
    original = provider.tree.path
    swapped = False

    def swap(key):
        nonlocal swapped
        result = original(key)
        if not swapped:
            swapped = True
            nested.rename(root / "previous")
            nested.symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(provider.tree, "path", swap)
    with pytest.raises((OSError, ValueError)):
        provider.open(provider.uri("nested/file"))


@pytest.mark.skipif(os.name == "nt", reason="Linux flock threads use separate opens")
def test_one_of_two_conditional_writers_wins(tmp_path):
    provider = LocalProvider(tmp_path)
    initial = provider.create(provider.root_uri, "file", b"initial")

    def write(content):
        instance = LocalProvider(tmp_path)
        try:
            return instance.write(
                initial.uri, content, expected_revision=initial.revision
            )
        except Conflict:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(write, (b"one", b"two")))
    assert sum(result is not None for result in results) == 1
    assert (tmp_path / "file").read_bytes() in {b"one", b"two"}


@pytest.mark.skipif(os.name == "nt", reason="Linux directory durability confirmation")
@pytest.mark.parametrize("operation", ["write", "create", "rename", "move", "delete"])
def test_post_commit_durability_failure_has_unknown_effect(
    tmp_path, monkeypatch, operation
):
    provider = LocalProvider(tmp_path)
    original = provider.create(provider.root_uri, "file", b"original")
    (tmp_path / "dest").mkdir()
    real_fsync = os.fsync

    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("injected durability failure")
        return real_fsync(fd)

    monkeypatch.setattr(atomic.os, "fsync", fail_directory)
    actions = {
        "write": lambda: provider.write(original.uri, b"changed"),
        "create": lambda: provider.create(provider.root_uri, "new", b"created"),
        "rename": lambda: provider.rename(original.uri, "new"),
        "move": lambda: provider.move(original.uri, provider.uri("dest")),
        "delete": lambda: provider.delete(original.uri),
    }
    with pytest.raises(EffectUnknown):
        actions[operation]()
    if operation == "write":
        assert (tmp_path / "file").read_bytes() == b"changed"
    if operation in {"create", "rename"}:
        assert (tmp_path / "new").is_file()
    if operation == "move":
        assert (tmp_path / "dest" / "file").is_file()
    if operation == "delete":
        assert not (tmp_path / "file").exists()


def test_pre_commit_failure_preserves_original_and_cleans_temporary(
    tmp_path, monkeypatch
):
    provider = LocalProvider(tmp_path)
    original = provider.create(provider.root_uri, "file", b"original")

    def fail_replace(*args, **kwargs):
        raise OSError("injected replacement failure")

    monkeypatch.setattr(atomic.os, "replace", fail_replace)
    with pytest.raises(OSError):
        provider.write(original.uri, b"changed", expected_revision=original.revision)
    assert (tmp_path / "file").read_bytes() == b"original"
    assert not list(tmp_path.glob(".framework-write-*"))
