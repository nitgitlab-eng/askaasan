"""Milestone 9 — partner programmes / cohorts: an org grants (or sells) a set of courses to a cohort for an access window.

Members get an Enrollment whose access_from/access_until mirror the window; learning.access.viewable_q refuses access
outside it, so the course disappears before the start and after the end while the learner's progress is kept."""

from datetime import timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.learning.models import Enrollment

from .models import Cohort, Group, Invitation, Membership
from .perms import require

MAX_COHORTS = 100


# ── Access helpers (also used by assignments / invitations) ──────────


def grant_permanent(user, cur):
    """Assignments and other permanent grants: enrol without a window (and lift a cohort window if there was one)."""
    e, created = Enrollment.objects.get_or_create(user=user, curriculum=cur)
    if not created and (e.access_from or e.access_until):
        e.access_from = e.access_until = None
        e.save(update_fields=["access_from", "access_until"])
    return e


def sync_access(user, cur):
    """Recompute a learner's cohort window for one course: union of every cohort window they hold for it."""
    if cur.owner_id == user.id:
        return
    e = Enrollment.objects.filter(user=user, curriculum=cur).first()
    if e and e.access_from is None and e.access_until is None:
        return  # permanent access (assignment, share link) is never narrowed by a cohort
    wins = list(Cohort.objects.filter(members__user=user, courses=cur).values_list("starts_at", "ends_at"))
    now = timezone.now()
    if not wins:
        if e:  # removed from the cohort (or course dropped): access ends now, progress stays
            e.access_until = min(e.access_until or now, now)
            e.save(update_fields=["access_until"])
        return
    start, end = min(w[0] for w in wins), max(w[1] for w in wins)
    if e:
        e.access_from, e.access_until = start, end
        e.save(update_fields=["access_from", "access_until"])
    else:
        Enrollment.objects.create(user=user, curriculum=cur, access_from=start, access_until=end)


def sync_cohort(c, users=None, courses=None):
    users = users if users is not None else [m.user for m in c.members.select_related("user")]
    courses = courses if courses is not None else list(c.courses.all())
    for u in users:
        for cur in courses:
            sync_access(u, cur)


def join_cohort(m: Membership, c: Cohort):
    c.members.add(m)
    sync_cohort(c, users=[m.user])


# ── Admin endpoints ──────────────────────────────────────────────────


def _state(c, now=None) -> str:
    now = now or timezone.now()
    return "upcoming" if now < c.starts_at else "ended" if now >= c.ends_at else "active"


def cohort_out(c) -> dict:
    from .units import _first

    return {
        "id": c.id,
        "name": c.name,
        "partner": c.partner,
        "description": c.description,
        "starts_at": c.starts_at,
        "ends_at": c.ends_at,
        "state": _state(c),
        "courses": [{"id": x.id, "title": x.title, "emoji": x.cover_emoji} for x in c.courses.all()],
        "members": [
            {"id": m.id, "name": _first(m.user), "email": m.user.email}
            for m in c.members.select_related("user__profile")[:500]
        ],
        "pending": list(
            Invitation.objects.filter(cohort=c, accepted_at__isnull=True).values_list("email", flat=True)[
                :200
            ]
        ),
    }


class CohortIn(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    partner = serializers.CharField(max_length=120, required=False, allow_blank=True)
    description = serializers.CharField(max_length=500, required=False, allow_blank=True)
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    course_ids = serializers.ListField(child=serializers.IntegerField(), max_length=50, required=False)

    def validate(self, d):
        s, e = (
            d.get("starts_at", getattr(self.instance, "starts_at", None)),
            d.get("ends_at", getattr(self.instance, "ends_at", None)),
        )
        if s and e and e <= s:
            raise serializers.ValidationError({"ends_at": "ends_before_start"})
        if s and e and e - s > timedelta(days=5 * 366):
            raise serializers.ValidationError({"ends_at": "window_too_long"})
        return d


def _courses(org, ids, user):
    """Courses for a cohort: only ones the caller may assign (never another member's private draft). The caller's own
    unpublished course is published without a public link (cohort-only, window-limited access)."""
    from .courses import assignable_courses, ensure_published

    ids = set(ids)
    found = list(assignable_courses(org, user).filter(id__in=ids))
    if len(found) != len(ids):
        raise serializers.ValidationError({"course_ids": "unknown_course"})
    for cur in found:
        if code := ensure_published(cur, user, share_link=False):
            raise serializers.ValidationError({"course_ids": code})
    return found


@api_view(["GET", "POST"])
def cohorts(request, slug):
    me = require(request.user, slug, "admin")
    if request.method == "GET":
        return Response([cohort_out(c) for c in me.org.cohorts.prefetch_related("courses")[:MAX_COHORTS]])
    if me.org.cohorts.count() >= MAX_COHORTS:
        return Response({"code": "too_many_cohorts"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    ser = CohortIn(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    with transaction.atomic():
        courses = _courses(me.org, d.get("course_ids") or [], request.user)
        c = Cohort.objects.create(
            org=me.org,
            name=d["name"].strip(),
            partner=d.get("partner", "").strip(),
            description=d.get("description", "").strip(),
            starts_at=d["starts_at"],
            ends_at=d["ends_at"],
            created_by=request.user,
        )
        c.courses.set(courses)
    return Response(cohort_out(c), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
def cohort_detail(request, slug, pk):
    me = require(request.user, slug, "admin")
    c = get_object_or_404(Cohort, pk=pk, org=me.org)
    if request.method == "DELETE":
        users, courses = [m.user for m in c.members.select_related("user")], list(c.courses.all())
        with transaction.atomic():
            c.delete()
            sync_cohort(c, users, courses)  # windows shrink / end; progress stays
        return Response(status=status.HTTP_204_NO_CONTENT)
    if request.method == "PATCH":
        ser = CohortIn(c, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        with transaction.atomic():
            before = list(c.courses.all())
            for k in ("name", "partner", "description", "starts_at", "ends_at"):
                if k in d:
                    setattr(c, k, d[k].strip() if isinstance(d[k], str) else d[k])
            c.save()
            if "course_ids" in d:
                c.courses.set(_courses(me.org, d["course_ids"], request.user))
            sync_cohort(c, courses=list({x.id: x for x in [*before, *c.courses.all()]}.values()))
    return Response(cohort_out(c))


@api_view(["POST"])
def cohort_members(request, slug, pk):
    """Add members from groups and/or by email (existing members at once; others get an invitation into the cohort)."""
    from apps.legal.mail import mail_ready

    from .api import email_invite, invite_mail_out, invite_refusal

    me = require(request.user, slug, "admin")
    c = get_object_or_404(Cohort, pk=pk, org=me.org)
    from .parse import int_list

    gids = int_list(request.data.get("group_ids"), 50)
    try:
        emails = sorted(
            {
                serializers.EmailField().run_validation(str(e).strip().lower())
                for e in (request.data.get("emails") or [])[:200]
            }
        )
    except serializers.ValidationError:
        return Response({"code": "bad_email"}, status=status.HTTP_400_BAD_REQUEST)
    if not gids and not emails:
        return Response({"code": "nobody"}, status=status.HTTP_400_BAD_REQUEST)
    groups = list(Group.objects.filter(org=me.org, id__in=gids))
    if len(groups) != len(set(gids)):
        return Response({"code": "unknown_group"}, status=status.HTTP_400_BAD_REQUEST)
    ms = {m.id: m for m in Membership.objects.filter(org=me.org, groups__in=groups).select_related("user")}
    ms.update(
        {
            m.id: m
            for m in Membership.objects.filter(org=me.org, user__email__in=emails).select_related("user")
        }
    )
    known = {m.user.email.lower() for m in ms.values()}
    to_invite = [
        e
        for e in emails
        if e not in known
        and not Invitation.objects.filter(org=me.org, cohort=c, email=e, accepted_at__isnull=True).exists()
    ]
    if refused := invite_refusal(request.user, me.org, len(to_invite)):
        return refused
    unsent, ready = [], mail_ready()
    with transaction.atomic():
        c.members.add(*ms.values())
        sync_cohort(c, users=[m.user for m in ms.values()])
        for e in to_invite:
            inv = Invitation.objects.create(
                org=me.org, email=e, role="learner", cohort=c, invited_by=request.user
            )
            if miss := email_invite(
                inv, f"You're invited to learn on Aasan with {me.org.display_name or me.org.name}.", ready
            ):
                unsent.append(miss)
    return Response(
        {**cohort_out(c), "added": len(ms), "invited": len(to_invite), **invite_mail_out(unsent)},
        status=status.HTTP_201_CREATED,
    )


@api_view(["DELETE"])
def cohort_member(request, slug, pk, mid):
    me = require(request.user, slug, "admin")
    c = get_object_or_404(Cohort, pk=pk, org=me.org)
    m = get_object_or_404(c.members.select_related("user"), pk=mid)
    with transaction.atomic():
        c.members.remove(m)
        sync_cohort(c, users=[m.user])
    return Response(status=status.HTTP_204_NO_CONTENT)


# ── Learner side ─────────────────────────────────────────────────────


@api_view(["GET"])
def my_cohorts(request):
    """The learner's cohort courses with their access window (ended ones stay listed for 60 days: progress is kept)."""
    now = timezone.now()
    qs = (
        Cohort.objects.filter(members__user=request.user, ends_at__gte=now - timedelta(days=60))
        .select_related("org")
        .prefetch_related("courses")
        .distinct()
        .order_by("ends_at")
    )
    return Response(
        [
            {
                "id": c.id,
                "name": c.name,
                "partner": c.partner,
                "org": c.org.display_name or c.org.name,
                "state": _state(c, now),
                "starts_at": c.starts_at,
                "ends_at": c.ends_at,
                "courses": [{"id": x.id, "title": x.title, "emoji": x.cover_emoji} for x in c.courses.all()],
            }
            for c in qs[:20]
        ]
    )
