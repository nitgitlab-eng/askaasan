"""Teacher tools (M9): role-play analytics per assigned scenario, per-question drill-down with keys for teachers,
AI class insights / misconceptions (cached + charged), end-of-training survey hook, assignable scenarios.

Scope: owners/admins see every learner of the org. A manager (teacher) attached to one or more classes sees only
those classes; a manager in no class sees the whole org (small schools where one teacher runs everything)."""

import csv
import io
import json
from collections import Counter, defaultdict

from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.learning.models import ActivityAttempt, Subsection, UserSubsectionState
from llm.fence import fence

from .models import Assignment, Membership, SurveyResponse, TeachInsight
from .perms import RANK, require

TEACH_AI_PER_DAY = 30  # AI insight / misconception runs per teacher per day
MAX_ATTEMPTS_FOR_AI = 80


# ── Scope ─────────────────────────────────────────────────────────────


def _classes(org):
    return org.groups.exclude(name="Everyone")


def scope_groups(me: Membership) -> set[int] | None:
    """Class ids this staff member may see; None = the whole org (admins/owners, or an org without any classes).
    A manager attached to no class sees nobody (fail closed) until an admin adds them to one."""
    if RANK[me.role] >= RANK["admin"] or not _classes(me.org).exists():
        return None
    return set(me.groups.exclude(name="Everyone").filter(org=me.org).values_list("id", flat=True))


def no_class(me) -> bool:
    return scope_groups(me) == set()


def _effective_groups(me, a) -> set[int] | None:
    """The classes this viewer's numbers for assignment `a` are cut to (None = the assignment's full audience).
    Purely by class: having created the assignment gives no extra reach (a demoted or class-removed teacher keeps none)."""
    g = scope_groups(me)
    if g is None or (a is not None and a.group_id in g):
        return None
    return g


def scope_key(me, a=None) -> str:
    """Cache key for AI read-outs: exactly the learner set they were computed over (full audience vs. a hashed class list)."""
    import hashlib

    g = _effective_groups(me, a)
    if g is None:
        return "all"
    return "g:" + hashlib.sha256(",".join(str(x) for x in sorted(g)).encode()).hexdigest()


def scoped_learners(me):
    qs = Membership.objects.filter(org=me.org, role="learner")
    g = scope_groups(me)
    return qs if g is None else qs.filter(groups__id__in=g).distinct()


def visible_assignment(me, pk) -> Assignment:
    a = get_object_or_404(
        Assignment.objects.select_related("curriculum", "scenario", "group", "survey", "org"),
        pk=pk,
        org=me.org,
    )
    g = scope_groups(me)
    if g is not None and a.group_id and a.group_id not in g:
        raise PermissionDenied("not_your_class")
    return a


def assignment_learners(me, a):
    """The assignment's audience, cut down to the teacher's classes (for org-wide assignments)."""
    from .api import _assignment_learners

    qs = _assignment_learners(a)
    g = _effective_groups(me, a)
    if g is not None:
        qs = qs.filter(groups__id__in=g).distinct()
    return list(qs.select_related("user__profile"))


def _name(m):
    from .api import _first

    return _first(m.user)


def _charge(user):
    from apps.providers.services import BudgetExceeded, charge

    try:
        charge(user, "teach_ai", 1, TEACH_AI_PER_DAY)
    except BudgetExceeded:
        return Response({"code": "budget_exceeded"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    return None


def _lang(user):
    from apps.learning.services import content_language
    from llm.prompts.curriculum import LANG_RULE

    return LANG_RULE.get(content_language(user), LANG_RULE["en"])


def _cached(a, kind, me, subsection=None):
    row = (
        TeachInsight.objects.filter(assignment=a, kind=kind, subsection=subsection, scope=scope_key(me, a))
        .order_by("-updated_at")
        .first()
    )
    return {**row.data, "updated_at": row.updated_at} if row else None


def _store(a, kind, me, data, subsection=None):
    TeachInsight.objects.update_or_create(
        assignment=a,
        kind=kind,
        subsection=subsection,
        scope=scope_key(me, a),
        defaults={"data": data, "created_by": me.user},
    )
    return _cached(a, kind, me, subsection)


# ── Role-play statistics ─────────────────────────────────────────────


def _sessions(a, user_ids):
    from apps.roleplay.models import RolePlaySession

    # Only attempts started for THIS assignment (personal practice and other orgs' assignments of the same
    # library scenario are excluded).
    return RolePlaySession.objects.filter(
        assignment=a, scenario_id=a.scenario_id, user_id__in=user_ids, started_at__gte=a.created_at
    ).order_by("started_at", "id")


def _secs(s):
    return int((s.ended_at - s.started_at).total_seconds()) if s.ended_at else None


def _stats(sessions) -> dict:
    done = [s for s in sessions if s.status == "completed" and s.result]
    scores = [int(s.result.get("overall", 0)) for s in done]
    last = done[-1] if done else None
    return {
        "attempts": len(done),
        "latest": scores[-1] if scores else None,
        "best": max(scores) if scores else None,
        "last_duration": _secs(last) if last else None,
        "last_attempt": sessions[-1].started_at if sessions else None,
        "status": "done" if done else "in_progress" if sessions else "not_started",
    }


def roleplay_rows(a, learners) -> list[dict]:
    by_user = defaultdict(list)
    for s in _sessions(a, [m.user_id for m in learners]):
        by_user[s.user_id].append(s)
    return [{"user_id": m.user_id, "name": _name(m), **_stats(by_user[m.user_id])} for m in learners]


def my_scenario_status(user, a) -> dict:
    return _stats(list(_sessions(a, [user.id])))


# ── End-of-training survey hook (learner side) ───────────────────────


def _course_finished(user, curriculum_id) -> bool:
    subs = Subsection.objects.filter(
        section__curriculum_id=curriculum_id, archived=False, section__archived=False
    )
    total = subs.count()
    return (
        bool(total)
        and UserSubsectionState.objects.filter(user=user, subsection__in=subs, status="completed").count()
        >= total
    )


def feedback_survey_for(user, curriculum_id=None, scenario_id=None, assignment_id=None) -> dict | None:
    """The school's feedback survey to show after finishing an assigned course / role-play (if not answered yet)."""
    from .api import learner_assignments
    from .surveys import _respondent_key

    qs = learner_assignments(user).filter(survey__isnull=False, survey__status="open")
    qs = (
        qs.filter(scenario_id=scenario_id, pk=assignment_id)
        if scenario_id
        else qs.filter(curriculum_id=curriculum_id)
    )
    if not qs.exists() or (curriculum_id and not _course_finished(user, curriculum_id)):
        return None
    for a in qs:
        s = a.survey
        if not SurveyResponse.objects.filter(survey=s, respondent_key=_respondent_key(s, user)).exists():
            return {
                "id": s.id,
                "title": s.title,
                "org": a.org.display_name or a.org.name,
                "url": f"/surveys#survey-{s.id}",
            }
    return None


# ── Assignable scenarios ─────────────────────────────────────────────


@api_view(["GET"])
def scenarios(request, slug):
    from apps.roleplay.api import _scenario_out, _visible_scenarios
    from apps.roleplay.models import Scenario

    me = require(request.user, slug, "manager")
    _visible_scenarios(request.user)  # makes sure the built-in library exists
    qs = Scenario.objects.filter(assignable_scenarios_q(me)).order_by("source", "-created_at")[:120]
    return Response([_scenario_out(s) for s in qs])


def assignable_scenarios_q(me) -> Q:
    """Built-in library, the teacher's own, and scenarios already shared with this org by an earlier assignment."""
    return Q(source="library") | Q(owner=me.user) | Q(assignments__org=me.org)


def _shared_course_ids(org):
    """Courses legitimately shared with this org: assigned here by their own author (see courses.author_shared_ids)."""
    from .courses import author_shared_ids

    return author_shared_ids(org)


def assignable_courses_q(me) -> Q:
    """Same rule as units / cohorts (courses.assignable_q): own, this org's templates, catalog-approved, author-shared."""
    from .courses import assignable_q

    return assignable_q(me.org, me.user)


def can_see_keys(me, a) -> bool:
    """Answer keys only for the course's author, or — for this org's own templates — the org's staff. Catalog-approved
    or otherwise shared courses stay assignable but their keys stay hidden."""
    cur = a.curriculum
    if not cur:
        return False
    if cur.owner_id == me.user_id:
        return True
    return (
        cur.template_scope == "org" and cur.template_org_id == me.org_id and RANK[me.role] >= RANK["manager"]
    )


# ── Role-play analytics ──────────────────────────────────────────────


def _csv_response(header, rows, filename, extra=()):
    """One CSV; `extra` = more (title, header, rows) tables appended after a blank line. Every cell (headers too)
    is formula-safe: concept names and learner names are author / learner text."""
    from .csvsafe import csv_safe as _csv_safe

    buf = io.StringIO()
    w = csv.writer(buf)
    for i, (_title, h, rs) in enumerate([("", header, rows), *extra]):
        if i:
            w.writerow([])
        w.writerow([_csv_safe(v) for v in h])
        for r in rs:
            w.writerow([_csv_safe(v) for v in r])
    resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp["Cache-Control"] = "no-store"
    return resp


@api_view(["GET"])
def roleplay_report(request, slug, pk):
    me = require(request.user, slug, "manager")
    a = visible_assignment(me, pk)
    if not a.scenario_id:
        return Response({"code": "not_roleplay"}, status=status.HTTP_400_BAD_REQUEST)
    from django.utils import timezone

    from . import teach_rp

    learners = assignment_learners(me, a)
    rows = roleplay_rows(a, learners)
    try:
        days = max(
            1,
            min(
                teach_rp.STUCK_DAYS_MAX,
                int(request.query_params.get("stuck_days") or teach_rp.STUCK_DAYS_DEFAULT),
            ),
        )
    except ValueError:
        days = teach_rp.STUCK_DAYS_DEFAULT
    comp = teach_rp.build(a, learners, timezone.now(), days)
    fmt = request.query_params.get("export")
    if fmt in ("csv", "xlsx"):
        header = [
            "Learner",
            "Status",
            "Latest score",
            "Best score",
            "Attempts",
            "Last duration (min)",
            "Last attempt",
        ]
        data = [
            [
                r["name"],
                r["status"].replace("_", " "),
                r["latest"],
                r["best"],
                r["attempts"],
                round(r["last_duration"] / 60, 1) if r["last_duration"] else None,
                r["last_attempt"].strftime("%Y-%m-%d %H:%M") if r["last_attempt"] else None,
            ]
            for r in rows
        ]
        extra = teach_rp.export_tables(comp) if rows else []  # nobody in scope → header only
        if fmt == "csv":
            return _csv_response(header, data, f"roleplay-{a.id}.csv", extra)
        from apps.studio import exports

        body = exports.workbook([("Role-play", header, data), *extra])
        return exports.download(body, exports.XLSX, exports._fname(f"roleplay {a.scenario.title}", "xlsx"))
    done = [r for r in rows if r["status"] == "done"]
    avg = lambda k: round(sum(r[k] for r in done) / len(done), 1) if done else None
    return Response(
        {
            "assignment": {
                "id": a.id,
                "scenario": {"id": a.scenario_id, "title": a.scenario.title, "emoji": a.scenario.emoji},
                "group": a.group.name if a.group_id else None,
                "due_at": a.due_at,
                "mandatory": a.mandatory,
            },
            "summary": {
                "learners": len(rows),
                "done": len(done),
                "in_progress": sum(r["status"] == "in_progress" for r in rows),
                "not_started": sum(r["status"] == "not_started" for r in rows),
                "avg_best": avg("best"),
                "avg_latest": avg("latest"),
            },
            "rows": rows,
            "no_class": no_class(me),
            "insights": _cached(a, "roleplay", me),
            "competency": comp,
        }
    )


@api_view(["GET"])
def roleplay_learner(request, slug, pk, uid):
    me = require(request.user, slug, "manager")
    a = visible_assignment(me, pk)
    m = next((x for x in assignment_learners(me, a) if x.user_id == uid), None)
    if not a.scenario_id or not m:
        return Response({"code": "not_found"}, status=status.HTTP_404_NOT_FOUND)
    out = [
        {
            "id": s.id,
            "status": s.status,
            "started_at": s.started_at,
            "ended_at": s.ended_at,
            "duration": _secs(s),
            "score": int(s.result.get("overall", 0)) if s.result else None,
            "result": s.result,
        }
        for s in _sessions(a, [uid])
    ]
    return Response({"user_id": uid, "name": _name(m), "attempts": out})


@api_view(["GET", "POST"])
def roleplay_insights(request, slug, pk):
    from llm.base import LLMError
    from llm.prompts.teach import ROLEPLAY_INSIGHTS_SYSTEM, RolePlayInsights
    from llm.structured import complete_json_sync

    me = require(request.user, slug, "manager")
    a = visible_assignment(me, pk)
    if not a.scenario_id:
        return Response({"code": "not_roleplay"}, status=status.HTTP_400_BAD_REQUEST)
    if request.method == "GET":
        return Response({"insights": _cached(a, "roleplay", me)})
    uids = [m.user_id for m in assignment_learners(me, a)]
    done = [
        s
        for s in _sessions(a, uids).filter(status="completed").order_by("-ended_at")[:MAX_ATTEMPTS_FOR_AI]
        if s.result
    ]
    if not done:
        return Response({"code": "no_attempts"}, status=status.HTTP_400_BAD_REQUEST)
    if refused := _charge(request.user):
        return refused
    sc = a.scenario
    lines = []
    for i, s in enumerate(done, 1):
        r = s.result
        comps = ", ".join(f"{c.get('name')}: {c.get('score')}/5" for c in r.get("competencies", []))
        lines.append(
            f"Attempt {i}: score {r.get('overall')}/100. Competencies: {comps}. Strengths: {'; '.join(r.get('strengths', [])[:3])}. "
            f"Improvements: {'; '.join(r.get('improvements', [])[:3])}. Coach summary: {str(r.get('summary', ''))[:300]}"
        )
    user_msg = (
        f"Scenario: {sc.title}\nLearner's role: {sc.learner_role}\nObjectives: {'; '.join(sc.objectives)}\n"
        f"Attempts by {len({s.user_id for s in done})} learners:\n" + fence("feedback", "\n".join(lines))
    )
    try:
        out = complete_json_sync(
            "suggest",
            ROLEPLAY_INSIGHTS_SYSTEM.format(lang_rule=_lang(request.user)),
            user_msg,
            RolePlayInsights,
            max_tokens=1500,
        )
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response({"insights": _store(a, "roleplay", me, {**out.model_dump(), "attempts": len(done)})})


@api_view(["GET", "POST"])
def roleplay_concept(request, slug, pk, key):
    """Per-concept drill-down (objective `o<i>` / competency `c<i>`): what learners got right / wrong, from the coach's
    per-turn reasons and the final reports; POST = AI summary of it (cached per viewer scope, charged)."""
    from llm.base import LLMError
    from llm.prompts.teach import ROLEPLAY_CONCEPT_SYSTEM, RolePlayConceptInsight
    from llm.structured import complete_json_sync

    from . import teach_rp

    me = require(request.user, slug, "manager")
    a = visible_assignment(me, pk)
    if not a.scenario_id or not teach_rp.KEY_RE.match(key):
        return Response({"code": "not_found"}, status=status.HTTP_404_NOT_FOUND)
    d = teach_rp.drill(a, assignment_learners(me, a), key)
    if d is None:
        return Response({"code": "not_found"}, status=status.HTTP_404_NOT_FOUND)
    kind = f"rpc:{key}"
    if request.method == "GET":
        return Response({**d, "no_class": no_class(me), "insight": _cached(a, kind, me)})
    if not (d["right"] or d["wrong"]):
        return Response({"code": "no_attempts"}, status=status.HTTP_400_BAD_REQUEST)
    if refused := _charge(request.user):
        return refused
    try:
        out = complete_json_sync(
            "suggest",
            ROLEPLAY_CONCEPT_SYSTEM.format(lang_rule=_lang(request.user)),
            teach_rp.drill_prompt(a.scenario, d),
            RolePlayConceptInsight,
            max_tokens=1200,
        )
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    data = out.model_dump()
    data = {k: (v[:4] if isinstance(v, list) else v) for k, v in data.items()}
    return Response({"insight": _store(a, kind, me, {**data, "concept": d["concept"]["name"]})})


# ── Course drill-down: lessons → questions → each learner's answer ───


def _course_assignment(request, slug, pk):
    me = require(request.user, slug, "manager")
    a = visible_assignment(me, pk)
    if not a.curriculum_id:
        return me, a, Response({"code": "not_course"}, status=status.HTTP_400_BAD_REQUEST)
    return me, a, None


@api_view(["GET"])
def course_lessons(request, slug, pk):
    me, a, bad = _course_assignment(request, slug, pk)
    if bad:
        return bad
    learners = assignment_learners(me, a)
    uids = [m.user_id for m in learners]
    subs = list(
        Subsection.objects.filter(section__curriculum=a.curriculum, archived=False, section__archived=False)
        .select_related("section")
        .order_by("section__order", "order")
    )
    completed = Counter(
        UserSubsectionState.objects.filter(
            subsection__in=subs, user_id__in=uids, status="completed"
        ).values_list("subsection_id", flat=True)
    )
    latest = {}
    for uid, aid, sid, ok in (
        ActivityAttempt.objects.filter(
            activity__subsection__in=subs, activity__kind="lesson", user_id__in=uids
        )
        .order_by("created_at", "id")
        .values_list("user_id", "activity_id", "activity__subsection_id", "correct")
    ):
        latest[(uid, aid)] = (sid, ok)
    right, answered = Counter(), Counter()
    for sid, ok in latest.values():
        answered[sid] += 1
        right[sid] += int(ok)
    return Response(
        {
            "course": {"id": a.curriculum_id, "title": a.curriculum.title, "emoji": a.curriculum.cover_emoji},
            "learners": len(learners),
            "no_class": no_class(me),
            "lessons": [
                {
                    "id": s.id,
                    "title": s.title,
                    "section": s.section.title,
                    "questions": s.activities.filter(kind="lesson").count(),
                    "completed": completed[s.id],
                    "answers": answered[s.id],
                    "correct_rate": round(right[s.id] / answered[s.id], 3) if answered[s.id] else None,
                }
                for s in subs
            ],
        }
    )


def _lesson_data(me, a, sid):
    sub = get_object_or_404(Subsection, pk=sid, section__curriculum_id=a.curriculum_id)
    learners = assignment_learners(me, a)
    names = {m.user_id: _name(m) for m in learners}
    acts = list(sub.activities.filter(kind="lesson").order_by("order"))
    latest, counts = {}, Counter()
    for at in ActivityAttempt.objects.filter(activity__in=acts, user_id__in=list(names)).order_by(
        "created_at", "id"
    ):
        latest[(at.user_id, at.activity_id)] = at
        counts[(at.user_id, at.activity_id)] += 1
    return sub, names, acts, latest, counts


@api_view(["GET"])
def course_lesson(request, slug, pk, sid):
    from .teach_render import render_answer, render_key

    me, a, bad = _course_assignment(request, slug, pk)
    if bad:
        return bad
    sub, names, acts, latest, counts = _lesson_data(me, a, sid)
    keys = can_see_keys(me, a)
    questions = []
    for act in acts:
        rows = []
        for uid, name in names.items():
            at = latest.get((uid, act.id))
            rows.append(
                {
                    "user_id": uid,
                    "name": name,
                    "answered": bool(at),
                    "answer": render_answer(act, at.answer) if at else None,
                    "correct": at.correct if at else None,
                    "score": round(at.score, 3) if at else None,
                    "attempts": counts[(uid, act.id)],
                    "at": at.created_at if at else None,
                }
            )
        ans = [r for r in rows if r["answered"]]
        questions.append(
            {
                "id": act.id,
                "type": act.type,
                "title": act.title,
                "prompt": (act.payload or {}).get("prompt", ""),
                "key": render_key(act) if keys else None,
                "answered": len(ans),
                "correct": sum(1 for r in ans if r["correct"]),
                "learners": rows,
            }
        )
    return Response(
        {
            "lesson": {"id": sub.id, "title": sub.title, "objective": sub.objective},
            "questions": questions,
            "keys": keys,
            "misconceptions": _cached(a, "misconceptions", me, sub) if keys else None,
        }
    )


@api_view(["GET", "POST"])
def lesson_misconceptions(request, slug, pk, sid):
    from llm.base import LLMError
    from llm.prompts.teach import MISCONCEPTIONS_SYSTEM, Misconceptions
    from llm.structured import complete_json_sync

    from .teach_render import render_answer, render_key

    me, a, bad = _course_assignment(request, slug, pk)
    if bad:
        return bad
    if not can_see_keys(me, a):  # the analysis works from the answer key
        return Response({"code": "keys_hidden"}, status=status.HTTP_403_FORBIDDEN)
    sub, _names, acts, latest, _ = _lesson_data(me, a, sid)
    if request.method == "GET":
        return Response({"misconceptions": _cached(a, "misconceptions", me, sub)})
    blocks = []
    for act in acts:
        wrong = Counter(
            render_answer(act, at.answer)[:200]
            for (uid, aid), at in latest.items()
            if aid == act.id and not at.correct
        )
        if wrong:
            k = render_key(act)
            blocks.append(
                f'Question "{act.title}" ({act.type}): {str((act.payload or {}).get("prompt", ""))[:400]}\n'
                f"Correct answer: {k['answer'][:300]}\nWhy: {k['rationale'][:300]}\nWrong answers:\n"
                + "\n".join(f"- ({n}×) {txt}" for txt, n in wrong.most_common(15))
            )
    if not blocks:
        return Response({"code": "no_wrong_answers"}, status=status.HTTP_400_BAD_REQUEST)
    if refused := _charge(request.user):
        return refused
    user_msg = f"Lesson: {sub.title}\nObjective: {sub.objective[:300]}\n" + fence(
        "answers", "\n\n".join(blocks)[:12000]
    )
    try:
        out = complete_json_sync(
            "suggest",
            MISCONCEPTIONS_SYSTEM.format(lang_rule=_lang(request.user)),
            user_msg,
            Misconceptions,
            max_tokens=2500,
        )
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    data = out.model_dump()
    data["misconceptions"] = data["misconceptions"][:6]
    return Response({"misconceptions": _store(a, "misconceptions", me, json.loads(json.dumps(data)), sub)})
