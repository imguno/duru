"""Open absolute directories without following any ancestor symlink on Linux."""

import os
from pathlib import Path


def open_directory(path: Path) -> int:
    if not path.is_absolute():
        raise ValueError("Directory descriptor requires an absolute path")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise
