"""Milestone 9 housekeeping: unit admins lose their (scoped) manager role with their last unit; org knowledge-base
documents stay with the organisation when the uploader leaves."""

from django.conf import settings
from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver

from .models import Membership, UnitAdmin


def release_scope(membership_id: int):
    """No units left → back to the role they had before becoming a unit admin (learner by default), unscoped."""
    m = Membership.objects.filter(
        pk=membership_id, unit_scoped=True, role="manager"
    ).first()  # only an untouched unit-admin arrangement
    if m and not m.unit_roles.exists():
        m.role = m.prior_role if m.prior_role in ("learner", "manager") else "learner"
        m.unit_scoped, m.prior_role = False, ""
        m.save(update_fields=["role", "unit_scoped", "prior_role"])


@receiver(post_delete, sender=UnitAdmin)
def _unit_admin_gone(sender, instance, **kw):
    release_scope(
        instance.membership_id
    )  # covers explicit removal and unit (or parent unit) deletion cascades


def kb_heir(org_id: int, leaving_user_id: int):
    """Who takes over an org's knowledge-base documents: an owner, else an admin (never the person leaving)."""
    for role in ("owner", "admin"):
        m = (
            Membership.objects.filter(org_id=org_id, role=role)
            .exclude(user_id=leaving_user_id)
            .order_by("joined_at")
            .first()
        )
        if m:
            return m.user_id
    return None


def hand_over_kb(org_id: int, user_id: int):
    """The person leaves the org or drops below admin: the org's knowledge-base documents they own go to the heir."""
    from apps.docs.models import Document

    from .models import OrgDocument

    ods = OrgDocument.objects.filter(org_id=org_id, source="kb", document__owner_id=user_id)
    if ods.exists() and (heir := kb_heir(org_id, user_id)):
        Document.objects.filter(shared_in__in=ods).update(owner_id=heir)


@receiver(post_delete, sender=Membership)
def _member_gone(sender, instance, **kw):
    hand_over_kb(instance.org_id, instance.user_id)


@receiver(pre_delete, sender=settings.AUTH_USER_MODEL, dispatch_uid="orgs_anonymise_training_records")
def _account_deleted(sender, instance, **kw):
    """Training records outlive the account (organisations keep the evidence) but no longer name the person."""
    from .models import TrainingRecord

    TrainingRecord.anonymise(instance)
