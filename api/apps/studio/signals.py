"""Lecture files leave storage with their row (lecture, lesson, course or account deleted), unless a lesson still plays
them, e.g. a course kept for other learners after its author deleted their account."""

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import LectureVideo


@receiver(post_delete, sender=LectureVideo)
def drop_lecture_file(sender, instance, **kwargs):
    if not instance.file:
        return
    from apps.media.cleanup import delete_lecture_if_unused

    path = instance.file.name
    # After commit: cascaded activity rows are gone by then, and a rolled-back delete keeps its file.
    transaction.on_commit(lambda: delete_lecture_if_unused(path))
