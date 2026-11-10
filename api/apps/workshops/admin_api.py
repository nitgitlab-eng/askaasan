"""Staff scheduling of public workshop runs (/api/admin/workshops/runs/): create, edit, publish, announce, cancel and
aggregate-only stats. Every view is staff-only."""

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.staff import AdminSection

from . import public, services
from .models import PROCTORING, Workshop, WorkshopRun

staff_only = permission_classes([AdminSection])
Status = WorkshopRun.Status
EDITABLE = (Status.DRAFT, Status.SCHEDULED)
PROCTORING_KEYS = {"", *(k for k, _ in PROCTORING)}


def _public_runs():
    return WorkshopRun.objects.filter(audience=WorkshopRun.Audience.PUBLIC).select_related("workshop")


def _int(v, lo: int, hi: int):
    if isinstance(v, bool):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi and str(n) == str(v).strip() else None


def _clean(data, run=None) -> tuple[dict, str | None]:
    """→ (validated fields, None) or ({}, "bad_<field>"). On create every field may be given; on edit only the given
    ones are checked. Times must be ISO 8601 with a zone and in the future."""
    out = {}
    if "workshop_slug" in data or run is None:
        w = Workshop.objects.filter(slug=str(data.get("workshop_slug") or ""), is_published=True).first()
        if not w:
            return {}, "bad_workshop"
        out["workshop"] = w
    if "starts_at" in data or run is None:
        at = parse_datetime(str(data.get("starts_at") or ""))
        if not at or at.tzinfo is None or at <= services.now():
            return {}, "bad_starts_at"
        out["starts_at"] = at
    rules = {
        "capacity": (0, public.CAPACITY_MAX, 0),
        "price_paise": (0, public.PRICE_MAX, 0),
        "late_join_minutes": (0, 60, 15),
        "lobby_opens_minutes": (5, 60, 15),
    }
    for key, (lo, hi, default) in rules.items():
        if key in data:
            n = _int(data[key], lo, hi)
            if n is None or key == "price_paise" and 0 < n < public.PRICE_MIN:
                return {}, f"bad_{key.removesuffix('_minutes').removesuffix('_paise')}"
            out[key] = n
        elif run is None:
            out[key] = default
    if "proctoring" in data:
        if data["proctoring"] not in PROCTORING_KEYS:
            return {}, "bad_proctoring"
        out["proctoring"] = data["proctoring"]
    if "capacity" in out:
        out["capacity"] = out["capacity"] or None  # 0 = unlimited
    return out, None


@api_view(["GET", "POST"])
@staff_only
def runs(request):
    if request.method == "POST":
        data, code = _clean(request.data)
        if code:
            return Response({"code": code}, status=status.HTTP_400_BAD_REQUEST)
        run = WorkshopRun.objects.create(
            audience=WorkshopRun.Audience.PUBLIC, status=Status.DRAFT, created_by=request.user, **data
        )
        return Response(public.admin_out(run), status=status.HTTP_201_CREATED)
    at = services.now()
    rows = [public.admin_out(r, at) for r in public.with_counts(_public_runs()).order_by("-starts_at")[:500]]
    if want := request.query_params.get("status"):
        rows = [r for r in rows if r["status"] == want]
    return Response(rows)


def _locked(pk) -> WorkshopRun:
    """Inside a transaction: the public run, row-locked so state changes and enrolments serialise."""
    get_object_or_404(_public_runs(), pk=pk)
    return WorkshopRun.objects.select_for_update(of=("self",)).select_related("workshop").get(pk=pk)


def _seats_sold(run) -> bool:
    """Anyone enrolled, or a paid / in-flight order: the price is then fixed."""
    from apps.billing.models import Order
    from apps.billing.pricing import HOLD

    if run.enrollments.exists():
        return True
    recent = timezone.now() - HOLD
    return (
        Order.objects.filter(workshop_run=run)
        .filter(
            Q(status=Order.Status.PAID)
            | Q(status=Order.Status.CREATED, created_at__gte=recent)
            | Q(status=Order.Status.CREATED) & ~Q(rp_payment_id="")
        )
        .exists()
    )


@api_view(["GET", "PATCH"])
@staff_only
def run_detail(request, pk):
    if request.method == "GET":
        return Response(public.admin_out(get_object_or_404(public.with_counts(_public_runs()), pk=pk)))
    moved = False
    with transaction.atomic():
        run = _locked(pk)
        if run.effective_status(services.now()) not in EDITABLE:
            return Response({"code": "not_editable"}, status=status.HTTP_409_CONFLICT)
        data, code = _clean(request.data, run)
        if code:
            return Response({"code": code}, status=status.HTTP_400_BAD_REQUEST)
        if "workshop" in data and data["workshop"].pk != run.workshop_id and run.status != Status.DRAFT:
            return Response({"code": "workshop_locked"}, status=status.HTTP_409_CONFLICT)
        if "price_paise" in data and data["price_paise"] != run.price_paise and _seats_sold(run):
            return Response({"code": "price_locked"}, status=status.HTTP_409_CONFLICT)
        if data.get("capacity") and data["capacity"] < run.enrollments.count():
            return Response({"code": "capacity_below_enrolled"}, status=status.HTTP_409_CONFLICT)
        moved = "starts_at" in data and data["starts_at"] != run.starts_at
        for k, v in data.items():
            setattr(run, k, v)
        if moved:  # a new time: the reminders go again for it
            run.enrollments.update(reminded_24h=False, reminded_15m=False)
        run.save()
    if moved and run.enrollments.exists():
        from .tasks import notify_enrolled

        notify_enrolled.delay(run.id, "moved")
    return Response(public.admin_out(get_object_or_404(public.with_counts(_public_runs()), pk=pk)))


@api_view(["POST"])
@staff_only
def run_publish(request, pk):
    with transaction.atomic():
        run = _locked(pk)
        if run.status == Status.SCHEDULED:
            return Response(public.admin_out(run))  # idempotent
        if run.status != Status.DRAFT:
            return Response({"code": "not_draft"}, status=status.HTTP_409_CONFLICT)
        if run.starts_at <= services.now():
            return Response({"code": "starts_in_past"}, status=status.HTTP_409_CONFLICT)
        run.status = Status.SCHEDULED
        run.save(update_fields=["status"])
    return Response(public.admin_out(run))


@api_view(["POST"])
@staff_only
def run_announce(request, pk):
    """Once per run: queue the platform-wide notification. A repeat call changes nothing and says so."""
    with transaction.atomic():
        run = _locked(pk)
        if run.announced_at:
            return Response({**public.admin_out(run), "already_announced": True})
        if run.effective_status(services.now()) != Status.SCHEDULED:
            return Response({"code": "not_scheduled"}, status=status.HTTP_409_CONFLICT)
        run.announced_at = services.now()
        run.save(update_fields=["announced_at"])
    from .tasks import announce_run

    announce_run.delay(run.id)  # after the commit, so the worker sees announced_at and the run
    return Response({**public.admin_out(run), "already_announced": False})


@api_view(["POST"])
@staff_only
def run_cancel(request, pk):
    with transaction.atomic():
        run = _locked(pk)
        if run.status == Status.CANCELLED:
            return Response({**public.admin_out(run), "refunds_due": 0})
        if run.effective_status(services.now()) == Status.ENDED:
            return Response({"code": "run_ended"}, status=status.HTTP_409_CONFLICT)
        refunds = public.cancel(run, request.user)
    if run.enrollments.exists():
        from .tasks import notify_enrolled

        notify_enrolled.delay(run.id, "cancelled")
    return Response({**public.admin_out(run), "refunds_due": refunds})


@api_view(["GET"])
@staff_only
def run_stats(request, pk):
    run = get_object_or_404(_public_runs(), pk=pk)
    return Response({"id": run.id, "status": run.effective_status(services.now()), **public.stats(run)})


# ── Institution workshops: the platform admin's per-org switch (on by default) and monthly seats ──


def _org_out(org) -> dict:
    from apps.orgs.extras import feature_on

    from .org import seats_used

    return {
        "id": org.id,
        "slug": org.slug,
        "name": org.display_name or org.name,
        "kind": org.kind,
        "members": org.memberships.count(),
        "workshops": feature_on(org, "workshops"),
        "workshop_seats": org.workshop_seats,  # distinct learners per month; 0 = none (can't schedule)
        "seats_used": len(seats_used(org, services.now())),
    }


@api_view(["GET"])
@staff_only
def orgs(request):
    """Organisations (search with ?q=), for the admin console's institution-workshop settings."""
    from apps.orgs.models import Organization

    qs = Organization.objects.order_by("name")
    if q := str(request.query_params.get("q") or "").strip()[:80]:
        qs = qs.filter(Q(name__icontains=q) | Q(slug__icontains=q) | Q(display_name__icontains=q))
    return Response([_org_out(o) for o in qs[:100]])


@api_view(["GET", "PATCH"])
@staff_only
def org_detail(request, pk):
    """PATCH {workshops: bool, workshop_seats: 0..100000}."""
    from apps.orgs.models import Organization

    org = get_object_or_404(Organization, pk=pk)
    if request.method == "PATCH":
        data = request.data if isinstance(request.data, dict) else {}
        with transaction.atomic():
            org = Organization.objects.select_for_update().get(pk=org.pk)
            fields = []
            if "workshops" in data:
                if not isinstance(data["workshops"], bool):
                    return Response({"code": "bad_workshops"}, status=status.HTTP_400_BAD_REQUEST)
                # On by default; an explicit False also keeps the org's learners out of workshops altogether
                # (orgs.extras.blocked), so "off" here is the whole switch, not just institution runs.
                org.features = {**(org.features or {}), "workshops": data["workshops"]}
                fields.append("features")
            if "workshop_seats" in data:
                n = _int(data["workshop_seats"], 0, 100_000)
                if n is None:
                    return Response({"code": "bad_workshop_seats"}, status=status.HTTP_400_BAD_REQUEST)
                org.workshop_seats = n
                fields.append("workshop_seats")
            if fields:
                org.save(update_fields=fields)
    return Response(_org_out(org))
