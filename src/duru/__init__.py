"""Resource access contracts and explicitly configured reference providers."""

from .contracts import (
    ConditionalWritable,
    Creatable,
    Listable,
    Movable,
    Page,
    Provider,
    Removable,
    Renamable,
    ResourceInfo,
    Writable,
    capabilities,
)
from .errors import (
    AccessDenied,
    AuthenticationRequired,
    Conflict,
    EffectUnknown,
    NotFound,
    ResourceError,
    UnsupportedOperation,
)
from .providers.google_drive import GoogleDriveProvider
from .providers.local import (
    LocalProvider,
    LocalTree,
    ReadOnlyLocalProvider,
    mutation_lock,
)
from .providers.slack import SlackProvider
from .registry import Registry

__all__ = [
    "Provider",
    "Listable",
    "Writable",
    "ConditionalWritable",
    "Creatable",
    "Renamable",
    "Movable",
    "Removable",
    "ResourceInfo",
    "Page",
    "capabilities",
    "ResourceError",
    "NotFound",
    "AccessDenied",
    "AuthenticationRequired",
    "Conflict",
    "UnsupportedOperation",
    "EffectUnknown",
    "Registry",
    "LocalProvider",
    "ReadOnlyLocalProvider",
    "LocalTree",
    "mutation_lock",
    "GoogleDriveProvider",
    "SlackProvider",
]
