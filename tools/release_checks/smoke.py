"""Exercise an installed wheel in an isolated interpreter with no framework."""

from importlib import metadata, util
from pathlib import Path
from tempfile import TemporaryDirectory

from duru import LocalProvider, Registry

for name in ("galmuri", "framework", "resource_access"):
    assert util.find_spec(name) is None, (
        "An unrelated or old package leaked into the environment"
    )
assert metadata.metadata("duru")["License-Expression"] == "BSD-3-Clause"

with TemporaryDirectory() as directory:
    root = Path(directory) / "resources"
    root.mkdir()
    (root / "guide.md").write_bytes(b"first")
    provider = LocalProvider(root)
    registry = Registry()
    registry.register("local", provider)
    uri = provider.uri("guide.md")
    selected = registry.resolve(uri)
    original = selected.stat(uri)
    with selected.open(uri, expected_revision=original.revision) as content:
        assert content.read() == b"first"
    updated = provider.write(uri, b"second", expected_revision=original.revision)
    with provider.open(updated.uri, expected_revision=updated.revision) as content:
        assert content.read() == b"second"

print("Installed wheel: checked reads and conditional writes passed without framework")
