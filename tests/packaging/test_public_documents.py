"""Public guidance travels with sources while private working documents do not."""

import pytest

from tools.release_checks.artifacts import check_names
from tools.release_checks.documents import PUBLIC_DOCUMENTS
from tools.release_checks.snapshot import copy_source


def test_public_document_archive_members_are_allowed():
    check_names(["duru-0.1.0/docs"])
    check_names([f"duru-0.1.0/docs/{name}" for name in PUBLIC_DOCUMENTS])


@pytest.mark.parametrize(
    "member",
    [
        "docs/decisions/note.md",
        "docs/implementation/note.md",
        "docs/draft.md",
        "docs/CONTRIBUTING.private.md",
        "docs/credentials.json",
        "docs/.env",
        ".secrets/CONTRIBUTING.md",
        "AGENTS.md",
        "agent.md",
        "CHANGELOG.md",
        "nested/Changelog.ko.md",
    ],
)
def test_private_document_archive_members_are_rejected(member):
    with pytest.raises(ValueError, match="private distribution member"):
        check_names([f"duru-0.1.0/{member}"])


def test_source_snapshot_copies_only_public_documents(tmp_path):
    root, destination = tmp_path / "checkout", tmp_path / "snapshot"
    (root / "docs/decisions").mkdir(parents=True)
    for directory in ("src", "tests", "tools"):
        (root / directory).mkdir()
    for name in (
        "pyproject.toml",
        "MANIFEST.in",
        "LICENSE",
        "README.md",
        "README.ko.md",
    ):
        (root / name).write_text("Source fixture", encoding="utf-8")
    for name in PUBLIC_DOCUMENTS:
        (root / "docs" / name).write_text(f"Public {name}", encoding="utf-8")
    (root / "docs/decisions/private.md").write_text("Private work", encoding="utf-8")
    (root / "docs/credentials.json").write_text("Private credential", encoding="utf-8")
    (root / "README.private.md").write_text("Private work", encoding="utf-8")
    copy_source(root, destination)
    copied = {
        path.relative_to(destination / "docs").as_posix()
        for path in (destination / "docs").rglob("*")
        if path.is_file()
    }
    assert copied == set(PUBLIC_DOCUMENTS)
    assert not (destination / "README.private.md").exists()
    for name in PUBLIC_DOCUMENTS:
        assert (destination / "docs" / name).read_bytes() == (
            root / "docs" / name
        ).read_bytes()
