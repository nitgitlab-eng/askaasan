from celery import shared_task

from config.retry import NOTIFY_RETRY

from .reminders import send_due


@shared_task(**NOTIFY_RETRY)
def plan_reminders():
    return send_due()


@shared_task
def reconcile_payments():
    """Every 10 min: grant orders Razorpay captured but we never granted (see reconcile.py)."""
    from .reconcile import reconcile_orders

    return reconcile_orders()
