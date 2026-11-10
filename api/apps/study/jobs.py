"""Run a study background job inline (tests), on Celery (Redis configured) or in a thread (local dev)."""

import importlib

ALLOWED = {
    "apps.study.explainer.build",
    "apps.study.journey.build_podcast",
    "apps.learning.widget.build",
    "apps.study.checkpoints.build",
    "apps.orgs.knowledge.build",
    "apps.guests.campaigns.build_prospect",
    "apps.providers.clips.warm",  # (user_id, [{text, lang, voice_role}]): pre-make the rest of an episode / lesson
}


def resolve(dotted: str):
    if dotted not in ALLOWED:
        raise ValueError(dotted)
    mod, fn = dotted.rsplit(".", 1)
    return getattr(importlib.import_module(mod), fn)


def enqueue(dotted: str, *args) -> None:
    """Arguments must be JSON-serialisable (they travel through Celery)."""
    from django.conf import settings

    if getattr(settings, "LEARNING_JOBS_INLINE", False):
        resolve(dotted)(*args)
    elif settings.REDIS_URL:
        from .tasks import run_job

        run_job.delay(dotted, *args)
    else:
        from apps.learning.jobs import _thread

        _thread(resolve(dotted), *args)
