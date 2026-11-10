"""Security events as structured log lines (logger "aasan.security"): sign-ins, failures, lockouts, password resets,
passkeys and re-authentication. Each line carries `event`; the account is a short hash of the email, so the logs hold
no personal data but repeated attacks on one account still group together."""

import hashlib
import logging

log = logging.getLogger("aasan.security")


def account_ref(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16] if email else ""


_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}


def security_event(event: str, *, email: str = "", user_id: int | None = None, **fields) -> None:
    """Never raises: a logging problem must not break the sign-in it describes."""
    extra = {k: v for k, v in fields.items() if k not in _RESERVED}
    try:
        log.info(
            "security: %s",
            event,
            extra={**extra, "event": event, "account": account_ref(email), "user_id": user_id},
        )
    except Exception:
        log.debug("security event %s not logged", event, exc_info=True)
