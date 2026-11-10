"""Family plan endpoints (signed-in learners) and the admin lists for families and gifts.

GET    /api/billing/family/                       my family: owner view, member view, or none
POST   /api/billing/family/invite/                {email}  owner only; always 201 (never says who has an account)
DELETE /api/billing/family/invites/<id>/          owner revokes a pending invite
GET    /api/billing/family/invites/<token>/       preview an invite link
POST   /api/billing/family/accept/                {token} or {code}
POST   /api/billing/family/members/<id>/remove/   owner removes a member
POST   /api/billing/family/leave/                 a member leaves; the owner leaving disbands the family
GET    /api/admin/family-groups/                  ?q= &page= &export=csv  (finance, support)
GET    /api/admin/gifts/                          ?q= &status= &page= &export=csv  (finance)
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from apps.accounts import counters
from apps.accounts.admin_paging import paged
from apps.accounts.staff import AdminSection

from . import family as fam
from .models import FamilyGroup, FamilyInvite, FamilyMember, Gift

log = logging.getLogger(__name__)

INVITES_PER_GROUP_DAY = 20
ACCEPT_FAILS_PER_HOUR = 10
INVITE_SUBJECT = "You're invited to share an Aasan family plan"


def _name(user) -> str:
    profile = getattr(user, "profile", None)
    return (getattr(profile, "display_name", "") or user.email.split("@")[0])[:80]


def _hint(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:2]}…@{domain}"


def family_state(user) -> dict:
    """What the Plans and Account pages show about families. Members never see other members' email addresses."""
    m = fam.membership_of(user)
    plan_ent = fam.owner_family_ent(user)
    if not m:
        return {
            "role": None,
            "can_create": bool(plan_ent),
            "plan": {"code": plan_ent.plan.code, "name": plan_ent.plan.name} if plan_ent else None,
            "max_members": plan_ent.plan.max_members if plan_ent else 0,
        }
    group = m.group
    owner = group.owner
    is_owner = owner.pk == user.pk
    ent = plan_ent if is_owner else fam.owner_family_ent(owner)
    members = list(fam.active_members(group).select_related("user__profile"))
    max_members = ent.plan.max_members if ent else 0
    out = {
        "role": "owner" if is_owner else "member",
        "can_create": False,
        "plan": {"code": ent.plan.code, "name": ent.plan.name} if ent else None,
        "max_members": max_members,
        "active_until": ent.ends_at if ent else None,
        "owner_name": _name(owner),
        "members": [
            {
                "id": x.id,
                "name": _name(x.user),
                "is_owner": x.user_id == owner.pk,
                "is_me": x.user_id == user.pk,
                "joined_at": x.joined_at,
                **({"email": x.user.email} if is_owner else {}),
            }
            for x in members
        ],
    }
    if is_owner:
        invites = list(fam.pending_invites(group).order_by("-created_at"))
        out["invites"] = [{"id": i.id, "email": i.email, "expires_at": i.expires_at} for i in invites]
        out["seats_left"] = max(0, max_members - len(members) - len(invites))
    return out


@api_view(["GET"])
def family(request):
    return Response(family_state(request.user))


class FamilyInviteThrottle(UserRateThrottle):
    scope = "family_invite"
    rate = "20/hour"


def _send_invite(inv: FamilyInvite, token: str, code: str, owner, plan_name: str) -> dict | None:
    """Email one invite → None when sent, else {email, link, code} for the owner to share by hand."""
    from apps.legal.mail import mail_ready

    link = f"{settings.FRONTEND_URL}/family/{token}"
    if mail_ready():
        try:
            send_mail(
                INVITE_SUBJECT,
                f"{_name(owner)} invited you to share their {plan_name} on Aasan.\n\n"
                f"Open this link and sign in with this email address to join:\n{link}\n\n"
                f"Or enter the code {code} on the Plans page. The invitation works for {fam.INVITE_DAYS} days.",
                None,
                [inv.email],
                fail_silently=False,
            )
            return None
        except Exception:
            log.warning("family invite mail failed for invite %s", inv.id, exc_info=True)
    return {"email": inv.email, "link": link, "code": code}


@api_view(["POST"])
@throttle_classes([FamilyInviteThrottle])
def invite(request):
    from apps.orgs.api import invite_mail_out

    email = str(request.data.get("email") or "").strip().lower()[:254]
    try:
        validate_email(email)
    except ValidationError:
        return Response({"code": "bad_email"}, status=status.HTTP_400_BAD_REQUEST)
    plan = fam.family_plan(request.user)
    if not plan:
        return Response({"code": "no_family_plan"}, status=status.HTTP_409_CONFLICT)
    if email == request.user.email.lower():
        return Response({"code": "invite_self"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        group = fam.ensure_group(request.user)
    except fam.FamilyError as e:
        return Response({"code": e.code}, status=e.http)
    with transaction.atomic():
        group = FamilyGroup.objects.select_for_update(of=("self",)).get(pk=group.pk)
        if (
            FamilyInvite.objects.filter(
                group=group, created_at__gte=timezone.now() - timedelta(days=1)
            ).count()
            >= INVITES_PER_GROUP_DAY
        ):
            return Response({"code": "invite_limit"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        now = timezone.now()
        # a resend replaces the earlier invite: one live link per address
        fam.pending_invites(group).filter(email__iexact=email).update(revoked_at=now)
        if fam.active_members(group).count() + fam.pending_invites(group).count() >= plan.max_members:
            return Response({"code": "family_full"}, status=status.HTTP_409_CONFLICT)
        token, code = fam.new_token(), fam.new_code()
        inv = FamilyInvite.objects.create(
            group=group,
            email=email,
            token_hash=fam.hash_secret(token),
            code_hash=fam.hash_secret(code),
            invited_by=request.user,
            expires_at=fam.invite_expiry(),
        )
    miss = _send_invite(inv, token, code, request.user, plan.name)
    return Response(
        {
            "invite": {"id": inv.id, "email": inv.email, "expires_at": inv.expires_at},
            **invite_mail_out([miss] if miss else []),
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["DELETE"])
def invite_detail(request, pk):
    inv = get_object_or_404(
        FamilyInvite, pk=pk, group__owner=request.user, accepted_at__isnull=True, revoked_at__isnull=True
    )
    inv.revoked_at = timezone.now()
    inv.save(update_fields=["revoked_at"])
    return Response(status=status.HTTP_204_NO_CONTENT)


def _invite_by_token(token: str) -> FamilyInvite | None:
    if not token or len(token) > 64:
        return None
    return (
        FamilyInvite.objects.filter(token_hash=fam.hash_secret(token))
        .select_related("group__owner__profile")
        .first()
    )


def _usable(inv: FamilyInvite | None) -> str | None:
    if not inv or inv.revoked_at:
        return "invite_invalid"
    if inv.accepted_at:
        return "invite_used"
    if inv.expires_at <= timezone.now():
        return "invite_expired"
    return None


@api_view(["GET"])
def invite_preview(request, token):
    inv = _invite_by_token(token)
    problem = _usable(inv)
    if problem == "invite_invalid":
        return Response({"code": problem}, status=status.HTTP_404_NOT_FOUND)
    plan = fam.family_plan(inv.group.owner)
    return Response(
        {
            "owner_name": _name(inv.group.owner),
            "plan": plan.name if plan else None,
            "email_hint": _hint(inv.email),
            "for_you": inv.email.lower() == request.user.email.lower(),
            "problem": problem or (None if plan else "family_inactive"),
            "expires_at": inv.expires_at,
        }
    )


@api_view(["POST"])
def accept(request):
    key = f"family-accept-fail:{request.user.id}"
    if counters.count(key) >= ACCEPT_FAILS_PER_HOUR:  # stops guessing codes
        return Response({"code": "too_many_attempts"}, status=status.HTTP_429_TOO_MANY_REQUESTS)

    def fail(code, http):
        counters.bump(key, 3600)
        return Response({"code": code}, status=http)

    token = str(request.data.get("token") or "").strip()
    code = fam.norm_code(request.data.get("code"))
    if token:
        inv = _invite_by_token(token)
    elif len(code) == fam.CODE_LEN:
        # A code is short, so it only counts together with the signed-in person's own email address.
        inv = (
            FamilyInvite.objects.filter(
                code_hash=fam.hash_secret(code),
                email__iexact=request.user.email,
                accepted_at__isnull=True,
                revoked_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .select_related("group__owner")
            .first()
        )
    else:
        inv = None
    problem = _usable(inv)
    if problem:
        return fail(
            problem, status.HTTP_404_NOT_FOUND if problem == "invite_invalid" else status.HTTP_410_GONE
        )
    if inv.email.lower() != request.user.email.lower():
        return fail("invite_not_for_you", status.HTTP_403_FORBIDDEN)
    if (
        not request.user.email_verified
    ):  # the email match only proves inbox control once the address is verified
        return Response({"code": "verify_email_first"}, status=status.HTTP_403_FORBIDDEN)
    try:
        fam.join(inv.group, request.user, invite=inv)
    except fam.FamilyError as e:
        return Response({"code": e.code}, status=e.http)
    return Response(family_state(request.user))


@api_view(["POST"])
def remove_member(request, pk):
    m = get_object_or_404(FamilyMember, pk=pk, group__owner=request.user, left_at__isnull=True)
    if m.user_id == request.user.pk:
        return Response({"code": "owner_cannot_be_removed"}, status=status.HTTP_400_BAD_REQUEST)
    fam.leave(m, by=request.user)
    return Response(family_state(request.user))


@api_view(["POST"])
def leave(request):
    m = fam.membership_of(request.user)
    if not m:
        return Response({"code": "not_in_family"}, status=status.HTTP_404_NOT_FOUND)
    fam.leave(m, by=request.user)
    return Response(family_state(request.user))


# ── Admin ───────────────────────────────────────────────────────────


@api_view(["GET"])
@permission_classes([AdminSection])
def admin_family_groups(request):
    qs = (
        FamilyGroup.objects.select_related("owner")
        .annotate(n=Count("members", filter=Q(members__left_at__isnull=True), distinct=True))
        .order_by("-created_at")
    )
    if q := str(request.query_params.get("q") or "").strip()[:80]:
        qs = qs.filter(
            Q(owner__email__icontains=q)
            | Q(members__user__email__icontains=q, members__left_at__isnull=True)
            | Q(invites__email__icontains=q)
        ).distinct()

    def row(g):
        ent = fam.owner_family_ent(g.owner)
        return {
            "id": g.id,
            "owner": g.owner.email,
            "plan": ent.plan.name if ent else None,
            "active_until": ent.ends_at if ent else None,
            "max_members": ent.plan.max_members if ent else 0,
            "members_count": g.n,
            "members": [
                m.user.email for m in fam.active_members(g).select_related("user").exclude(user_id=g.owner_id)
            ],
            "pending_invites": fam.pending_invites(g).count(),
            "created_at": g.created_at,
        }

    return paged(
        request,
        qs,
        row,
        name="family-groups",
        extra={
            "groups": FamilyGroup.objects.count(),
            "members": FamilyMember.objects.filter(left_at__isnull=True).count(),
        },
    )


def gift_status(g: Gift) -> str:
    rc = g.redeem_code
    if g.order.status != "paid":
        return "unpaid"
    if g.claimed_at or (rc and rc.redeemed_at):
        return "claimed"
    if not rc:
        return "pending"
    if rc.expires_at and rc.expires_at <= timezone.now():
        return "void"
    return "sent" if g.sent_at else "not_sent"


@api_view(["GET"])
@permission_classes([AdminSection])
def admin_gifts(request):
    qs = Gift.objects.select_related("order__user", "order__plan", "redeem_code").order_by("-created_at")
    if q := str(request.query_params.get("q") or "").strip()[:80]:
        qs = qs.filter(Q(order__user__email__icontains=q) | Q(recipient_email__icontains=q))
    if request.query_params.get("paid") != "all":
        qs = qs.filter(order__status="paid")

    def row(g):
        rc = g.redeem_code
        return {
            "id": g.id,
            "order_id": g.order_id,
            "buyer": g.order.user.email if g.order.user else "(deleted account)",
            "recipient": g.recipient_email,
            "plan": g.order.plan.name if g.order.plan_id else "",
            "amount_paise": g.order.amount_paise,
            "mode": g.order.mode,
            "status": gift_status(g),
            "code_last4": rc.code[-4:] if rc else "",
            "expires_at": rc.expires_at if rc else None,
            "created_at": g.created_at,
            "sent_at": g.sent_at,
            "claimed_at": g.claimed_at,
        }

    return paged(request, qs, row, name="gifts")
