"""Admin console: organisations.

GET   orgs/            ?q= &kind= &filter=suspended|paying &page= &export=csv
GET   orgs/<id>/       members by role, seats paid vs used, subscription, features, branding, DPA, certificates
PATCH orgs/<id>/       {features: {name: bool}, workshop_seats, suspended: bool, suspended_reason, sso_enabled: false}
"""

from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.admin_paging import paged
from apps.accounts.staff import AdminSection, has_role

from .extras import FEATURES, PLATFORM_FEATURES, feature_on
from .models import Membership, Organization
from .sso import admin_disable, admin_summary


def _row(o) -> dict:
    from apps.billing.services import seats_total

    return {
        "id": o.id,
        "name": o.display_name or o.name,
        "slug": o.slug,
        "kind": o.kind,
        "members": getattr(o, "n_members", None),
        "seats_paid": seats_total(o),
        "seats_used": getattr(o, "n_seats", None),
        "workshop_seats": o.workshop_seats,
        "suspended": bool(o.suspended_at),
        "created_at": o.created_at,
    }


def _annotated():
    return Organization.objects.annotate(
        n_members=Count("memberships", distinct=True),
        n_seats=Count("memberships", filter=Q(memberships__seat=True), distinct=True),
    )


@api_view(["GET"])
@permission_classes([AdminSection])
def orgs(request):
    from apps.billing.models import OrgSubscription

    qs = _annotated().order_by("name")
    if q := str(request.query_params.get("q") or "").strip()[:80]:
        qs = qs.filter(Q(name__icontains=q) | Q(slug__icontains=q) | Q(display_name__icontains=q))
    if (kind := request.query_params.get("kind")) in Organization.Kind.values:
        qs = qs.filter(kind=kind)
    f = request.query_params.get("filter")
    if f == "suspended":
        qs = qs.exclude(suspended_at=None)
    elif f == "paying":
        now = timezone.now()
        qs = qs.filter(
            id__in=OrgSubscription.objects.filter(starts_at__lte=now, ends_at__gt=now).values("org_id")
        )
    by_kind = dict(Organization.objects.values_list("kind").annotate(n=Count("id")))
    return paged(request, qs, _row, name="organisations", extra={"by_kind": by_kind})


def _detail(o: Organization) -> dict:
    from apps.billing.services import active_seat_sub
    from apps.credentials.models import Certificate
    from apps.workshops.org import seats_used

    roles = dict(Membership.objects.filter(org=o).values_list("role").annotate(n=Count("id")))
    sub = active_seat_sub(o.pk)
    owners = Membership.objects.filter(org=o, role__in=["owner", "admin"]).select_related("user")[:20]
    return {
        **_row(_annotated().get(pk=o.pk)),
        "name_legal": o.name,
        "display_name": o.display_name,
        "description": o.description,
        "members_by_role": roles,
        "admins": [{"id": m.user_id, "email": m.user.email, "role": m.role} for m in owners],
        "subscription": {
            "plan": sub.plan.name if sub and getattr(sub, "plan", None) else None,
            "seats": sub.seats,
            "starts_at": sub.starts_at,
            "ends_at": sub.ends_at,
        }
        if sub
        else None,
        "features": {f: feature_on(o, f) for f in FEATURES},
        "platform_features": list(PLATFORM_FEATURES),
        "workshop_seats_used": len(seats_used(o, timezone.now())),
        "branding": {"brand_color": o.brand_color, "logo_url": o.logo_url},
        "dpa": {"version": o.dpa_version, "accepted_at": o.dpa_accepted_at},
        "suspended_at": o.suspended_at,
        "suspended_reason": o.suspended_reason,
        "certificates": Certificate.objects.filter(org=o).count(),
        "sso": admin_summary(o),
    }


@api_view(["GET", "PATCH"])
@permission_classes([AdminSection])
def org_detail(request, pk):
    o = get_object_or_404(Organization, pk=pk)
    if request.method == "GET":
        return Response(_detail(o))
    if not has_role(request.user, "support"):
        return Response(
            {"code": "role_required"}, status=status.HTTP_403_FORBIDDEN
        )  # finance can look, not change
    data = request.data if isinstance(request.data, dict) else {}
    with transaction.atomic():
        o = Organization.objects.select_for_update().get(pk=o.pk)
        fields = []
        if "features" in data:
            feats = data["features"]
            if not isinstance(feats, dict) or not all(
                k in FEATURES and isinstance(v, bool) for k, v in feats.items()
            ):
                return Response({"code": "bad_features"}, status=status.HTTP_400_BAD_REQUEST)
            # Stored explicitly either way. Platform features (workshops) are on by default, so switching one
            # off stores False, which also keeps the org's learners out of workshops (orgs.extras.blocked).
            o.features = {**(o.features or {}), **feats}
            fields.append("features")
        if "workshop_seats" in data:
            n = data["workshop_seats"]
            if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= 100000:
                return Response({"code": "bad_workshop_seats"}, status=status.HTTP_400_BAD_REQUEST)
            o.workshop_seats = n
            fields.append("workshop_seats")
        if "suspended" in data:
            if not isinstance(data["suspended"], bool):
                return Response({"code": "bad_suspended"}, status=status.HTTP_400_BAD_REQUEST)
            o.suspended_at = (o.suspended_at or timezone.now()) if data["suspended"] else None
            o.suspended_reason = str(data.get("suspended_reason") or "")[:200] if data["suspended"] else ""
            fields += ["suspended_at", "suspended_reason"]
        if "sso_enabled" in data:  # support break-glass: only ever switches SSO off
            if data["sso_enabled"] is not False:
                return Response({"code": "sso_off_only"}, status=status.HTTP_400_BAD_REQUEST)
            admin_disable(o)
        if fields:
            o.save(update_fields=fields)
    return Response(_detail(o))
