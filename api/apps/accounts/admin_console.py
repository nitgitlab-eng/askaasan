"""Admin console: staff roles, the audit log, and user management.

GET  staff/                      staff members and their roles                  (superadmin)
POST staff/                      {email, roles: [...]} — [] removes staff access (superadmin)
GET  audit/                      ?q= &section= &page= &export=csv               (superadmin)
GET  users/                      ?q= &filter=staff|creator|inactive|unverified|minor|paying &page= &export=csv
GET  users/<id>/                 one person: plans, orgs, courses, certificates, AI use, devices
POST users/<id>/action/          {action: deactivate|reactivate|force_logout|verify_email|set_creator|unset_creator}
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .admin_paging import paged
from .models import AdminAuditLog, StaffRole, User
from .staff import AdminSection, has_role, roles_of

admin_view = permission_classes([AdminSection])


def _name(u) -> str:
    prof = getattr(u, "profile", None)
    return getattr(prof, "display_name", "") or ""


# ── staff + roles ────────────────────────────────────────────────────


def _staff_out(u) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "name": _name(u),
        "roles": sorted(roles_of(u)),
        "superuser": u.is_superuser,
        "last_login": u.last_login,
    }


@api_view(["GET", "POST"])
@admin_view
def staff(request):
    if request.method == "GET":
        qs = (
            User.objects.filter(Q(is_staff=True) | Q(is_superuser=True))
            .select_related("profile")
            .order_by("email")
        )
        return Response([_staff_out(u) for u in qs[:500]])
    email = str(request.data.get("email") or "").strip().lower()
    roles = request.data.get("roles")
    if not isinstance(roles, list) or not all(r in StaffRole.ROLES for r in roles):
        return Response({"code": "bad_roles", "roles": StaffRole.ROLES}, status=status.HTTP_400_BAD_REQUEST)
    user = User.objects.filter(email=email).first()
    if not user:
        return Response({"code": "user_not_found"}, status=status.HTTP_404_NOT_FOUND)
    if user.is_superuser:
        return Response(
            {"code": "superuser_fixed"}, status=status.HTTP_409_CONFLICT
        )  # managed outside the console
    with transaction.atomic():
        removing_super = "superadmin" in roles_of(user) and "superadmin" not in roles
        if removing_super:
            if user == request.user:
                return Response({"code": "cannot_demote_self"}, status=status.HTTP_409_CONFLICT)
            others = [
                u
                for u in User.objects.filter(is_staff=True).exclude(pk=user.pk)
                if "superadmin" in roles_of(u)
            ]
            if not others and not User.objects.filter(is_superuser=True).exists():
                return Response({"code": "last_superadmin"}, status=status.HTTP_409_CONFLICT)
        user.is_staff = bool(roles)
        user.save(update_fields=["is_staff"])
        if roles:
            StaffRole.objects.update_or_create(
                user=user, defaults={"roles": sorted(set(roles)), "updated_by": request.user}
            )
        else:
            StaffRole.objects.filter(user=user).delete()
            from .tokens import revoke_all_sessions

            revoke_all_sessions(user, "staff access removed")  # admin tokens in the wild stop working now
    return Response(_staff_out(user))


# ── audit log ────────────────────────────────────────────────────────


def _audit_out(a: AdminAuditLog) -> dict:
    return {
        "id": a.id,
        "at": a.at,
        "actor": a.actor_email,
        "method": a.method,
        "path": a.path,
        "section": a.section,
        "target": a.target,
        "data": a.data,
        "status": a.status,
        "ip": a.ip,
    }


@api_view(["GET"])
@admin_view
def audit(request):
    qs = AdminAuditLog.objects.all()
    if q := str(request.query_params.get("q") or "").strip()[:80]:
        qs = qs.filter(Q(actor_email__icontains=q) | Q(path__icontains=q) | Q(target__icontains=q))
    if sec := str(request.query_params.get("section") or "").strip()[:40]:
        qs = qs.filter(section=sec)
    return paged(request, qs, _audit_out, name="audit")


# ── users ────────────────────────────────────────────────────────────

FILTERS = {
    "staff": Q(is_staff=True) | Q(is_superuser=True),
    "creator": Q(is_creator=True),
    "inactive": Q(is_active=False),
    "unverified": Q(email_verified=False),
    "minor": Q(age_band="minor"),
}


def _user_row(u) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "name": _name(u),
        "joined": u.date_joined,
        "last_login": u.last_login,
        "active": u.is_active,
        "verified": u.email_verified,
        "staff": u.is_staff or u.is_superuser,
        "creator": u.is_creator,
        "minor": u.age_band == "minor",
        "orgs": getattr(u, "n_orgs", None),
        "courses": getattr(u, "n_courses", None),
    }


@api_view(["GET"])
@admin_view
def users(request):
    from apps.billing.models import Entitlement

    qs = User.objects.select_related("profile").annotate(
        n_orgs=Count("memberships", distinct=True), n_courses=Count("curriculums", distinct=True)
    )
    if q := str(request.query_params.get("q") or "").strip()[:80]:
        qs = qs.filter(
            Q(email__icontains=q)
            | Q(profile__display_name__icontains=q)
            | Q(memberships__org__name__icontains=q)
        ).distinct()
    f = request.query_params.get("filter")
    if f in FILTERS:
        qs = qs.filter(FILTERS[f])
    elif f == "paying":
        now = timezone.now()
        qs = qs.filter(
            id__in=Entitlement.objects.filter(starts_at__lte=now, ends_at__gt=now).values("user_id")
        )
    totals = {
        "total": User.objects.count(),
        "active_7d": User.objects.filter(last_login__gte=timezone.now() - timedelta(days=7)).count(),
    }
    return paged(request, qs.order_by("-date_joined"), _user_row, name="users", extra={"totals": totals})


def _detail(u: User) -> dict:
    from apps.billing.models import Entitlement, Order
    from apps.credentials.models import Certificate
    from apps.extension.models import ExtensionToken
    from apps.learning.models import Curriculum, Enrollment
    from apps.orgs.models import Membership
    from apps.providers.models import LLMUsage

    now = timezone.now()
    paid = Order.objects.filter(user=u, status="paid")
    since = now - timedelta(days=30)
    ai = LLMUsage.objects.filter(user=u, created_at__gte=since).aggregate(
        calls=Count("id"), tin=Sum("input_tokens"), tout=Sum("output_tokens")
    )
    return {
        **_user_row(u),
        "roles": sorted(roles_of(u)),
        "age_band": u.age_band,
        "guardian_email": u.guardian_email,
        "terms_version": u.terms_version,
        "plans": [
            {
                "plan": e.plan.name,
                "source": e.source,
                "starts_at": e.starts_at,
                "ends_at": e.ends_at,
                "active": e.starts_at <= now < e.ends_at,
                "note": e.note,
            }
            for e in Entitlement.objects.filter(user=u).select_related("plan").order_by("-ends_at")[:20]
        ],
        "payments": {
            "count": paid.count(),
            "total_paise": paid.filter(mode="live").aggregate(t=Sum("amount_paise"))["t"] or 0,
        },
        "orgs": [
            {"id": m.org_id, "name": m.org.display_name or m.org.name, "slug": m.org.slug, "role": m.role}
            for m in Membership.objects.filter(user=u).select_related("org")[:50]
        ],
        "courses": {
            "own": Curriculum.objects.filter(owner=u).count(),
            "enrolled": Enrollment.objects.filter(user=u).count(),
        },
        "certificates": [
            {
                "id": c.id,
                "title": c.title,
                "kind": c.kind,
                "issued_at": c.issued_at,
                "revoked": bool(c.revoked_at),
            }
            for c in Certificate.objects.filter(user=u).order_by("-issued_at")[:20]
        ],
        "ai_30d": {"calls": ai["calls"], "tokens": (ai["tin"] or 0) + (ai["tout"] or 0)},
        "devices": {
            "passkeys": u.passkeys.count(),
            "extension": ExtensionToken.objects.filter(user=u).count(),
        },
    }


@api_view(["GET"])
@admin_view
def user_detail(request, pk):
    u = get_object_or_404(User.objects.select_related("profile"), pk=pk)
    return Response(_detail(u))


ACTIONS = {
    # action → roles allowed (superadmin always)
    "deactivate": ("support",),
    "reactivate": ("support",),
    "force_logout": ("support",),
    "verify_email": ("support",),
    "set_creator": ("support", "content"),
    "unset_creator": ("support", "content"),
}


@api_view(["POST"])
@admin_view
def user_action(request, pk):
    from .tokens import revoke_all_sessions

    u = get_object_or_404(User, pk=pk)
    action = request.data.get("action")
    if action not in ACTIONS:
        return Response({"code": "bad_action", "actions": list(ACTIONS)}, status=status.HTTP_400_BAD_REQUEST)
    if not has_role(request.user, *ACTIONS[action]):
        return Response({"code": "role_required"}, status=status.HTTP_403_FORBIDDEN)
    if (u.is_staff or u.is_superuser) and "superadmin" not in roles_of(request.user):
        return Response(
            {"code": "staff_target"}, status=status.HTTP_403_FORBIDDEN
        )  # only superadmins touch staff
    if u == request.user and action in ("deactivate", "force_logout"):
        return Response({"code": "not_yourself"}, status=status.HTTP_409_CONFLICT)
    if action == "deactivate":
        u.is_active = False
        u.save(update_fields=["is_active"])
        revoke_all_sessions(u, "deactivated by admin")
    elif action == "reactivate":
        u.is_active = True
        u.save(update_fields=["is_active"])
    elif action == "force_logout":
        revoke_all_sessions(u, "signed out by admin")
    elif action == "verify_email":
        u.email_verified = True
        u.save(update_fields=["email_verified"])
    else:
        u.is_creator = action == "set_creator"
        u.save(update_fields=["is_creator"])
    u.refresh_from_db()
    return Response(_detail(u))
