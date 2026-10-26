"""Encryption for secrets that administrators edit in the LMS.

Values are encrypted at rest with Fernet (AES-128-CBC + HMAC). The key is
derived from ``SETTINGS_ENCRYPTION_KEY`` when provided, otherwise from
``JWT_SECRET_KEY``. Rotating the JWT secret therefore invalidates stored
tokens unless a dedicated settings key is configured; the resolver reports
this state instead of crashing, and the administrator simply enters the token
again.
"""
from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

log = logging.getLogger(__name__)

PREFIX = "enc:v1:"
_DERIVATION_CONTEXT = b"corelms/app-settings/v1:"


class SecretDecryptError(ValueError):
    """The stored value cannot be decrypted with the current key."""


def _fernet() -> Fernet:
    material = (settings.settings_encryption_key or settings.jwt_secret_key or "").strip()
    if not material:
        raise SecretDecryptError("settings encryption key is not configured")
    digest = hashlib.sha256(_DERIVATION_CONTEXT + material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return PREFIX + _fernet().encrypt(raw.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if not raw.startswith(PREFIX):
        # Values copied from the legacy Redis store or a manual migration.
        return raw
    try:
        return _fernet().decrypt(raw[len(PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise SecretDecryptError("stored secret cannot be decrypted") from exc
