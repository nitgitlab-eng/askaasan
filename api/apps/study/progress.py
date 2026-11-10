"""P6: learner analytics — time, engagement, skills, knowledge graph, answer efficiency, AI insights, ask-your-data.

'Ask your data' never runs model-written queries: the AI only picks (metric, group_by, days, chart) from a fixed
catalog and the server computes the answer from the learner's own rows."""

from collections import defaultdict
from datetime import date, timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import ProgressInsight

SESSION_GAP_MIN = 20
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
CATALOG = {  # metric → allowed groupings (first = default)
    "xp": ["day", "week", "weekday"],
    "minutes": ["day", "week", "weekday"],
    "attempts": ["day", "week", "weekday", "activity_type", "course", "skill"],
    "reviews": ["day", "week", "weekday"],
    "accuracy": ["activity_type", "day", "week", "course", "skill"],
    "lessons": ["day", "week", "course"],
    "mastery": ["skill", "course"],
}
GROUPS = sorted({g for gs in CATALOG.values() for g in gs})


def _days_param(raw, default=30) -> int:
    try:
        return max(7, min(365, int(raw)))
    except (TypeError, ValueError):
        return default


def _local(dt) -> date:
    return timezone.localtime(dt).date()


def _events(user, since):
    """Timestamps of everything the learner actively did (for time/session estimates)."""
    from apps.learning.models import ActivityAttempt
    from apps.mentor.models import Message
    from apps.review.models import ReviewLog

    ts = list(
        ActivityAttempt.objects.filter(user=user, created_at__gte=since).values_list("created_at", flat=True)
    )
    ts += list(
        ReviewLog.objects.filter(card__user=user, created_at__gte=since).values_list("created_at", flat=True)
    )
    ts += list(
        Message.objects.filter(conversation__user=user, role="user", created_at__gte=since).values_list(
            "created_at", flat=True
        )
    )
    return sorted(ts)


def _sessions(ts) -> list[tuple]:
    out, start, last = [], None, None
    for t in ts:
        if last is None or (t - last).total_seconds() > SESSION_GAP_MIN * 60:
            if start is not None:
                out.append((start, last))
            start = t
        last = t
    if start is not None:
        out.append((start, last))
    return out


def minutes_by_day(user, since) -> dict[date, int]:
    """Estimated active minutes: session span + 2 minutes, capped at 2 hours per session."""
    out: dict[date, int] = defaultdict(int)
    for a, b in _sessions(_events(user, since)):
        out[_local(a)] += min(120, int((b - a).total_seconds() // 60) + 2)
    return out


def _bucket(d: date, group: str) -> str:
    if group == "week":
        return (d - timedelta(days=d.weekday())).isoformat()
    if group == "weekday":
        return WEEKDAYS[d.weekday()]
    return d.isoformat()


def _first_attempts(user, since):
    from apps.learning.models import ActivityAttempt

    seen, out = set(), []
    for a in (
        ActivityAttempt.objects.filter(user=user)
        .select_related("activity__subsection__section__curriculum")
        .order_by("created_at", "id")
    ):
        if a.activity_id in seen:
            continue
        seen.add(a.activity_id)
        if a.created_at >= since:
            out.append(a)
    return out


def compute(user, metric: str, group: str, days: int) -> list[dict]:
    """Aggregate one catalog metric for this learner only. Returns [{label, value}] in display order."""
    from django.db.models import Sum

    from apps.game.models import XPEvent
    from apps.learning.models import ActivityAttempt, UserSubsectionState
    from apps.review.models import MasteryRecord, ReviewLog

    if metric not in CATALOG:
        metric = "xp"
    if group not in CATALOG[metric]:
        group = CATALOG[metric][0]
    since_d = timezone.localdate() - timedelta(days=days - 1)
    since = timezone.make_aware(timezone.datetime.combine(since_d, timezone.datetime.min.time()))
    acc: dict[str, float] = defaultdict(float)
    cnt: dict[str, int] = defaultdict(int)
    skill_names = {}

    def sk(sub):
        from apps.paths.models import Skill
        from apps.paths.services import match_skills

        slugs = match_skills((sub.skills or []) + [sub.title]) or match_skills(
            sub.section.curriculum.skills or []
        )
        if not skill_names:
            skill_names.update(dict(Skill.objects.values_list("slug", "name")))
        return [skill_names.get(s, s) for s in slugs] or ["Other"]

    if metric == "xp":
        for d, x in (
            XPEvent.objects.filter(user=user, day__gte=since_d).values_list("day").annotate(t=Sum("xp"))
        ):
            acc[_bucket(d, group)] += x
    elif metric == "minutes":
        for d, m in minutes_by_day(user, since).items():
            acc[_bucket(d, group)] += m
    elif metric == "reviews":
        for t in ReviewLog.objects.filter(card__user=user, created_at__gte=since).values_list(
            "created_at", flat=True
        ):
            acc[_bucket(_local(t), group)] += 1
    elif metric == "lessons":
        for st in UserSubsectionState.objects.filter(
            user=user, status="completed", completed_at__gte=since
        ).select_related("subsection__section__curriculum"):
            k = (
                st.subsection.section.curriculum.title
                if group == "course"
                else _bucket(_local(st.completed_at), group)
            )
            acc[k] += 1
    elif metric == "attempts":
        for a in ActivityAttempt.objects.filter(user=user, created_at__gte=since).select_related(
            "activity__subsection__section__curriculum"
        ):
            keys = (
                [a.activity.type]
                if group == "activity_type"
                else [a.activity.subsection.section.curriculum.title]
                if group == "course"
                else sk(a.activity.subsection)
                if group == "skill"
                else [_bucket(_local(a.created_at), group)]
            )
            for k in keys:
                acc[k] += 1
    elif metric == "accuracy":  # first-try accuracy %
        for a in _first_attempts(user, since):
            keys = (
                [a.activity.type]
                if group == "activity_type"
                else [a.activity.subsection.section.curriculum.title]
                if group == "course"
                else sk(a.activity.subsection)
                if group == "skill"
                else [_bucket(_local(a.created_at), group)]
            )
            for k in keys:
                acc[k] += 1 if a.correct else 0
                cnt[k] += 1
        acc = {k: round(100 * v / cnt[k]) for k, v in acc.items()}
    elif metric == "mastery":
        if group == "skill":
            from apps.paths.models import Skill
            from apps.paths.services import skill_mastery

            names = dict(Skill.objects.values_list("slug", "name"))
            acc = {names.get(k, k): round(v * 100) for k, v in skill_mastery(user).items()}
        else:
            vals = defaultdict(list)
            for m in MasteryRecord.objects.filter(user=user).select_related(
                "subsection__section__curriculum"
            ):
                vals[m.subsection.section.curriculum.title].append(m.p_known)
            acc = {k: round(100 * sum(v) / len(v)) for k, v in vals.items()}

    if group in ("day", "week"):  # continuous axis: fill gaps with 0
        step = 7 if group == "week" else 1
        d = since_d - timedelta(days=since_d.weekday()) if group == "week" else since_d
        rows = []
        while d <= timezone.localdate():
            k = d.isoformat()
            rows.append({"label": k, "value": acc.get(k, 0)})
            d += timedelta(days=step)
        return rows
    if group == "weekday":
        return [{"label": w, "value": acc.get(w, 0)} for w in WEEKDAYS]
    return sorted(({"label": k, "value": v} for k, v in acc.items()), key=lambda r: -r["value"])[:15]


def dashboard(user, days: int) -> dict:
    from apps.game.services import stats_for
    from apps.learning.models import UserSubsectionState
    from apps.paths.models import Skill
    from apps.paths.services import skill_mastery, user_skill_rows
    from apps.review.models import MasteryRecord

    since_d = timezone.localdate() - timedelta(days=days - 1)
    since = timezone.make_aware(timezone.datetime.combine(since_d, timezone.datetime.min.time()))
    mins = compute(user, "minutes", "day", days)
    xp = compute(user, "xp", "day", days)
    sessions = _sessions(_events(user, since))
    firsts = _first_attempts(user, since)
    s = stats_for(user)

    by_type = defaultdict(lambda: [0, 0])
    for a in firsts:
        by_type[a.activity.type][0] += 1 if a.correct else 0
        by_type[a.activity.type][1] += 1
    usage = {r["label"]: r["value"] for r in compute(user, "attempts", "skill", days)}
    mastery = skill_mastery(user)
    prefs = user_skill_rows(user)
    names = {sk.slug: sk for sk in Skill.objects.all()}
    skill_rows = []
    for slug in set(mastery) | {k for k, v in prefs.items() if v.followed}:
        sk = names.get(slug)
        if sk:
            skill_rows.append(
                {
                    "slug": slug,
                    "name": sk.name,
                    "name_ta": sk.name_ta,
                    "mastery": mastery.get(slug),
                    "usage": usage.get(sk.name, 0),
                    "followed": bool(prefs.get(slug) and prefs[slug].followed),
                }
            )
    skill_rows.sort(key=lambda r: (-(r["mastery"] or 0), r["name"]))

    # Knowledge graph: skills ↔ the lessons that build them (most recent 40 practised lessons).
    from apps.paths.services import match_skills

    nodes, edges, seen = [], [], set()
    for m in (
        MasteryRecord.objects.filter(user=user)
        .select_related("subsection__section__curriculum")
        .order_by("-updated_at")[:40]
    ):
        sub = m.subsection
        nodes.append(
            {
                "id": f"l{sub.id}",
                "label": sub.title,
                "type": "lesson",
                "mastery": round(m.p_known, 2),
                "link": f"/learn/{sub.section.curriculum_id}/lesson/{sub.id}",
            }
        )
        for slug in match_skills((sub.skills or []) + [sub.title]) or match_skills(
            sub.section.curriculum.skills or []
        ):
            if slug not in seen and slug in names:
                seen.add(slug)
                nodes.append(
                    {
                        "id": f"s{slug}",
                        "label": names[slug].name,
                        "type": "skill",
                        "mastery": mastery.get(slug),
                    }
                )
            edges.append({"from": f"l{sub.id}", "to": f"s{slug}"})

    total_first = len(firsts)
    return {
        "days": days,
        "totals": {
            "minutes": sum(r["value"] for r in mins),
            "xp": sum(r["value"] for r in xp),
            "sessions": len(sessions),
            "active_days": sum(1 for r in mins if r["value"]),
            "streak": s.streak,
            "best_streak": s.best_streak,
            "lessons": UserSubsectionState.objects.filter(
                user=user, status="completed", completed_at__gte=since
            ).count(),
            "first_try_accuracy": round(100 * sum(1 for a in firsts if a.correct) / total_first)
            if total_first
            else None,
        },
        "minutes": mins,
        "xp": xp,
        "by_weekday": compute(user, "minutes", "weekday", days),
        "efficiency": sorted(
            ({"type": t, "attempts": v[1], "accuracy": round(100 * v[0] / v[1])} for t, v in by_type.items()),
            key=lambda r: -r["attempts"],
        ),
        "skills": skill_rows[:20],
        "graph": {"nodes": nodes, "edges": edges},
    }


@api_view(["GET"])
def progress(request):
    return Response(dashboard(request.user, _days_param(request.query_params.get("days"))))


def _ai_charge(user, max_tokens=None):
    from apps.providers.services import BudgetExceeded, charge

    try:
        charge(user, "ai_grades", 1, 200, max_tokens=max_tokens)  # weighted by call size (H5)
        return None
    except BudgetExceeded:
        return Response({"code": "ai_budget_exceeded"}, status=status.HTTP_429_TOO_MANY_REQUESTS)


@api_view(["POST"])
def insights(request):
    """AI weekly summary (cached per ISO week + language; ?refresh is not offered to keep cost bounded)."""
    import json

    from apps.learning.services import content_language
    from llm.base import LLMError
    from llm.prompts.curriculum import LANG_RULE
    from llm.prompts.study import INSIGHT_SYSTEM, Insights
    from llm.structured import complete_json_sync

    lang = content_language(request.user)
    y, w, _ = timezone.localdate().isocalendar()
    week = f"{y}-W{w:02d}"
    cached = ProgressInsight.objects.filter(user=request.user, week=week, lang=lang).first()
    if cached:
        return Response({**cached.data, "week": week, "cached": True})
    if denied := _ai_charge(request.user, max_tokens=1500):
        return denied
    d = dashboard(request.user, 30)
    facts = {
        "totals": d["totals"],
        "skills": [{k: r[k] for k in ("name", "mastery", "usage", "followed")} for r in d["skills"][:10]],
        "accuracy_by_type": d["efficiency"][:8],
        "minutes_by_weekday": d["by_weekday"],
    }
    try:
        out = complete_json_sync(
            "suggest",
            INSIGHT_SYSTEM.format(lang_rule=LANG_RULE.get(lang, LANG_RULE["en"])),
            json.dumps(facts, default=str),
            Insights,
            max_tokens=1500,
        )
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    data = out.model_dump()
    ProgressInsight.objects.update_or_create(user=request.user, week=week, lang=lang, defaults={"data": data})
    return Response({**data, "week": week, "cached": False})


@api_view(["POST"])
def ask(request):
    """'Ask your data': plain-language question → one whitelisted aggregate → chart data."""
    from apps.learning.services import content_language
    from llm.base import LLMError
    from llm.prompts.curriculum import LANG_RULE
    from llm.prompts.study import ASK_SYSTEM, AskQuery
    from llm.structured import complete_json_sync

    q = str(request.data.get("question") or "").strip()
    if not 3 <= len(q) <= 300:
        return Response({"code": "bad_question"}, status=status.HTTP_400_BAD_REQUEST)
    if denied := _ai_charge(request.user, max_tokens=600):
        return denied
    lang = content_language(request.user)
    metrics = "; ".join(f"{m} (group by {', '.join(g)})" for m, g in CATALOG.items())
    try:
        aq = complete_json_sync(
            "suggest",
            ASK_SYSTEM.format(
                metrics=metrics, groups=", ".join(GROUPS), lang_rule=LANG_RULE.get(lang, LANG_RULE["en"])
            ),
            f"Today is {timezone.localdate()}. Question: {q}",
            AskQuery,
            max_tokens=600,
        )
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if not aq.supported or aq.metric not in CATALOG:
        return Response({"supported": False, "note": aq.note[:300]})
    group = aq.group_by if aq.group_by in CATALOG[aq.metric] else CATALOG[aq.metric][0]
    days = _days_param(aq.days)
    chart = (
        aq.chart
        if aq.chart in ("bar", "line", "hbar")
        else ("hbar" if group not in ("day", "week", "weekday") else "bar")
    )
    data = compute(request.user, aq.metric, group, days)
    return Response(
        {
            "supported": True,
            "title": aq.title[:120],
            "metric": aq.metric,
            "group_by": group,
            "days": days,
            "chart": chart,
            "data": data,
            "unit": "%" if aq.metric in ("accuracy", "mastery") else "",
            "note": aq.note[:300],
        }
    )
