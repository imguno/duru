"""Explicit URI scheme dispatch, without global credentials or settings."""

import re
from urllib.parse import urlsplit

from .contracts import Provider
from .errors import UnsupportedOperation


class Registry:
    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(self, scheme: str, provider: Provider) -> None:
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9+.-]*", scheme):
            raise ValueError("Invalid URI scheme")
        scheme = scheme.lower()
        if scheme in self._providers:
            raise ValueError("URI scheme is already registered")
        if not isinstance(provider, Provider):
            raise TypeError("Provider must implement the Provider contract")
        self._providers[scheme] = provider

    def resolve(self, uri: str) -> Provider:
        scheme = urlsplit(uri).scheme.lower()
        try:
            return self._providers[scheme]
        except KeyError:
            raise UnsupportedOperation(
                "No provider registered for URI scheme"
            ) from None
