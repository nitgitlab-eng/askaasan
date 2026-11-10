from celery import shared_task

from . import services


@shared_task
def generate_outline(curriculum_id: int):
    services.generate_outline(curriculum_id)


@shared_task
def generate_practice(subsection_id: int):
    services.generate_practice(subsection_id)


@shared_task
def generate_lesson(subsection_id: int):
    services.generate_lesson(subsection_id)
