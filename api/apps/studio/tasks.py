from celery import shared_task


@shared_task
def process_lecture(lecture_id: int):
    from .lecture import process

    process(lecture_id)
