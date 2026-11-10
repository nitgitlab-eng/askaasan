"""Retry policy for Celery tasks that send email or notifications.

Each send inside these tasks already swallows a single bad address, so what reaches here is an outage: the database,
Redis or the mail server not answering. Those are retried with exponential backoff and jitter (about 5 s, 10 s, 20 s
... up to 10 min, 5 tries). The tasks are idempotent (they claim a flag or skip users already told) so a retry
doesn't double-send."""

import smtplib

from django.db import InterfaceError, OperationalError

TRANSIENT = (OperationalError, InterfaceError, ConnectionError, TimeoutError, smtplib.SMTPException)

NOTIFY_RETRY = {
    "autoretry_for": TRANSIENT,
    "retry_backoff": 5,
    "retry_backoff_max": 600,
    "retry_jitter": True,
    "max_retries": 5,
}
