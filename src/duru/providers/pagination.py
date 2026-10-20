"""Opaque continuation envelopes prevent accidental cross-collection reuse.

These are routing checks, not authentication or signed capabilities.
"""

import base64
import hashlib
import json


def _scope(identity: str, uri: str) -> str:
    return hashlib.sha256(json.dumps([identity, uri]).encode()).hexdigest()


def pack_cursor(identity: str, uri: str, upstream: str | None) -> str | None:
    if not upstream:
        return None
    if not isinstance(upstream, str) or len(upstream) > 8192:
        raise ValueError("Invalid upstream cursor")
    value = {"scope": _scope(identity, uri), "cursor": upstream}
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode()


def unpack_cursor(identity: str, uri: str, cursor: str | None) -> str | None:
    if cursor is None:
        return None
    try:
        if not isinstance(cursor, str) or len(cursor) > 16384:
            raise ValueError
        value = json.loads(
            base64.b64decode(cursor.encode("ascii"), altchars=b"-_", validate=True)
        )
        if not isinstance(value, dict) or value.get("scope") != _scope(identity, uri):
            raise ValueError
        result = value["cursor"]
        if not isinstance(result, str) or not result or len(result) > 8192:
            raise ValueError
        return result
    except (ValueError, KeyError, UnicodeError):
        raise ValueError(
            "Cursor belongs to another collection or is malformed"
        ) from None
