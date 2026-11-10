from celery import shared_task

from config.retry import NOTIFY_RETRY

from .study_reminders import send_due


@shared_task(**NOTIFY_RETRY)
def study_reminders():
    return send_due()


@shared_task(**NOTIFY_RETRY)
def guardian_digest():
    from .guardian import send_weekly

    return send_weekly()


@shared_task(**NOTIFY_RETRY)
def push_deliver(user_id, payload):
    from .push import deliver

    return deliver(user_id, payload)


@shared_task(**NOTIFY_RETRY)
def evening_checks():
    from .evening import run

    return run()


@shared_task(**NOTIFY_RETRY)
def winback_daily():
    from .winback import run

    return run()


@shared_task(**NOTIFY_RETRY)
def stepup_checks():
    from .cadence import send_notices
    from .stepup import run

    return {"stepup": run(), "notices": send_notices()}


@shared_task(**NOTIFY_RETRY)
def reminder_nightly():
    from .besttime import compute_all
    from .cadence import evaluate_all, prune

    return {"best": compute_all(), "backoff": evaluate_all(), "pruned": prune()}
