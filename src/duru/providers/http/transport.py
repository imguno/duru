"""No redirects, automatic retries, environment proxies, or upstream error bodies."""

import json
import math
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from duru.errors import (
    AccessDenied,
    AuthenticationRequired,
    NotFound,
    ResourceError,
)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HttpTransport:
    """Explicit trusted origin and injected bearer token; reads are bounded in memory.

    timeout is a socket-operation timeout, not a whole-operation deadline. Local
    HTTP is an explicit fixture-only option. No arbitrary URLs are accepted by get.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 20,
        max_bytes: int = 32 * 1024 * 1024,
        allow_insecure_localhost: bool = False,
    ):
        parsed = urlsplit(base_url)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            (
                parsed.scheme != "https"
                and not (allow_insecure_localhost and local and parsed.scheme == "http")
            )
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("API base must be a trusted HTTPS URL")
        if (
            not isinstance(token, str)
            or not token
            or any(ord(char) < 33 or ord(char) > 126 for char in token)
        ):
            raise ValueError("Invalid bearer credential")
        if (
            not math.isfinite(timeout)
            or timeout <= 0
            or not isinstance(max_bytes, int)
            or max_bytes < 1
        ):
            raise ValueError("Invalid transport limits")
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def get(self, path: str, params: dict | None = None) -> bytes:
        if (
            not path.startswith("/")
            or path.startswith("//")
            or any(c in path for c in "?#\\\r\n")
        ):
            raise ValueError("Invalid relative API path")
        url = self._base + path
        if params:
            url += "?" + urlencode(params)
        request = Request(url, headers={"Authorization": "Bearer " + self._token})
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                result = response.read(self._max_bytes + 1)
        except HTTPError as error:
            status = error.code
            error.close()
            exception = {
                401: AuthenticationRequired,
                403: AccessDenied,
                404: NotFound,
            }.get(status, ResourceError)
            raise exception(f"Upstream HTTP status {status}") from None
        except (URLError, OSError, ValueError, HTTPException):
            raise ResourceError("Upstream transport failed") from None
        if len(result) > self._max_bytes:
            raise ResourceError("Upstream response exceeds configured size limit")
        return result

    def json(self, path: str, params: dict | None = None) -> dict:
        try:
            result = json.loads(self.get(path, params), parse_constant=_reject_constant)
        except (ValueError, UnicodeError):
            raise ResourceError("Upstream returned invalid JSON") from None
        if not isinstance(result, dict):
            raise ResourceError("Upstream returned invalid object")
        return result


def _reject_constant(value: str):
    raise ValueError("Non-finite JSON number")
