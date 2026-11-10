"""Run generation off the request thread.

Redis configured → Celery task. Otherwise (local dev) → daemon thread.
Tests set LEARNING_JOBS_INLINE=True to run synchronously."""

import threading

from django.conf import settings
from django.db import close_old_connections


def _thread(fn, *args):
    def run():
        try:
            fn(*args)
        finally:
            close_old_connections()

    threading.Thread(target=run, daemon=True).start()


def enqueue(name: str, *args):
    from . import services, tasks

    if getattr(settings, "LEARNING_JOBS_INLINE", False):
        getattr(services, name)(*args)
    elif settings.REDIS_URL:
        getattr(tasks, name).delay(*args)
    else:
        _thread(getattr(services, name), *args)
