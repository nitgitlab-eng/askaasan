"""HR onboarding journeys.

Staff side (/api/journeys/orgs/<slug>/…): org owners/admins and org-wide managers design journeys (create, edit, duplicate,
AI draft) and assign them to any member; unit admins (unit-scoped managers) may only assign existing journeys to — and
follow the progress of — learners in their own units. Learner side (/api/journeys/me/…): own journeys only."""

import csv
import io
from datetime import date

from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.orgs.csvsafe import csv_safe
from apps.orgs.models import Group, Membership
from apps.orgs.perms import is_org_admin, is_unit_scoped, managed_unit_ids, membership, require

from .models import Journey, JourneyAssignment, JourneyItem, JourneyTick
from .services import MAX_DAYS, assignable_documents, clean_phases, done_items, due_date, status_of

MAX_JOURNEYS = 100
MAX_ITEMS = 400
AI_PER_DAY = 20
KINDS = {k.value for k in JourneyItem.Kind}


class Refused(Exception):
    def __init__(self, code: str, http=status.HTTP_400_BAD_REQUEST):
        self.code, self.http = code, http


# ── Permissions ──────────────────────────────────────────────────────


def editor(user, slug) -> Membership:
    """Designing journeys: org owners/admins and org-wide managers (perms.require refuses unit-scoped managers)."""
    return require(user, slug, "manager")


def staff(user, slug) -> tuple[Membership, set[int] | None]:
    """Assigning / following journeys. Returns (membership, allowed membership ids) — None means the whole org; a unit
    admin gets only the learners of their unit(s) and child units. Learners are refused."""
    m = membership(user, slug)
    if is_org_admin(m) or (m.role == "manager" and not is_unit_scoped(m)):
        return m, None
    if is_unit_scoped(m):
        units = managed_unit_ids(m)
        return m, set(
            Membership.objects.filter(
                org_id=m.org_id, role="learner", partner=False, groups__unit_id__in=units
            ).values_list("id", flat=True)
        )
    raise PermissionDenied("insufficient_role")


def _scoped(qs, allowed):
    return qs if allowed is None else qs.filter(membership_id__in=allowed)


# ── Output ───────────────────────────────────────────────────────────


def _name(user) -> str:
    p = getattr(user, "profile", None)
    return ((p.display_name if p else "") or user.email.split("@")[0])[:80]


def item_out(i: JourneyItem) -> dict:
    cur, sub, sc, od = i.curriculum, i.subsection, i.scenario, i.document
    return {
        "id": i.id,
        "day": i.day,
        "order": i.order,
        "kind": i.kind,
        "title": i.title,
        "notes": i.notes,
        "course": {"id": cur.id, "title": cur.title, "emoji": cur.cover_emoji} if cur else None,
        "lesson": {"id": sub.id, "title": sub.title} if sub else None,
        "scenario": {"id": sc.id, "title": sc.title, "emoji": sc.emoji} if sc else None,
        "document": {
            "id": od.id,
            "document_id": od.document_id,
            "title": od.title or (od.document.title if od.document_id else ""),
        }
        if od
        else None,
        "colleague_name": i.colleague_name,
        "colleague_role": i.colleague_role,
    }


ITEM_RELATED = ("curriculum", "subsection", "scenario", "document__document")


def _items(j):
    return list(j.items.select_related(*ITEM_RELATED))


def journey_out(j: Journey, *, full=False) -> dict:
    out = {
        "id": j.id,
        "name": j.name,
        "description": j.description,
        "length_days": j.length_days,
        "phases": j.phases,
        "items_n": j.items.count(),
        "assignees_n": j.assignments.count(),
        "updated_at": j.updated_at,
    }
    if full:
        out["items"] = [item_out(i) for i in _items(j)]
    return out


# ── Input ────────────────────────────────────────────────────────────


def _int(v, lo, hi, code):
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise Refused(code) from None
    if not lo <= n <= hi:
        raise Refused(code)
    return n


def _text(v, n) -> str:
    return str(v or "").strip()[:n]


def parse_item(d, me: Membership, length: int) -> dict:
    """Validated item fields. Courses: only assignable ones (courses.assignable_q); scenarios: library, own, or already
    shared with this org; documents: org documents learners may read."""
    from apps.learning.models import Subsection
    from apps.orgs.courses import assignable_courses, ensure_published
    from apps.orgs.teach import assignable_scenarios_q
    from apps.roleplay.models import Scenario

    if not isinstance(d, dict):
        raise Refused("bad_item")
    kind = str(d.get("kind") or "")
    if kind not in KINDS:
        raise Refused("bad_kind")
    out = {
        "kind": kind,
        "day": _int(d.get("day"), 1, length, "bad_day"),
        "order": _int(d.get("order", 0) or 0, 0, 100, "bad_order"),
        "title": _text(d.get("title"), 160),
        "notes": _text(d.get("notes"), 1000),
        "curriculum": None,
        "subsection": None,
        "scenario": None,
        "document": None,
        "colleague_name": "",
        "colleague_role": "",
    }
    if kind == "lesson":
        cur = (
            assignable_courses(me.org, me.user)
            .filter(pk=_int(d.get("curriculum_id"), 1, 2**62, "course_required"))
            .first()
        )
        if not cur:
            raise Refused("course_not_found", status.HTTP_404_NOT_FOUND)
        if code := ensure_published(
            cur, me.user
        ):  # only the caller's own course is published as a side effect
            raise Refused(code, status.HTTP_409_CONFLICT)
        if d.get("lesson_id"):
            sub = Subsection.objects.filter(
                pk=_int(d.get("lesson_id"), 1, 2**62, "bad_lesson"), section__curriculum=cur, archived=False
            ).first()
            if not sub:
                raise Refused("lesson_not_found", status.HTTP_404_NOT_FOUND)
            out["subsection"] = sub
        out["curriculum"] = cur
        out["title"] = out["title"] or (out["subsection"].title if out["subsection"] else cur.title)[:160]
    elif kind == "scenario":
        if (me.org.features or {}).get("roleplay", True) is False:
            raise Refused("feature_off", status.HTTP_409_CONFLICT)
        sc = (
            Scenario.objects.filter(
                assignable_scenarios_q(me), pk=_int(d.get("scenario_id"), 1, 2**62, "scenario_required")
            )
            .distinct()
            .first()
        )
        if not sc:
            raise Refused("scenario_not_found", status.HTTP_404_NOT_FOUND)
        out["scenario"], out["title"] = sc, out["title"] or sc.title[:160]
    elif kind == "document":
        od = (
            assignable_documents(me.org)
            .filter(pk=_int(d.get("document_id"), 1, 2**62, "document_required"))
            .select_related("document")
            .first()
        )
        if not od:
            raise Refused("document_not_found", status.HTTP_404_NOT_FOUND)
        out["document"], out["title"] = od, out["title"] or (od.title or od.document.title)[:160]
    elif kind == "shadow":
        out["colleague_name"], out["colleague_role"] = (
            _text(d.get("colleague_name"), 80),
            _text(d.get("colleague_role"), 80),
        )
        if not (out["colleague_name"] or out["colleague_role"]):
            raise Refused("colleague_required")
        out["title"] = out["title"] or f"Shadow {out['colleague_name'] or out['colleague_role']}"[:160]
    elif not (out["title"] or out["notes"]):
        raise Refused("note_required")
    return out


def grantable_course_ids(j: Journey, user, ids) -> set[int]:
    """Courses that are still assignable in this org (courses.assignable_q) for the assigning user or — while they are
    still org staff — the journey's author. Anything else is never granted (and never lifts a cohort window)."""
    from django.db.models import Q

    from apps.learning.models import Curriculum
    from apps.orgs.courses import assignable_q

    q = assignable_q(j.org, user)
    author = j.created_by
    if (
        author
        and author.pk != user.pk
        and Membership.objects.filter(org=j.org, user=author, role__in=["owner", "admin", "manager"]).exists()
    ):
        q = q | assignable_q(j.org, author)
    return set(Curriculum.objects.filter(Q(id__in=ids) & q).values_list("id", flat=True).distinct())


def item_payload(i: JourneyItem) -> dict:
    """An existing item as parse_item input (to re-validate it)."""
    return {
        "kind": i.kind,
        "day": i.day,
        "order": i.order,
        "title": i.title,
        "notes": i.notes,
        "curriculum_id": i.curriculum_id,
        "lesson_id": i.subsection_id,
        "scenario_id": i.scenario_id,
        "document_id": i.document_id,
        "colleague_name": i.colleague_name,
        "colleague_role": i.colleague_role,
    }


def _grant(j: Journey, user, items=None, members=None) -> list[dict]:
    """Learners on a journey get permanent access to its courses (like an assignment) — only courses that are currently
    assignable. Returns the skipped courses so the caller can warn the admin."""
    from apps.orgs.cohorts import grant_permanent

    curs = {
        i.curriculum
        for i in (items if items is not None else j.items.select_related("curriculum"))
        if i.curriculum_id
    }
    if not curs:
        return []
    ok = grantable_course_ids(j, user, [c.id for c in curs])
    for m in (
        members
        if members is not None
        else Membership.objects.filter(journeys__journey=j).select_related("user")
    ):
        for cur in curs:
            if cur.id in ok:
                grant_permanent(m.user, cur)
    return [{"id": c.id, "title": c.title} for c in curs if c.id not in ok]


def _refused(e: Refused, index: int | None = None) -> Response:
    body = {"code": e.code}
    if index is not None:
        body["index"] = index
    return Response(body, status=e.http)


def _header(d, j: Journey | None) -> dict:
    """name / description / length / phases from a create or update payload."""
    out = {}
    if j is None or "name" in d:
        out["name"] = _text(d.get("name"), 120)
        if not out["name"]:
            raise Refused("name_required")
    if "description" in d:
        out["description"] = _text(d.get("description"), 500)
    length = j.length_days if j else 30
    if d.get("length_days") is not None:
        length = out["length_days"] = _int(d.get("length_days"), 1, MAX_DAYS, "bad_length")
        if j and j.items.filter(day__gt=length).exists():
            raise Refused("items_beyond_length", status.HTTP_409_CONFLICT)
    if "phases" in d or (j and "length_days" in out):
        out["phases"] = clean_phases(d.get("phases", j.phases if j else []), length)
    return out


# ── Staff endpoints ──────────────────────────────────────────────────


@api_view(["GET", "POST"])
def journeys(request, slug):
    if request.method == "GET":
        me, _ = staff(request.user, slug)
        return Response(
            {
                "can_edit": me.role != "manager" or not is_unit_scoped(me),
                "journeys": [journey_out(j) for j in Journey.objects.filter(org=me.org)[:MAX_JOURNEYS]],
            }
        )
    me = editor(request.user, slug)
    if Journey.objects.filter(org=me.org).count() >= MAX_JOURNEYS:
        return Response({"code": "too_many_journeys"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    d = request.data if isinstance(request.data, dict) else {}
    try:
        head = _header(d, None)
        length = head.get("length_days", 30)
        head.setdefault("phases", [])
        raw = d.get("items") or []
        if not isinstance(raw, list) or len(raw) > MAX_ITEMS:
            raise Refused("bad_items")
    except Refused as e:
        return _refused(e)
    parsed = []
    for n, x in enumerate(raw):
        try:
            parsed.append(parse_item(x, me, length))
        except Refused as e:
            return _refused(e, n)
    with transaction.atomic():
        j = Journey.objects.create(org=me.org, created_by=request.user, **head)
        JourneyItem.objects.bulk_create([JourneyItem(journey=j, **p) for p in parsed])
    return Response(journey_out(j, full=True), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
def journey_detail(request, slug, pk):
    if request.method == "GET":
        me, _ = staff(request.user, slug)
    else:
        me = editor(request.user, slug)
    j = get_object_or_404(Journey, pk=pk, org=me.org)
    if request.method == "DELETE":
        j.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    if request.method == "PATCH":
        try:
            head = _header(request.data if isinstance(request.data, dict) else {}, j)
        except Refused as e:
            return _refused(e)
        for k, v in head.items():
            setattr(j, k, v)
        j.save()
    return Response(journey_out(j, full=True))


@api_view(["POST"])
def journey_duplicate(request, slug, pk):
    """Templates: copy a journey (phases + items, never its assignees)."""
    me = editor(request.user, slug)
    src = get_object_or_404(Journey, pk=pk, org=me.org)
    if Journey.objects.filter(org=me.org).count() >= MAX_JOURNEYS:
        return Response({"code": "too_many_journeys"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    name = _text(request.data.get("name"), 120) or f"Copy of {src.name}"[:120]
    parsed, dropped = [], []
    for i in src.items.select_related(
        *ITEM_RELATED
    ):  # re-check every item: a course/role-play/doc may no longer be allowed
        try:
            parsed.append(parse_item(item_payload(i), me, src.length_days))
        except Refused as e:
            dropped.append({"id": i.id, "day": i.day, "kind": i.kind, "title": i.title, "code": e.code})
    with transaction.atomic():
        j = Journey.objects.create(
            org=me.org,
            name=name,
            description=src.description,
            length_days=src.length_days,
            phases=src.phases,
            created_by=request.user,
        )
        JourneyItem.objects.bulk_create([JourneyItem(journey=j, **p) for p in parsed])
    return Response({**journey_out(j, full=True), "dropped": dropped}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def items(request, slug, pk):
    me = editor(request.user, slug)
    j = get_object_or_404(Journey, pk=pk, org=me.org)
    if j.items.count() >= MAX_ITEMS:
        return Response({"code": "too_many_items"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    try:
        p = parse_item(request.data, me, j.length_days)
    except Refused as e:
        return _refused(e)
    i = JourneyItem.objects.create(journey=j, **p)
    _grant(j, request.user, [i])
    Journey.objects.filter(pk=j.pk).update(updated_at=timezone.now())
    return Response(item_out(i), status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
def item_detail(request, slug, pk, iid):
    me = editor(request.user, slug)
    i = get_object_or_404(
        JourneyItem.objects.select_related(*ITEM_RELATED), pk=iid, journey_id=pk, journey__org=me.org
    )
    if request.method == "DELETE":
        i.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    base = item_payload(i)
    d = request.data if isinstance(request.data, dict) else {}
    try:
        p = parse_item({**base, **{k: v for k, v in d.items() if k in base}}, me, i.journey.length_days)
    except Refused as e:
        return _refused(e)
    if p["kind"] != i.kind:
        i.ticks.all().delete()  # a tick meant "done" for the old item
    for k, v in p.items():
        setattr(i, k, v)
    i.save()
    _grant(i.journey, request.user, [i])
    return Response(item_out(i))


@api_view(["GET"])
def options(request, slug):
    """What can go into a journey: assignable courses (with lessons), role-plays and readable documents."""
    from apps.learning.models import Subsection
    from apps.orgs.courses import assignable_courses
    from apps.orgs.teach import assignable_scenarios_q
    from apps.roleplay.api import _visible_scenarios
    from apps.roleplay.models import Scenario

    me = editor(request.user, slug)
    curs = list(assignable_courses(me.org, request.user).order_by("-updated_at")[:150])
    lessons: dict[int, list] = {}
    for s in (
        Subsection.objects.filter(section__curriculum__in=curs, archived=False, section__archived=False)
        .order_by("section__order", "order")
        .values("id", "title", "section__curriculum_id")
    ):
        lessons.setdefault(s["section__curriculum_id"], []).append({"id": s["id"], "title": s["title"]})
    _visible_scenarios(request.user)  # makes sure the built-in library exists
    roleplay_on = (me.org.features or {}).get("roleplay", True) is not False
    scs = (
        Scenario.objects.filter(assignable_scenarios_q(me)).distinct().order_by("source", "-created_at")[:120]
        if roleplay_on
        else []
    )
    return Response(
        {
            "courses": [
                {"id": c.id, "title": c.title, "emoji": c.cover_emoji, "lessons": lessons.get(c.id, [])[:60]}
                for c in curs
            ],
            "scenarios": [{"id": s.id, "title": s.title, "emoji": s.emoji} for s in scs],
            "documents": [
                {"id": od.id, "title": od.title or od.document.title}
                for od in assignable_documents(me.org).select_related("document")[:100]
            ],
        }
    )


@api_view(["GET"])
def people(request, slug):
    """Members and classes the caller may assign a journey to (unit admins: their units only)."""
    me, allowed = staff(request.user, slug)
    ms = (
        Membership.objects.filter(org=me.org, partner=False)
        .select_related("user__profile")
        .order_by("user__email")
    )
    groups = Group.objects.filter(org=me.org).exclude(name="Everyone")
    if allowed is not None:
        ms = ms.filter(id__in=allowed)
        groups = groups.filter(unit_id__in=managed_unit_ids(me))
    return Response(
        {
            "members": [
                {"id": m.id, "name": _name(m.user), "email": m.user.email, "role": m.role} for m in ms[:1000]
            ],
            "groups": [{"id": g.id, "name": g.name} for g in groups.order_by("name")[:300]],
        }
    )


def _parse_date(v) -> date:
    try:
        d = date.fromisoformat(str(v))
    except ValueError:
        raise Refused("bad_start_date") from None
    today = timezone.localdate()
    if abs((d - today).days) > MAX_DAYS:
        raise Refused("bad_start_date")
    return d


@api_view(["POST"])
def assign(request, slug, pk):
    from apps.game.services import notify

    me, allowed = staff(request.user, slug)
    j = get_object_or_404(Journey, pk=pk, org=me.org)
    d = request.data if isinstance(request.data, dict) else {}
    try:
        start = _parse_date(d.get("start_date") or timezone.localdate().isoformat())
        ids = d.get("membership_ids") or []
        if not isinstance(ids, list) or len(ids) > 500:
            raise Refused("bad_members")
        ids = {_int(x, 1, 2**62, "bad_members") for x in ids}
    except Refused as e:
        return _refused(e)
    group = None
    if d.get("group_id"):
        groups = Group.objects.filter(org=me.org)
        if allowed is not None:
            groups = groups.filter(unit_id__in=managed_unit_ids(me))
        group = get_object_or_404(groups, pk=d.get("group_id"))
    targets = Membership.objects.filter(org=me.org, partner=False, id__in=ids)
    if targets.count() != len(ids) or (allowed is not None and not ids <= allowed):
        raise Http404  # someone outside the caller's org / units: don't reveal who exists
    chosen = set(ids)
    if group:
        gm = group.members.filter(partner=False)
        if allowed is not None:
            gm = gm.filter(id__in=allowed)
        chosen |= set(gm.values_list("id", flat=True))
    if not chosen:
        return Response({"code": "no_members"}, status=status.HTTP_400_BAD_REQUEST)
    existing = set(
        JourneyAssignment.objects.filter(journey=j, membership_id__in=chosen).values_list(
            "membership_id", flat=True
        )
    )
    new = Membership.objects.filter(id__in=chosen - existing).select_related("user")
    with transaction.atomic():
        JourneyAssignment.objects.bulk_create(
            [
                JourneyAssignment(
                    journey=j, membership=m, start_date=start, group=group, assigned_by=request.user
                )
                for m in new
            ]
        )
        not_granted = _grant(j, request.user, members=new)
    for m in new:
        notify(
            m.user,
            "assignment",
            f"🧭 {j.name[:120]}",
            "Your onboarding plan is ready: one day at a time.",
            "/journey",
        )
    return Response(
        {"assigned": len(new), "skipped": len(existing), "not_granted": not_granted},
        status=status.HTTP_201_CREATED,
    )


@api_view(["PATCH", "DELETE"])
def assignee(request, slug, pk, aid):
    me, allowed = staff(request.user, slug)
    a = get_object_or_404(
        _scoped(JourneyAssignment.objects.filter(journey__org=me.org, journey_id=pk), allowed), pk=aid
    )
    if request.method == "DELETE":
        a.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    try:
        a.start_date = _parse_date(request.data.get("start_date"))
    except Refused as e:
        return _refused(e)
    a.save(update_fields=["start_date"])
    return Response({"id": a.id, "start_date": a.start_date})


def progress_rows(j: Journey, allowed) -> list[dict]:
    its = _items(j)
    qs = list(_scoped(j.assignments.select_related("membership__user__profile", "journey"), allowed)[:1000])
    done = done_items(qs, its)
    today = timezone.localdate()
    rows = []
    for a in qs:
        st = status_of(a, its, done[a.id], today)
        u = a.membership.user
        phase = j.phases[st["phase"]]["title"] if st["phase"] is not None else ""
        rows.append(
            {
                "assignment_id": a.id,
                "membership_id": a.membership_id,
                "user_id": u.id,
                "name": _name(u),
                "email": u.email,
                "start_date": a.start_date,
                "phase_title": phase,
                **st,
            }
        )
    return rows


@api_view(["GET"])
def progress(request, slug, pk):
    me, allowed = staff(request.user, slug)
    j = get_object_or_404(Journey, pk=pk, org=me.org)
    return Response(
        {"journey": journey_out(j), "today": timezone.localdate(), "rows": progress_rows(j, allowed)}
    )


def safe_cell(v) -> str:
    """CSV cells never start like a formula (Excel/Sheets would run them), even after leading spaces or a newline."""
    return csv_safe("" if v is None else str(v))


@api_view(["GET"])
def progress_csv(request, slug, pk):
    me, allowed = staff(request.user, slug)
    j = get_object_or_404(Journey, pk=pk, org=me.org)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "Name",
            "Email",
            "Start date",
            "Day",
            "Length (days)",
            "Items done",
            "Items total",
            "Overdue",
            "Current phase",
            "Stuck",
        ]
    )
    for r in progress_rows(j, allowed):
        w.writerow(
            [
                safe_cell(x)
                for x in (
                    r["name"],
                    r["email"],
                    r["start_date"].isoformat(),
                    r["day"],
                    r["length_days"],
                    r["done"],
                    r["total"],
                    r["overdue"],
                    r["phase_title"],
                    "yes" if r["stuck"] else "no",
                )
            ]
        )
    resp = HttpResponse("﻿" + buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="journey-{j.id}-progress.csv"'
    return resp


@api_view(["POST"])
def ai_draft(request, slug):
    """ "Draft a N-day onboarding plan for a <role> at <company>": a proposal (not saved) mapped to existing courses,
    role-plays and documents. The admin accepts/rejects items, then creates the journey with the normal POST."""
    from apps.orgs.courses import assignable_courses
    from apps.orgs.teach import assignable_scenarios_q
    from apps.providers.services import BudgetExceeded, charge
    from apps.roleplay.models import Scenario
    from llm.base import LLMError
    from llm.prompts.journeys import JOURNEY_DRAFT_SYSTEM, JourneyDraft
    from llm.structured import complete_json_sync

    me = editor(request.user, slug)
    d = request.data if isinstance(request.data, dict) else {}
    role = _text(d.get("role"), 120)
    company = _text(d.get("company"), 600) or me.org.description[:600]
    if len(role) < 2:
        return Response({"code": "role_required"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        days = _int(d.get("days") or 30, 1, 90, "bad_length")
    except Refused as e:
        return _refused(e)
    curs = {c.id: c for c in assignable_courses(me.org, request.user).order_by("-updated_at")[:40]}
    roleplay_on = (me.org.features or {}).get("roleplay", True) is not False
    scs = (
        {s.id: s for s in Scenario.objects.filter(assignable_scenarios_q(me)).distinct()[:40]}
        if roleplay_on
        else {}
    )
    docs = {od.id: od for od in assignable_documents(me.org).select_related("document")[:30]}
    try:
        charge(request.user, "journey_ai", 1, AI_PER_DAY)
    except BudgetExceeded:
        return Response({"code": "ai_budget_exceeded"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    from apps.paths.api import _lang

    listing = "\n".join(
        [
            f"Role: {role}",
            f"Company: {company or me.org.display_name or me.org.name}",
            "COURSES:",
            *[f"- {c.id}: {c.title[:100]}" for c in curs.values()],
            "SCENARIOS:",
            *[f"- {s.id}: {s.title[:100]}" for s in scs.values()],
            "DOCUMENTS:",
            *[f"- {o.id}: {(o.title or o.document.title)[:100]}" for o in docs.values()],
        ]
    )
    try:
        out = complete_json_sync(
            "author",
            JOURNEY_DRAFT_SYSTEM.format(days=days, lang_rule=_lang(request.user)),
            listing,
            JourneyDraft,
            max_tokens=6000,
        )
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    proposals = []
    for x in out.items[:MAX_ITEMS]:
        if not 1 <= x.day <= days or x.kind not in KINDS:
            continue
        p = {
            "key": len(proposals),
            "day": x.day,
            "kind": x.kind,
            "title": x.title[:160],
            "notes": x.notes[:1000],
            "curriculum_id": None,
            "scenario_id": None,
            "document_id": None,
            "colleague_role": "",
            "ref_title": "",
        }
        if x.kind == "lesson" and x.ref_id in curs:
            p["curriculum_id"], p["ref_title"] = x.ref_id, curs[x.ref_id].title
        elif x.kind == "scenario" and x.ref_id in scs:
            p["scenario_id"], p["ref_title"] = x.ref_id, scs[x.ref_id].title
        elif x.kind == "document" and x.ref_id in docs:
            p["document_id"], p["ref_title"] = x.ref_id, docs[x.ref_id].title or docs[x.ref_id].document.title
        elif x.kind == "shadow":
            p["colleague_role"] = x.colleague_role[:80] or "a teammate"
        else:
            p["kind"] = (
                "note"  # an id that isn't in the lists: keep the idea as an HR note instead of guessing
            )
        if p["kind"] == "note" and not (p["title"] or p["notes"]):
            continue
        proposals.append(p)
    return Response(
        {
            "name": out.name[:120],
            "description": out.description[:500],
            "length_days": days,
            "phases": clean_phases([ph.model_dump() for ph in out.phases], days),
            "items": proposals,
        }
    )


# ── Learner endpoints ────────────────────────────────────────────────


def _mine(user):
    return JourneyAssignment.objects.filter(membership__user=user, membership__partner=False).select_related(
        "journey", "journey__org", "membership"
    )


def _learner_items(a, its, done, day):
    rows = []
    readable = set(
        assignable_documents(a.journey.org)
        .filter(id__in=[i.document_id for i in its if i.document_id])
        .values_list("id", flat=True)
    )
    for i in its:
        o = item_out(i)
        o["unavailable"] = False
        if (
            i.kind == "document" and i.document_id not in readable
        ):  # switched to staff-only / gone: reveal nothing about it
            o.update(title="", notes="", document=None, link="", unavailable=True)
        elif i.kind == "lesson" and i.curriculum_id:
            o["link"] = (
                f"/learn/{i.curriculum_id}/lesson/{i.subsection_id}"
                if i.subsection_id
                else f"/learn/{i.curriculum_id}"
            )
        elif i.kind == "document" and i.document.document_id:
            o["link"] = f"/documents/{i.document.document_id}"
        elif not o["unavailable"]:
            o["link"] = ""
        o.update(
            due_date=due_date(a.start_date, i.day),
            done=i.id in done,
            overdue=i.id not in done and i.day < day,
            auto=i.kind == "lesson",
        )
        rows.append(o)
    return rows


def _assignment_out(a, *, full=False, today=None):
    j = a.journey
    its = _items(j)
    done = done_items([a], its)[a.id]
    st = status_of(a, its, done, today)
    out = {
        "id": a.id,
        "journey": {
            "id": j.id,
            "name": j.name,
            "description": j.description,
            "length_days": j.length_days,
            "phases": j.phases,
        },
        "org": j.org.display_name or j.org.name,
        "start_date": a.start_date,
        "status": st,
    }
    rows = _learner_items(a, its, done, st["day"])
    if full:
        out["items"] = rows
    else:
        out["today"] = [r for r in rows if r["day"] == st["day"]][:10]
    return out


@api_view(["GET"])
def my_journeys(request):
    today = timezone.localdate()
    return Response([_assignment_out(a, today=today) for a in _mine(request.user)[:10]])


@api_view(["GET"])
def my_journey(request, aid):
    return Response(_assignment_out(get_object_or_404(_mine(request.user), pk=aid), full=True))


@api_view(["POST"])
def my_tick(request, aid, iid):
    """Tick (or un-tick) a non-lesson item. Lesson items complete through normal lesson completion."""
    a = get_object_or_404(_mine(request.user), pk=aid)
    i = get_object_or_404(JourneyItem, pk=iid, journey_id=a.journey_id)
    if i.kind == JourneyItem.Kind.LESSON:
        return Response({"code": "auto_item"}, status=status.HTTP_400_BAD_REQUEST)
    if request.data.get("done", True) is False:
        JourneyTick.objects.filter(assignment=a, item=i).delete()
    else:
        JourneyTick.objects.get_or_create(assignment=a, item=i)
    return Response(_assignment_out(a, full=True))
