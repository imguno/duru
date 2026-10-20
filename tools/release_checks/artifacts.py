"""Validate archive members and compare package bytes across independent builds."""

import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import PurePosixPath

from .documents import private_document_path

PRIVATE = {
    ".git",
    ".venv",
    ".runtime",
    ".verification",
    "__pycache__",
    ".secrets",
    "secrets",
}
PRIVATE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".token",
    ".pem",
    ".key",
    ".sqlite",
    ".sqlite3",
    ".db",
}


def check_names(names):
    for name in names:
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in name
            or PRIVATE.intersection(path.parts)
            or private_document_path(path)
            or path.suffix in PRIVATE_SUFFIXES
            or any(part == ".env" or part.startswith(".env.") for part in path.parts)
        ):
            raise ValueError(f"Unsafe or private distribution member: {name}")


def wheel_payload(path, version):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        check_names(names)
        licenses = [
            name for name in names if name.endswith(".dist-info/licenses/LICENSE")
        ]
        if len(licenses) != 1:
            raise ValueError("Wheel must include its BSD license")
        metadata = BytesParser().parsebytes(
            archive.read(
                next(name for name in names if name.endswith(".dist-info/METADATA"))
            )
        )
        if (
            metadata["Name"] != "duru"
            or metadata["Version"] != version
            or metadata["License-Expression"] != "BSD-3-Clause"
        ):
            raise ValueError("Wheel name, version or BSD license metadata differs")
        if any(
            "extra ==" not in value for value in metadata.get_all("Requires-Dist", [])
        ):
            raise ValueError("Resource access must not gain a runtime dependency")
        return {
            name: archive.read(name)
            for name in names
            if name.startswith("duru/") and not name.endswith("/")
        }


def unpack_sdist(path, destination):
    with tarfile.open(path) as archive:
        check_names(archive.getnames())
        if any(
            not (member.isfile() or member.isdir()) for member in archive.getmembers()
        ):
            raise ValueError("Source archive must not contain links or special files")
        archive.extractall(destination, filter="data")
    roots = list(destination.iterdir())
    if len(roots) != 1 or not (roots[0] / "LICENSE").is_file():
        raise ValueError("Source archive must have one root with a license")
    return roots[0]
