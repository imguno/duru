"""Provider errors describe outcomes without exposing upstream secrets."""


class ResourceError(Exception):
    """Base resource access failure."""


class NotFound(ResourceError, FileNotFoundError):
    """The addressed resource does not exist."""


class AccessDenied(ResourceError, PermissionError):
    """The caller lacks permission for this operation."""


class AuthenticationRequired(ResourceError):
    """Credentials are absent or no longer accepted."""


class Conflict(ResourceError):
    """The requested version or destination conflicts with current state."""


class UnsupportedOperation(ResourceError):
    """The provider cannot perform this operation."""


class EffectUnknown(ResourceError):
    """A mutation may have happened; do not retry without reconciliation."""
