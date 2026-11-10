"""Password checks beyond Django's built-ins."""

import hashlib
import logging

from django.conf import settings
from django.core.exceptions import ValidationError

log = logging.getLogger(__name__)
HIBP_URL = "https://api.pwnedpasswords.com/range/"


def breach_count(password: str) -> int:
    """How often `password` appears in Have I Been Pwned's breach corpus. Only the first 5 characters of its SHA-1
    leave the server (k-anonymity). Fails open (0) when the service is slow or down: sign-up must not depend on it."""
    import httpx

    digest = hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    try:
        r = httpx.get(HIBP_URL + prefix, timeout=2.0, headers={"Add-Padding": "true"})
        r.raise_for_status()
    except httpx.HTTPError:
        log.warning("password breach check unavailable; allowing")
        return 0
    for line in r.text.splitlines():
        h, _, n = line.partition(":")
        if h == suffix:
            return int(n or 0)
    return 0


class BreachedPasswordValidator:
    def validate(self, password, user=None):
        if settings.PASSWORD_BREACH_CHECK and breach_count(password) > 0:
            raise ValidationError(
                "This password has appeared in a data breach. Please choose a different one.",
                code="password_breached",
            )

    def get_help_text(self):
        return "Your password can't be one that has appeared in a known data breach."
