"""Values shared by callers and independently implemented providers."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ResourceInfo:
    uri: str
    name: str
    kind: str = "file"
    revision: str | None = None
    media_type: str | None = None
    size: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.uri or self.kind not in {"file", "collection"}:
            raise ValueError("Resource requires a URI and file/collection kind")
        if self.size is not None and self.size < 0:
            raise ValueError("Resource size must be nonnegative")


@dataclass(frozen=True)
class Page:
    items: tuple[ResourceInfo, ...]
    next_cursor: str | None = None
