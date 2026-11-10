from celery import shared_task


@shared_task
def translate_lesson(translation_id: int):
    from .translation import translate

    translate(translation_id)


@shared_task
def run_job(dotted: str, *args):
    """Generic background job: 'apps.study.explainer.build' etc."""
    from .jobs import resolve

    resolve(dotted)(*args)
