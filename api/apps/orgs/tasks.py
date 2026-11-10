from celery import shared_task

from config.retry import NOTIFY_RETRY


@shared_task(**NOTIFY_RETRY)
def recheck_domains():
    """Daily DNS re-check of verified SSO domains (sso.recheck_domains)."""
    from .sso import recheck_domains as run

    return run()
