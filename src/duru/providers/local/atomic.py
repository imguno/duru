"""Commit local content, separating pre-effect failures from unknown outcomes."""

import os
import uuid
from pathlib import Path

from ...errors import EffectUnknown
from .paths import TEMP_PREFIX


def synchronize(parent: int | None) -> None:
    if parent is not None:
        try:
            os.fsync(parent)
        except OSError as error:
            raise EffectUnknown("Mutation durability could not be confirmed") from error


def replace_content(
    parent: int | None, target: str | Path, content: bytes, *, create: bool = False
) -> None:
    temporary = f"{TEMP_PREFIX}{uuid.uuid4().hex}.tmp"
    if parent is None:
        temporary = str(Path(target).parent / temporary)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(temporary, flags, 0o600, dir_fd=parent)
    committed = False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if create:
            # Linking the fully written temporary file never overwrites a target.
            os.link(
                temporary,
                target,
                src_dir_fd=parent,
                dst_dir_fd=parent,
                follow_symlinks=False,
            )
        else:
            os.replace(temporary, target, src_dir_fd=parent, dst_dir_fd=parent)
        committed = True
        synchronize(parent)
    finally:
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass
        except OSError as error:
            if committed:
                raise EffectUnknown("Mutation committed but cleanup failed") from error
            raise
