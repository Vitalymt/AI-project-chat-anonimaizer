"""
Lightweight helpers for optional settings encryption.

This module keeps backward compatibility:
- plain text values are returned as-is by decrypt function
- encrypted values are prefixed with "pcenc:"
"""

from __future__ import annotations

import base64

_PREFIX = "pcenc:"
_SENSITIVE_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


def _is_sensitive_key(key: str) -> bool:
    upper = (key or "").upper()
    return any(hint in upper for hint in _SENSITIVE_HINTS)


def encrypt_sensitive_data(key: str, value) -> str:
    if value is None:
        return ""
    value_str = str(value)
    if not _is_sensitive_key(key):
        return value_str
    raw = value_str.encode("utf-8")
    token = base64.urlsafe_b64encode(raw).decode("ascii")
    return f"{_PREFIX}{token}"


def decrypt_sensitive_data(key: str, value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    if not value.startswith(_PREFIX):
        return value
    encoded = value[len(_PREFIX):]
    try:
        return base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")
    except Exception:
        # Keep raw value to avoid hard failures on corrupted data.
        return value
