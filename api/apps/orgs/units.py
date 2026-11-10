"""Milestone 9 — sub-schools / departments ("units") with their own target roles, module coverage and unit-scoped admins.

Org owners/admins manage every unit. A unit admin (a manager with Membership.unit_scoped and UnitAdmin rows) manages only their unit(s) and child
units: its groups, learners and assignments. Every endpoint here goes through `perms.unit_scope`."""

from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from .courses import assignable_courses, ensure_published
from .models import Assignment, Group, Invitation, Membership, SubUnit, UnitAdmin
from .perms import is_org_admin, make_unit_admin, managed_unit_ids, unit_scope

MAX_UNITS = 50
ADMIN_ONLY_FIELDS = ("name", "parent_id", "course_ids", "group_ids")


def _first(user):
    return (user.profile.display_name or user.email.split("@")[0]).split(" ")[0]


def descendants(unit) -> set[int]:
    rows = list(SubUnit.objects.filter(org_id=unit.org_id).values_list("id", "parent_id"))
    out, stack = {unit.id}, [unit.id]
    while stack:
        cur = stack.pop()
        for i, p in rows:
            if p == cur and i not in out:
                out.add(i)
                stack.append(i)
    return out


def unit_groups(unit):
    return Group.objects.filter(unit_id__in=descendants(unit))


def unit_learners(unit):
    return Membership.objects.filter(groups__in=unit_groups(unit), role="learner").distinct()


def unit_course_choices(u, user):
    """Module coverage (set by an org admin) limits what a unit admin may assign; empty coverage = what they may assign."""
    return u.courses.all() if u.courses.exists() else assignable_courses(u.org, user)


def careers_by_slug(slugs):
    from apps.paths.models import CareerPath

    rows = {c.slug: c for c in CareerPath.objects.filter(slug__in=slugs)}
    return [{"slug": s, "title": rows[s].title, "emoji": rows[s].emoji} for s in slugs if s in rows]


def valid_roles(slugs, org) -> list[str]:
    """Only published (or this org's own) career roles; unknown slugs are a 400 so typos don't vanish silently."""
    from apps.paths.models import CareerPath

    slugs = list(dict.fromkeys(str(s)[:80] for s in slugs))[:12]
    ok = set(
        CareerPath.objects.filter(slug__in=slugs)
        .filter(Q(published=True) | Q(org=org))
        .values_list("slug", flat=True)
    )
    if set(slugs) - ok:
        raise serializers.ValidationError({"target_roles": "unknown_role"})
    return slugs


def _course(c):
    return {"id": c.id, "title": c.title, "emoji": c.cover_emoji}


def unit_out(u, *, full=False) -> dict:
    out = {
        "id": u.id,
        "name": u.name,
        "description": u.description,
        "parent_id": u.parent_id,
        "target_roles": careers_by_slug(u.target_roles or []),
        "courses": [_course(c) for c in u.courses.all()],
        "groups": [
            {"id": g.id, "name": g.name, "join_code": g.join_code, "members": g.n}
            for g in u.groups.annotate(n=Count("members")).order_by("created_at")
        ],
        "admins": [
            {"id": a.membership_id, "name": _first(a.membership.user), "email": a.membership.user.email}
            for a in u.admins.select_related("membership__user__profile")
        ],
        "learners": unit_learners(u).count(),
    }
    if full:
        out["pending_admins"] = list(
            Invitation.objects.filter(unit=u, accepted_at__isnull=True).values_list("email", flat=True)[:50]
        )
    return out


class UnitIn(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)
    parent_id = serializers.IntegerField(required=False, allow_null=True)
    target_roles = serializers.ListField(
        child=serializers.CharField(max_length=80), max_length=12, required=False
    )
    course_ids = serializers.ListField(child=serializers.IntegerField(), max_length=100, required=False)
    group_ids = serializers.ListField(child=serializers.IntegerField(), max_length=200, required=False)


def _apply(u, d, org, user):
    if "parent_id" in d:
        parent = get_object_or_404(SubUnit, pk=d["parent_id"], org=org) if d["parent_id"] else None
        if parent and u.pk and parent.id in descendants(u):
            raise serializers.ValidationError({"parent_id": "cycle"})
        u.parent = parent
    for k in ("name", "description"):
        if k in d:
            setattr(u, k, d[k].strip())
    if "target_roles" in d:
        u.target_roles = valid_roles(d["target_roles"], org)
    u.save()
    if "course_ids" in d:
        ids = set(d["course_ids"])
        found = list(assignable_courses(org, user).filter(id__in=ids))  # never someone else's private draft
        if len(found) != len(ids):
            raise serializers.ValidationError({"course_ids": "unknown_course"})
        u.courses.set(found)
    if "group_ids" in d:
        groups = list(Group.objects.filter(org=org, id__in=set(d["group_ids"])).exclude(name="Everyone"))
        Group.objects.filter(unit=u).exclude(id__in=[g.id for g in groups]).update(unit=None)
        Group.objects.filter(id__in=[g.id for g in groups]).update(unit=u)


@api_view(["GET", "POST"])
def units(request, slug):
    if request.method == "POST":
        me, _ = unit_scope(request.user, slug, admin_only=True)
        if me.org.units.count() >= MAX_UNITS:
            return Response({"code": "too_many_units"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        ser = UnitIn(data=request.data)
        ser.is_valid(raise_exception=True)
        with transaction.atomic():
            u = SubUnit(org=me.org)
            _apply(u, ser.validated_data, me.org, request.user)
        return Response(unit_out(u, full=True), status=status.HTTP_201_CREATED)
    me, _ = unit_scope(request.user, slug)
    ids = managed_unit_ids(me)
    qs = SubUnit.objects.filter(id__in=ids).prefetch_related("courses")
    return Response({"scoped": not is_org_admin(me), "units": [unit_out(u) for u in qs]})


@api_view(["GET", "PATCH", "DELETE"])
def unit_detail(request, slug, pk):
    if request.method == "DELETE":
        _, u = unit_scope(request.user, slug, pk, admin_only=True)
        u.delete()  # its groups stay (unit=None); unit admin rows and pending unit invitations go with it
        return Response(status=status.HTTP_204_NO_CONTENT)
    me, u = unit_scope(request.user, slug, pk)
    if request.method == "PATCH":
        if not is_org_admin(me) and any(k in request.data for k in ADMIN_ONLY_FIELDS):
            raise PermissionDenied("org_admin_only")  # unit admins may edit description + target roles only
        ser = UnitIn(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        with transaction.atomic():
            _apply(u, ser.validated_data, me.org, request.user)
    out = unit_out(u, full=True)
    courses = (
        assignable_courses(me.org, request.user) if is_org_admin(me) else unit_course_choices(u, request.user)
    )
    out["course_options"] = [_course(c) for c in courses.order_by("-updated_at")[:200]]
    return Response(out)


@api_view(["POST"])
def unit_groups_create(request, slug, pk):
    """Unit admins add classes/teams to their own unit."""
    me, u = unit_scope(request.user, slug, pk)
    name = str(request.data.get("name") or "").strip()[:80]
    if not name or name == "Everyone":
        return Response({"code": "name_required"}, status=status.HTTP_400_BAD_REQUEST)
    Group.objects.create(org=me.org, name=name, unit=u)
    return Response(unit_out(u, full=True), status=status.HTTP_201_CREATED)


@api_view(["GET"])
def unit_learner_list(request, slug, pk):
    me, u = unit_scope(request.user, slug, pk)
    defs = me.org.member_fields or []
    gids = set(unit_groups(u).values_list("id", flat=True))
    rows = unit_learners(u).select_related("user__profile").prefetch_related("groups")[:1000]
    return Response(
        {
            "fields": defs,
            "learners": [
                {
                    "id": m.id,
                    "user_id": m.user_id,
                    "name": _first(m.user),
                    "email": m.user.email,
                    "fields": m.fields or {},
                    "groups": [g.id for g in m.groups.all() if g.id in gids],
                }
                for m in rows
            ],
        }
    )


class UnitAssignIn(serializers.Serializer):
    curriculum_id = serializers.IntegerField()
    group_id = serializers.IntegerField()
    due_at = serializers.DateTimeField(required=False, allow_null=True)
    note = serializers.CharField(max_length=300, required=False, allow_blank=True)


@api_view(["GET", "POST"])
def unit_assignments(request, slug, pk):
    from apps.game.services import notify

    from .api import _assignment_out, _assignments_out
    from .cohorts import grant_permanent

    me, u = unit_scope(request.user, slug, pk)
    groups = unit_groups(u)
    if request.method == "GET":
        qs = Assignment.objects.filter(org=me.org, group__in=groups).select_related(
            "curriculum", "scenario", "group", "survey"
        )[:50]
        return Response(_assignments_out(me.org, qs))
    ser = UnitAssignIn(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    group = get_object_or_404(groups, pk=d["group_id"])  # only this unit's classes
    cur = get_object_or_404(unit_course_choices(u, request.user), pk=d["curriculum_id"])
    if code := ensure_published(
        cur, request.user
    ):  # only the caller's own course is published as a side effect
        return Response({"code": code}, status=status.HTTP_409_CONFLICT)
    a = Assignment.objects.create(
        org=me.org,
        group=group,
        curriculum=cur,
        due_at=d.get("due_at"),
        note=d.get("note", ""),
        created_by=request.user,
    )
    for m in Membership.objects.filter(groups=group, role="learner").select_related("user"):
        grant_permanent(m.user, cur)
        notify(
            m.user,
            "assignment",
            f"📚 {cur.title[:120]}",
            (d.get("note") or "New course assigned")[:300],
            f"/learn/{cur.id}",
        )
    return Response(_assignment_out(a, with_rows=True), status=status.HTTP_201_CREATED)


@api_view(["DELETE"])
def unit_assignment_detail(request, slug, pk, aid):
    me, u = unit_scope(request.user, slug, pk)
    get_object_or_404(
        Assignment, pk=aid, org=me.org, group__in=unit_groups(u)
    ).delete()  # enrollments + progress stay
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
def unit_admins(request, slug, pk):
    """Org admins make someone a unit admin: an existing member at once, anyone else by email invitation."""
    from apps.legal.mail import mail_ready

    from .api import email_invite, invite_mail_out, invite_refusal

    me, u = unit_scope(request.user, slug, pk, admin_only=True)
    email = serializers.EmailField().run_validation(str(request.data.get("email") or "").strip().lower())
    m = Membership.objects.filter(org=me.org, user__email__iexact=email).first()
    if m:
        if is_org_admin(m):
            return Response(
                {"code": "already_org_admin"}, status=status.HTTP_400_BAD_REQUEST
            )  # they already manage everything
        with transaction.atomic():
            make_unit_admin(m, u)  # scoped explicitly; demoted back when their last unit goes
        return Response(unit_out(u, full=True), status=status.HTTP_201_CREATED)
    if Invitation.objects.filter(org=me.org, unit=u, email=email, accepted_at__isnull=True).exists():
        return Response(unit_out(u, full=True))
    if refused := invite_refusal(request.user, me.org, 1):
        return refused
    inv = Invitation.objects.create(org=me.org, email=email, role="manager", unit=u, invited_by=request.user)
    miss = email_invite(
        inv,
        f"You're invited to help run a team on Aasan with {me.org.display_name or me.org.name}.",
        mail_ready(),
    )
    return Response(
        {**unit_out(u, full=True), **invite_mail_out([miss] if miss else [])}, status=status.HTTP_201_CREATED
    )


@api_view(["DELETE"])
def unit_admin_detail(request, slug, pk, mid):
    _, u = unit_scope(request.user, slug, pk, admin_only=True)
    get_object_or_404(UnitAdmin, unit=u, membership_id=mid).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
def course_options(request, slug):
    """Courses an org admin can put in a unit's coverage or a cohort."""
    me, _ = unit_scope(request.user, slug, admin_only=True)
    return Response(
        [_course(c) for c in assignable_courses(me.org, request.user).order_by("-updated_at")[:200]]
    )
