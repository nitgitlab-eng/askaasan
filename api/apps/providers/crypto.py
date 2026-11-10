"""Fernet encryption for provider API keys stored in the DB.

AASAN_SECRETS_KEY encrypts; it is required (no fallback to the Django SECRET_KEY, which is public in dev and does
other jobs in production). Rotation: set the new key as AASAN_SECRETS_KEY and the previous one(s) in
AASAN_SECRETS_KEY_OLD (comma-separated): old rows still decrypt, new writes use the new key, and rotate() re-encrypts.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _key(secret: str) -> Fernet:
    # Accept any string: derive a 32-byte urlsafe key from it.
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def _fernet() -> MultiFernet:
    secret = settings.AASAN_SECRETS_KEY
    if not secret:
        raise ImproperlyConfigured(
            "AASAN_SECRETS_KEY must be set to store provider keys. Run `uv run python manage.py setup_env` in api/ "
            "(it generates one in api/.env), or set it yourself."
        )
    olds = [s.strip() for s in (getattr(settings, "AASAN_SECRETS_KEY_OLD", "") or "").split(",") if s.strip()]
    if settings.DEBUG:
        # Decrypt-only: rows saved in dev before AASAN_SECRETS_KEY existed were encrypted with SECRET_KEY.
        olds.append(settings.SECRET_KEY)
    return MultiFernet([_key(secret), *(_key(s) for s in olds if s != secret)])


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ImproperlyConfigured(
            "Stored provider key can't be decrypted — was AASAN_SECRETS_KEY changed? "
            "Put the previous key in AASAN_SECRETS_KEY_OLD."
        ) from exc


def rotate(token: str) -> str:
    """Re-encrypt a stored token under the current AASAN_SECRETS_KEY (it may have been made with an old key)."""
    try:
        return _fernet().rotate(token.encode()).decode()
    except InvalidToken as exc:
        raise ImproperlyConfigured("Stored provider key can't be decrypted with any configured key.") from exc


def mask(plaintext: str) -> str:
    return f"••••{plaintext[-4:]}" if len(plaintext) >= 8 else "••••"
