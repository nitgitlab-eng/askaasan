from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.learning.models import UserSubsectionState


@receiver(post_save, sender=UserSubsectionState, dispatch_uid="credentials_course_complete")
def course_complete(sender, instance, **kwargs):
    if instance.status != UserSubsectionState.Status.COMPLETED:
        return
    from .services import maybe_issue_course

    maybe_issue_course(instance.user, instance.subsection.section.curriculum)
