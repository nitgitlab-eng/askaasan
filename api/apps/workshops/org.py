"""Institution workshops (/api/orgs/<slug>/workshops/): an org's batch runs for selected classes and cohorts.

Who: the `workshops` feature is on for every org unless the platform admin switches it off, and only the platform
admin sets the monthly `workshop_seats` (0 until set, so nothing can be scheduled before then). Org owners and
admins schedule, edit and cancel runs; managers (teachers) see runs, the live monitor, drill-downs and reports
for the learners in their own classes only (teach.scope_groups). Org runs are free to learners: everyone in the
selected classes / cohorts is enrolled automatically and notified, and only they can see or join the run."""

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import public, services
from .models import Workshop, WorkshopEnrollment, WorkshopEvent, WorkshopRun, WorkshopSession, WorkshopTurn

Status = WorkshopRun.Status
ORG = WorkshopRun.Audience.ORG
MAX_IDS = 200
RUN_FIELDS = ("workshop_slug", "starts_at", "proctoring", "late_join_minutes", "lobby_opens_minutes")
NOTICE = "Your institution can see your progress, answers, scores and help summaries during this workshop"
NOTICE_ATTENTION = ", plus your attention (tab switches, window focus and idle time)"


def institution_notice(run) -> str | None:
    """The pre-session notice for org runs (None for public / test runs)."""
    if run.audience != ORG:
        return None
    return NOTICE + (NOTICE_ATTENTION if run.effective_proctoring != "off" else "") + "."


def institution_sees(run) -> list[str]:
    if run.audience != ORG:
        return []
    out = ["progress", "answers", "scores", "help_summaries"]
    return out + ["attention"] if run.effective_proctoring != "off" else out


# ── Audience and scope ───────────────────────────────────────────────


def in_audience_q(user) -> Q:
    """Org runs whose selected classes or cohorts hold `user` as a learner right now."""
    G, C = WorkshopRun.groups.through, WorkshopRun.cohorts.through
    return Q(
        id__in=G.objects.filter(group__members__user=user, group__members__role="learner").values(
            "workshoprun_id"
        )
    ) | Q(
        id__in=C.objects.filter(cohort__members__user=user, cohort__members__role="learner").values(
            "workshoprun_id"
        )
    )


def in_audience(run, user) -> bool:
    return WorkshopRun.objects.filter(pk=run.pk).filter(in_audience_q(user)).exists()


def audience_user_ids(org, group_ids, cohort_ids) -> set[int]:
    from apps.orgs.models import Membership

    return set(
        Membership.objects.filter(org=org, role="learner")
        .filter(Q(groups__id__in=group_ids) | Q(cohorts__id__in=cohort_ids))
        .values_list("user_id", flat=True)
        .distinct()
    )


def scope_user_ids(me) -> set[int] | None:
    """Learners this staff member may see: None = everyone (owners/admins, or an org without classes)."""
    from apps.orgs.models import Membership
    from apps.orgs.teach import scope_groups

    g = scope_groups(me)
    if g is None:
        return None
    return set(
        Membership.objects.filter(org=me.org, groups__id__in=g).values_list("user_id", flat=True).distinct()
    )


def enrolled_ids(run, scope: set[int] | None) -> list[int]:
    ids = WorkshopEnrollment.objects.filter(run=run).values_list("user_id", flat=True)
    return [u for u in ids if scope is None or u in scope]


class FeatureOff(Exception):
    pass


def staff(user, slug, role: str):
    """→ the Membership (role checked by perms.require: 404 to non-members, 403 below `role`), feature on."""
    from apps.orgs.extras import feature_on
    from apps.orgs.perms import require

    me = require(user, slug, role)
    if not feature_on(me.org, "workshops"):
        raise FeatureOff
    return me


def _off():
    from apps.orgs.extras import feature_off_response

    return feature_off_response("workshops")


def _org_runs(org):
    return WorkshopRun.objects.filter(org=org, audience=ORG).select_related("workshop")


def visible_run(me, pk) -> WorkshopRun:
    """An org run of this org that this staff member can see: admins all, teachers runs with a learner of theirs."""
    run = get_object_or_404(_org_runs(me.org), pk=pk)
    scope = scope_user_ids(me)
    if scope is not None and not set(enrolled_ids(run, None)) & scope:
        from django.http import Http404

        raise Http404
    return run


# ── Quota ────────────────────────────────────────────────────────────


def _month(at):
    local = timezone.localtime(at)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )
    return start, end


def seats_used(org, at, exclude_run=None) -> set[int]:
    """Distinct learners enrolled in this org's (not cancelled) runs starting in `at`'s calendar month."""
    start, end = _month(at)
    qs = WorkshopEnrollment.objects.filter(
        run__org=org, run__audience=ORG, run__starts_at__gte=start, run__starts_at__lt=end
    ).exclude(run__status=Status.CANCELLED)
    if exclude_run is not None:
        qs = qs.exclude(run=exclude_run)
    return set(qs.values_list("user_id", flat=True))


def _quota_refusal(org, at, users: set[int], exclude_run=None):
    used = seats_used(org, at, exclude_run)
    total = len(used | users)
    if total > org.workshop_seats:
        return Response(
            {
                "code": "quota_exceeded",
                "seats": org.workshop_seats,
                "used": len(used),
                "needed": len(users - used),
            },
            status=status.HTTP_409_CONFLICT,
        )
    return None


# ── Shapes ───────────────────────────────────────────────────────────


def run_out(run, scope=None, at=None) -> dict:
    at = at or services.now()
    w = run.workshop
    ids = set(enrolled_ids(run, scope))
    sessions = WorkshopSession.objects.filter(run=run, user_id__in=ids)
    return {
        "id": run.id,
        "workshop": {"slug": w.slug, "title": w.title, "duration_minutes": w.duration_minutes},
        "audience": run.audience,
        "starts_at": run.starts_at,
        **public.timing(run),
        "status": run.effective_status(at),
        "proctoring": run.effective_proctoring,
        "proctoring_override": run.proctoring,
        "late_join_minutes": run.late_join_minutes,
        "lobby_opens_minutes": run.lobby_opens_minutes,
        "groups": [{"id": g.id, "name": g.name} for g in run.groups.all()],
        "cohorts": [{"id": c.id, "name": c.name} for c in run.cohorts.all()],
        "enrolled": len(ids),
        "joined": sessions.count(),
        "started": sessions.filter(started_at__isnull=False).count(),
        "finished": sessions.filter(status=WorkshopSession.Status.SUBMITTED).count(),
        "passed": sessions.filter(passed=True).count(),
        "created_at": run.created_at,
    }


# ── Validation ───────────────────────────────────────────────────────


def _ids(v) -> list[int] | None:
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > MAX_IDS:
        return None
    out = []
    for x in v:
        if isinstance(x, bool) or not isinstance(x, int | str):
            return None
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            return None
    return sorted(set(out))


def _clean(org, data, run=None) -> tuple[dict, str | None]:
    """Run fields (shared rules with the staff scheduler) plus groups / cohorts that must belong to this org."""
    from apps.orgs.models import Cohort, Group

    from .admin_api import _clean as clean_run

    if not isinstance(data, dict):
        return {}, "bad_request"
    fields, code = clean_run({k: data[k] for k in RUN_FIELDS if k in data}, run)
    if code:
        return {}, code
    for k in ("capacity", "price_paise"):  # org runs: free, no seat cap
        fields.pop(k, None)
    out = {"fields": fields}
    for key, model in (("groups", Group), ("cohorts", Cohort)):
        if key in data or run is None:
            ids = _ids(data.get(key))
            if ids is None or model.objects.filter(org=org, id__in=ids).count() != len(ids):
                return {}, f"bad_{key}"
            out[key] = ids
    return out, None


# ── Views ────────────────────────────────────────────────────────────


@api_view(["GET"])
def overview(request, slug):
    """For the cockpit tab: is the feature on, the month's seats and what this viewer may do."""
    from apps.orgs.extras import feature_on
    from apps.orgs.perms import RANK, require

    me = require(request.user, slug, "manager")
    org = me.org
    at = services.now()
    on = feature_on(org, "workshops")
    return Response(
        {
            "enabled": on,
            "seats": org.workshop_seats,
            "used_this_month": len(seats_used(org, at)) if on else 0,
            "month": f"{timezone.localtime(at):%Y-%m}",
            "can_manage": on and RANK[me.role] >= RANK["admin"],
            "scope": "all" if scope_user_ids(me) is None else "classes",
        }
    )


@api_view(["GET"])
def templates(request, slug):
    try:
        staff(request.user, slug, "manager")
    except FeatureOff:
        return _off()
    return Response(
        [
            {
                "slug": w.slug,
                "title": w.title,
                "summary": w.summary,
                "level": w.level,
                "duration_minutes": w.duration_minutes,
                "proctoring": w.proctoring,
                "stages": len(w.agenda or []),
                "prerequisites": [p.get("label", "") for p in w.prerequisites or []],
            }
            for w in Workshop.objects.filter(is_published=True)
        ]
    )


@api_view(["GET", "POST"])
def runs(request, slug):
    try:
        me = staff(request.user, slug, "admin" if request.method == "POST" else "manager")
    except FeatureOff:
        return _off()
    org = me.org
    if request.method == "GET":
        scope = scope_user_ids(me)
        at = services.now()
        rows = _org_runs(org).prefetch_related("groups", "cohorts").order_by("-starts_at")[:300]
        out = [run_out(r, scope, at) for r in rows]
        if scope is not None:
            out = [r for r in out if r["enrolled"]]
        from apps.orgs.perms import RANK

        return Response(
            {
                "runs": out,
                "quota": {
                    "limit": org.workshop_seats,
                    "used": len(seats_used(org, at)),
                    "month": f"{timezone.localtime(at):%Y-%m}",
                },
                "can_manage": RANK[me.role] >= RANK["admin"],
            }
        )
    data, code = _clean(org, request.data)
    if code:
        return Response({"code": code}, status=status.HTTP_400_BAD_REQUEST)
    users = audience_user_ids(org, data["groups"], data["cohorts"])
    if not users:
        return Response({"code": "no_learners"}, status=status.HTTP_400_BAD_REQUEST)
    from apps.orgs.models import Organization

    with transaction.atomic():
        Organization.objects.select_for_update().filter(pk=org.pk).first()  # serialise quota checks per org
        org.refresh_from_db(fields=["workshop_seats"])
        if refused := _quota_refusal(org, data["fields"]["starts_at"], users):
            return refused
        run = WorkshopRun.objects.create(
            audience=ORG, org=org, status=Status.SCHEDULED, created_by=request.user, **data["fields"]
        )
        run.groups.set(data["groups"])
        run.cohorts.set(data["cohorts"])
        WorkshopEnrollment.objects.bulk_create(
            [WorkshopEnrollment(run=run, user_id=u) for u in sorted(users)], ignore_conflicts=True
        )
    _notify_new(run.id, sorted(users))
    return Response(run_out(run), status=status.HTTP_201_CREATED)


def _notify_new(run_id, user_ids):
    from .tasks import notify_org_run

    notify_org_run.delay(run_id, user_ids)  # called after the scheduling transaction has committed


@api_view(["GET", "PATCH"])
def run_detail(request, slug, pk):
    try:
        me = staff(request.user, slug, "admin" if request.method == "PATCH" else "manager")
    except FeatureOff:
        return _off()
    if request.method == "GET":
        return Response(run_out(visible_run(me, pk), scope_user_ids(me)))
    org = me.org
    get_object_or_404(_org_runs(org), pk=pk)
    moved = False
    added: list[int] = []
    with transaction.atomic():
        run = WorkshopRun.objects.select_for_update(of=("self",)).select_related("workshop").get(pk=pk)
        if run.effective_status(services.now()) != Status.SCHEDULED:
            return Response({"code": "not_editable"}, status=status.HTTP_409_CONFLICT)
        data, code = _clean(org, request.data, run)
        if code:
            return Response({"code": code}, status=status.HTTP_400_BAD_REQUEST)
        fields = data["fields"]
        if "workshop" in fields and fields["workshop"].pk != run.workshop_id and run.sessions.exists():
            return Response({"code": "workshop_locked"}, status=status.HTTP_409_CONFLICT)
        gids = data.get("groups", list(run.groups.values_list("id", flat=True)))
        cids = data.get("cohorts", list(run.cohorts.values_list("id", flat=True)))
        users = audience_user_ids(org, gids, cids)
        if not users:
            return Response({"code": "no_learners"}, status=status.HTTP_400_BAD_REQUEST)
        at = fields.get("starts_at", run.starts_at)
        if refused := _quota_refusal(org, at, users, exclude_run=run):
            return refused
        moved = "starts_at" in fields and fields["starts_at"] != run.starts_at
        for k, v in fields.items():
            setattr(run, k, v)
        run.save()
        run.groups.set(gids)
        run.cohorts.set(cids)
        have = set(WorkshopEnrollment.objects.filter(run=run).values_list("user_id", flat=True))
        added = sorted(users - have)
        WorkshopEnrollment.objects.bulk_create(
            [WorkshopEnrollment(run=run, user_id=u) for u in added], ignore_conflicts=True
        )
        # Learners no longer in the selected classes lose a seat they never used.
        WorkshopEnrollment.objects.filter(run=run, session__isnull=True).exclude(user_id__in=users).delete()
        if moved:
            run.enrollments.update(reminded_24h=False, reminded_15m=False)
    if added:
        _notify_new(run.id, added)
    if moved:
        from .tasks import notify_enrolled

        notify_enrolled.delay(run.id, "moved")
    return Response(run_out(run))


@api_view(["POST"])
def run_cancel(request, slug, pk):
    try:
        me = staff(request.user, slug, "admin")
    except FeatureOff:
        return _off()
    get_object_or_404(_org_runs(me.org), pk=pk)
    with transaction.atomic():
        run = WorkshopRun.objects.select_for_update(of=("self",)).select_related("workshop").get(pk=pk)
        if run.status == Status.CANCELLED:
            return Response(run_out(run))
        if run.effective_status(services.now()) == Status.ENDED:
            return Response({"code": "run_ended"}, status=status.HTTP_409_CONFLICT)
        public.cancel(run, request.user)
    if run.enrollments.exists():
        from .tasks import notify_enrolled

        notify_enrolled.delay(run.id, "cancelled")
    return Response(run_out(run))


# ── Drill-down ───────────────────────────────────────────────────────


TIMELINE_SKIP = ("ai_turn",)


def scoped_session(me, run, session_id) -> WorkshopSession:
    scope = scope_user_ids(me)
    s = get_object_or_404(
        WorkshopSession.objects.select_related("run__workshop", "user__profile"), pk=session_id, run=run
    )
    if scope is not None and s.user_id not in scope:
        from django.http import Http404

        raise Http404
    return s


def stage_times(events, end) -> dict[int, float]:
    """Seconds spent per stage index, from stage_start events (the last stage runs until `end`)."""
    starts = [(e.stage, e.created_at) for e in events if e.type == "stage_start"]
    out: dict[int, float] = {}
    for i, (st, at) in enumerate(starts):
        nxt = starts[i + 1][1] if i + 1 < len(starts) else end
        if nxt and nxt > at:
            out[st] = out.get(st, 0.0) + (nxt - at).total_seconds()
    return out


def _event_out(e, proctoring: bool) -> dict | None:
    from .monitor import ATTENTION_EVENTS

    if e.type in TIMELINE_SKIP or (e.type in ATTENTION_EVENTS and not proctoring):
        return None
    keep = {
        "answer": ("item", "score", "tries", "diy"),
        "concept_done": ("item", "score"),
        "concept_skipped": ("item",),
        "diy_step_done": ("item",),
        "step_skipped": ("item",),
        "help_screenshot": ("summary",),
        "help_error": ("summary",),
        "staff_nudge": ("text", "name"),
        "final_attempt": ("score", "mcq_correct", "mcq_total", "attempt", "agent_score"),
        "build_graded": ("score", "attempt", "type"),
        "stage_start": ("key",),
    }.get(e.type, ())
    return {
        "type": e.type,
        "stage": e.stage,
        "at": e.created_at,
        "data": {k: (e.data or {}).get(k) for k in keep if k in (e.data or {})},
    }


@api_view(["GET"])
def learner_detail(request, slug, pk, session_id):
    from . import monitor

    try:
        me = staff(request.user, slug, "manager")
    except FeatureOff:
        return _off()
    run = visible_run(me, pk)
    s = scoped_session(me, run, session_id)
    proctoring = run.effective_proctoring != "off"
    events = list(WorkshopEvent.objects.filter(session=s).order_by("created_at", "id"))
    end = s.ended_at or (events[-1].created_at if events else None)
    times = stage_times(events, end)
    agenda = s.run.workshop.agenda or []
    turns = list(WorkshopTurn.objects.filter(session=s).order_by("created_at", "id")[:1000])
    done_at = {
        (e.stage, (e.data or {}).get("item")): e.created_at for e in events if e.type == "diy_step_done"
    }
    stages, diy_steps = [], []
    for i, st in enumerate(agenda):
        state_i = services.state(s, i)
        texts = services.item_texts(st)
        items = state_i["items"]
        if not s.started_at or i > s.stage_index:
            stage_status = "not_started"
        elif i < s.stage_index or (items and all(it["done"] for it in items)):
            stage_status = "done"
        else:
            stage_status = "current"
        stages.append(
            {
                "index": i,
                "key": st.get("key", str(i)),
                "title": st.get("title", ""),
                "kind": st.get("kind", ""),
                "status": stage_status,
                "score": (s.scores or {}).get(st.get("key", str(i))),
                "minutes": round(times[i] / 60, 1) if i in times else None,
                "items": [
                    {
                        "text": t,
                        "done": it["done"],
                        "skipped": it.get("skipped", False),
                        "tries": it.get("tries", 0),
                        "score": it.get("score"),
                    }
                    for t, it in zip(texts, items, strict=False)
                ],
            }
        )
        if st.get("kind") in services.DIY_KINDS:
            diy_steps += [
                {"stage": st.get("title", ""), "text": t, "done": it["done"], "at": done_at.get((i, n))}
                for n, (t, it) in enumerate(zip(texts, items, strict=False))
            ]
    answers = []
    for e in events:
        d = e.data or {}
        if e.type != "answer" or "score" not in d:
            continue
        st = agenda[e.stage] if 0 <= e.stage < len(agenda) else {}
        texts = services.item_texts(st)
        item = d.get("item")
        said = [t for t in turns if t.role == "user" and t.stage == e.stage and t.created_at <= e.created_at]
        answers.append(
            {
                "stage": st.get("title", ""),
                "question": texts[item] if isinstance(item, int) and 0 <= item < len(texts) else "",
                "answer": said[-1].text[:2000] if said else "",
                "score": d.get("score"),
                "correct": isinstance(d.get("score"), int | float) and d["score"] >= services.PASS,
                "at": e.created_at,
            }
        )
    from .monitor import ATTENTION_EVENTS, _membership

    return Response(
        {
            "learner": monitor.learner_out(s.user, _membership(s)),
            "tile": monitor.tile(s),
            "started_at": s.started_at,
            "ended_at": s.ended_at,
            "final_score": s.final_score,
            "final_attempts": s.final_attempts,
            "passed": s.passed,
            "proctoring": run.effective_proctoring,
            "stages": stages,
            "answers": answers,
            "diy_steps": diy_steps,
            "help": [
                {"at": e.created_at, "summary": (e.data or {}).get("summary", "")}
                for e in events
                if e.type in ("help_screenshot", "help_error")
            ],
            # Attention only ever exists with proctoring on (and never during DIY stages).
            "attention": [
                {"at": e.created_at, "kind": e.type, "seconds": None}
                for e in events
                if e.type in ATTENTION_EVENTS
            ]
            if proctoring
            else None,
            "attention_summary": {
                "hidden_s": s.hidden_seconds,
                "idle_s": s.idle_seconds,
                "focus_losses": s.focus_losses,
                "score": s.attention_score,
            }
            if proctoring
            else None,
            "nudges": [
                {
                    "at": e.created_at,
                    "text": (e.data or {}).get("text", ""),
                    "from": (e.data or {}).get("name", ""),
                }
                for e in events
                if e.type == "staff_nudge"
            ],
            "timeline": [x for x in (_event_out(e, proctoring) for e in events) if x],
            "transcript": [services.turn_out(t) for t in turns],
        }
    )


# ── Reports ──────────────────────────────────────────────────────────


def _report(request, slug, pk):
    from . import report

    me = staff(request.user, slug, "manager")
    run = visible_run(me, pk)
    return report.compute(me, run)


@api_view(["GET"])
def run_report(request, slug, pk):
    try:
        return Response(_report(request, slug, pk))
    except FeatureOff:
        return _off()


@api_view(["GET"])
def run_report_pdf(request, slug, pk):
    from apps.studio import exports

    from . import report

    try:
        d = _report(request, slug, pk)
    except FeatureOff:
        return _off()
    return exports.download(
        report.render_pdf(d), "application/pdf", exports._fname(report.filename(d), "pdf")
    )


@api_view(["GET"])
def run_report_pptx(request, slug, pk):
    from apps.studio import exports

    from . import report

    try:
        d = _report(request, slug, pk)
    except FeatureOff:
        return _off()
    return exports.download(report.render_pptx(d), exports.PPTX, exports._fname(report.filename(d), "pptx"))


@api_view(["GET"])
def run_report_csv(request, slug, pk):
    from apps.studio import exports

    from . import report

    try:
        d = _report(request, slug, pk)
    except FeatureOff:
        return _off()
    return exports.download(
        report.render_csv(d).encode("utf-8-sig"),
        "text/csv; charset=utf-8",
        exports._fname(report.filename(d), "csv"),
    )
