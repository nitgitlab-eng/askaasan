from celery import shared_task

from config.retry import NOTIFY_RETRY


@shared_task(**NOTIFY_RETRY)
def run_hook(name: str, *args):
    """A completion hook (hooks.HANDLERS) off the request thread. Handlers are idempotent (deduplicated records)."""
    from .hooks import HANDLERS

    HANDLERS[name](*args)


@shared_task(**NOTIFY_RETRY)
def deliver(delivery_id: int):
    """One webhook delivery try (events.attempt claims it under a row lock, so a redelivered message can't double-send)."""
    from .events import attempt

    attempt(delivery_id)


@shared_task(**NOTIFY_RETRY)
def retry_webhooks():
    from .events import retry_due

    return retry_due()


@shared_task(**NOTIFY_RETRY)
def cleanup_webhooks():
    from .events import cleanup

    return cleanup()
