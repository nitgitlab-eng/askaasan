"""Family plan: one buyer (the owner) shares a family plan with up to `plan.max_members` people in all.

Members get mirrored Entitlement rows (source="family", derived_from = the owner's row), so plan limits, paid_until,
reminders and the admin console treat them like any other window. `resync(group)` is the one place that writes those
mirrors; every change to the owner's access (checkout, renewal, grace, codes, manual grants via `services._extend`,
refunds and ended grace via `resync_owner`) and every join/leave calls it."""

import hashlib
import logging
import secrets
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Entitlement, FamilyGroup, FamilyInvite, FamilyMember, Plan

log = logging.getLogger(__name__)

INVITE_DAYS = 7
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LEN = 6


class FamilyError(Exception):
    def __init__(self, code: str, http: int = 409):
        super().__init__(code)
        self.code, self.http = code, http


# ── Invite secrets: only hashes are stored ───────────────────────────


def hash_secret(raw: str) -> str:
    return hashlib.sha256(f"family:{raw}".encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(24)


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))


def norm_code(raw) -> str:
    return "".join(ch for ch in str(raw or "").upper() if ch.isalnum())[:CODE_LEN]


def pending_invites(group):
    return FamilyInvite.objects.filter(
        group=group, accepted_at__isnull=True, revoked_at__isnull=True, expires_at__gt=timezone.now()
    )


# ── Who is in which family ──────────────────────────────────────────


def owner_family_ent(owner) -> Entitlement | None:
    """The owner's own window on a family plan that runs latest (highest price first), if any is still running."""
    return (
        Entitlement.objects.filter(user=owner, plan__family=True, ends_at__gt=timezone.now())
        .exclude(source="family")
        .select_related("plan")
        .order_by("-plan__price_paise", "-ends_at")
        .first()
    )


def family_plan(owner) -> Plan | None:
    ent = owner_family_ent(owner)
    return ent.plan if ent else None


def membership_of(user) -> FamilyMember | None:
    return (
        FamilyMember.objects.filter(user=user, left_at__isnull=True)
        .select_related("group", "group__owner")
        .first()
    )


def active_members(group):
    return FamilyMember.objects.filter(group=group, left_at__isnull=True)


def ensure_group(owner) -> FamilyGroup:
    """The owner's group (with the owner's own seat), created on first use. Refused while they are in another family."""
    with transaction.atomic():
        group, _ = FamilyGroup.objects.get_or_create(owner=owner)
        group = FamilyGroup.objects.select_for_update(of=("self",)).get(pk=group.pk)
        mine = membership_of(owner)
        if mine and mine.group_id != group.pk:
            raise FamilyError("family_already")
        if not mine:
            try:
                with transaction.atomic():
                    FamilyMember.objects.create(group=group, user=owner)
            except IntegrityError as e:
                raise FamilyError("family_already") from e
    return group


# ── Mirrors ─────────────────────────────────────────────────────────


def resync(group: FamilyGroup) -> None:
    """Mirror the owner's family-plan windows onto every active member; cut the mirrors of anyone who left (or whose
    source window ended) to now, and tell people who lost access."""
    cut_users = set()
    with transaction.atomic():
        group = FamilyGroup.objects.select_for_update(of=("self",)).get(pk=group.pk)
        now = timezone.now()
        sources = {
            e.id: e
            for e in Entitlement.objects.filter(user_id=group.owner_id, plan__family=True, ends_at__gt=now)
            .exclude(source="family")
            .select_related("plan")
        }
        members = set(active_members(group).exclude(user_id=group.owner_id).values_list("user_id", flat=True))
        for m in Entitlement.objects.filter(family_group=group, source="family", ends_at__gt=now):
            if m.user_id in members and m.derived_from_id in sources:
                continue  # brought up to date below
            m.starts_at, m.ends_at = min(m.starts_at, now), now
            m.save(update_fields=["starts_at", "ends_at"])
            if m.user_id not in members:
                cut_users.add(m.user_id)
        for src in sources.values():
            for uid in members:
                Entitlement.objects.update_or_create(
                    derived_from=src,
                    user_id=uid,
                    defaults={
                        "plan": src.plan,
                        "starts_at": src.starts_at,
                        "ends_at": src.ends_at,
                        "source": "family",
                        "family_group": group,
                        "note": "family plan",
                    },
                )
        if cut_users:
            ids = sorted(cut_users)
            transaction.on_commit(lambda: _tell_cut(ids))


def resync_owner(user) -> None:
    group = FamilyGroup.objects.filter(owner=user).first()
    if group:
        resync(group)


def on_owner_grant(ent: Entitlement) -> None:
    """Hook from services._extend: a new window for someone who owns a family reaches the members."""
    if ent.source == "family" or not ent.plan.family:
        return
    resync_owner(ent.user)


def _tell_cut(user_ids) -> None:
    from django.contrib.auth import get_user_model

    from .reminders import _notify

    for u in get_user_model().objects.filter(id__in=user_ids):
        try:
            _notify(
                u,
                "Your family plan access has ended",
                "You're no longer part of a family plan on Aasan. Everything you made is still here.",
            )
        except Exception:  # a notice must never break billing
            log.exception("family notice failed")


# ── Joining and leaving ─────────────────────────────────────────────


def join(group: FamilyGroup, user, invite: FamilyInvite | None = None) -> FamilyMember:
    from .services import seat_plan

    with transaction.atomic():
        group = FamilyGroup.objects.select_for_update(of=("self",)).get(pk=group.pk)
        if membership_of(user):
            raise FamilyError("family_already")
        plan = family_plan(group.owner)
        if not plan:
            raise FamilyError("family_inactive", 410)
        seat = seat_plan(user)
        if seat and seat.price_paise >= plan.price_paise:
            raise FamilyError("seat_covered")
        if active_members(group).count() >= plan.max_members:
            raise FamilyError("family_full")
        try:
            with transaction.atomic():
                m = FamilyMember.objects.create(group=group, user=user)
        except IntegrityError as e:
            raise FamilyError("family_already") from e
        if invite:
            invite.accepted_at = timezone.now()
            invite.save(update_fields=["accepted_at"])
        resync(group)
    return m


def leave(member: FamilyMember, by=None) -> None:
    """A member leaves (or is removed by the owner). The owner leaving disbands the family."""
    with transaction.atomic():
        group = FamilyGroup.objects.select_for_update(of=("self",)).get(pk=member.group_id)
        now = timezone.now()
        if member.user_id == group.owner_id:
            active_members(group).update(left_at=now)
            pending_invites(group).update(revoked_at=now)
        else:
            FamilyMember.objects.filter(pk=member.pk, left_at__isnull=True).update(
                left_at=now, removed_by=by if by and by.pk != member.user_id else None
            )
        resync(group)


def invite_expiry():
    return timezone.now() + timedelta(days=INVITE_DAYS)
