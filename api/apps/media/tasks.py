from celery import shared_task

from .cleanup import sweep, sweep_lectures


@shared_task
def clean_media():
    return {**sweep(), "lectures": sweep_lectures()}
