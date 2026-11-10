"""Model signals that feed the completion hooks (see hooks.py)."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.credentials.models import Certificate
from apps.learning.models import UserSubsectionState


@receiver(post_save, sender=UserSubsectionState, dispatch_uid="integrations_lesson_completed")
def lesson_completed(sender, instance, **kwargs):
    if instance.status != UserSubsectionState.Status.COMPLETED:
        return
    from .hooks import on_lesson_completed

    on_lesson_completed(instance.user_id, instance.subsection_id)


@receiver(post_save, sender=Certificate, dispatch_uid="integrations_certificate_issued")
def certificate_issued(sender, instance, created, **kwargs):
    if created:
        from .hooks import on_certificate

        on_certificate(instance.id)
