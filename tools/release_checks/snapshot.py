"""Copy only distribution inputs, excluding cached build metadata and private data."""

import shutil

from .documents import PUBLIC_DOCUMENTS


def copy_source(root, destination):
    destination.mkdir()
    for name in (
        "pyproject.toml",
        "MANIFEST.in",
        "LICENSE",
        "README.md",
        "README.ko.md",
    ):
        shutil.copy2(root / name, destination / name)
    (destination / "docs").mkdir()
    for name in PUBLIC_DOCUMENTS:
        shutil.copy2(root / "docs" / name, destination / "docs" / name)
    for name in ("src", "tests", "tools"):
        shutil.copytree(
            root / name,
            destination / name,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", "*.pyo", "*.egg-info"
            ),
        )


def package_payload(source):
    return {
        path.relative_to(source / "src").as_posix(): path.read_bytes()
        for path in (source / "src/duru").rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    }


def compare_source(source, payload):
    if payload != package_payload(source):
        raise ValueError("Wheel package files or bytes differ from the source snapshot")
