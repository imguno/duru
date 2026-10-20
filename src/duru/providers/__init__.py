"""Provider implementations; configuration is always injected by callers."""

from .google_drive import GoogleDriveProvider
from .slack import SlackProvider

__all__ = ["GoogleDriveProvider", "SlackProvider"]
