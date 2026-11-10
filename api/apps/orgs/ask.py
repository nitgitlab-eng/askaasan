"""C4 "Ask about my organisation": a plain-language question → ONE query from a fixed catalog → a chart or a table.

Like the learner's "Ask your data" (apps/study/progress.py): the model only picks (metric, group_by, days, chart and an
optional class / assignment id); it never writes a query. The server checks every id against the organisation and the
asker's class scope (a teacher sees only their classes), computes the answer from the organisation's own rows, and
names learners by first name only. The question is fenced, the call is metered against the daily AI budget and
throttled (60/hour)."""

import json
from collections import defaultdict
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from llm.fence import fence

from .models import Membership
from .perms import require

ORG_CATALOG = {  # metric → allowed groupings (first = default)
    "completion": ["assignment", "class"],  # average % of assigned work finished
    "stuck": ["class"],  # learners needing attention: inactive 7+ days, overdue or low scores
    "active": ["day", "week"],  # distinct learners active
    "mastery": ["skill", "class"],  # average mastery on assigned courses (%)
    "overdue": ["assignment", "class"],  # learners past the due date and not finished
    "workshop_pass": ["workshop"],  # % of organisation workshop sessions passed
}
DESCRIPTIONS = {
    "completion": "average % of assigned work finished",
    "stuck": "learners needing attention (inactive 7+ days, overdue or low scores)",
    "active": "distinct learners active",
    "mastery": "average skill mastery on assigned courses, %",
    "overdue": "learners past a due date and not finished",
    "workshop_pass": "% of organisation workshop sessions passed",
}
PERCENT = {"completion", "mastery", "workshop_pass"}
CHARTS = ("bar", "line", "hbar", "table")
MAX_ROWS = 30


class OrgAskThrottle(UserRateThrottle):
    scope, rate = "org_ask", "60/hour"


def _days(raw) -> int:
    try:
        return max(7, min(365, int(raw)))
    except (TypeError, ValueError):
        return 30


class Scope:
    """The learners, classes and assignments this asker may see (optionally narrowed to one class / assignment)."""

    def __init__(self, me, class_id=None, assignment_id=None):
        from .teach import _classes, scope_groups

        self.me, self.org = me, me.org
        allowed = scope_groups(me)  # None = whole organisation
        classes = _classes(self.org)
        if allowed is not None:
            classes = classes.filter(id__in=allowed)
        self.classes = {g.id: g.name for g in classes.order_by("name")}
        assigns = self.org.assignments.select_related("curriculum", "scenario", "group", "survey")
        if allowed is not None:
            from django.db.models import Q

            assigns = assigns.filter(Q(group__isnull=True) | Q(group_id__in=allowed))
        self.assignments = list(assigns[:50])
        self.class_id, self.assignment_id = class_id, assignment_id
        ms = Membership.objects.filter(org=self.org, role="learner").select_related("user__profile")
        if allowed is not None:
            ms = ms.filter(groups__id__in=allowed)
        if class_id:
            ms = ms.filter(groups__id=class_id)
        self.learners = list(ms.prefetch_related("groups").distinct())
        self.uids = {m.user_id for m in self.learners}
        self.class_of = {
            m.user_id: [g.id for g in m.groups.all() if g.id in self.classes] for m in self.learners
        }
        if assignment_id:
            self.assignments = [a for a in self.assignments if a.id == assignment_id]

    def valid(self, class_id, assignment_id) -> bool:
        return (not class_id or class_id in self.classes) and (
            not assignment_id or any(a.id == assignment_id for a in self.assignments)
        )

    def lists(self) -> dict:
        return {
            "classes": [{"id": i, "name": n[:80]} for i, n in self.classes.items()],
            "assignments": [{"id": a.id, "title": _title(a)[:120]} for a in self.assignments],
        }


def _title(a) -> str:
    return (
        a.curriculum.title if a.curriculum_id else a.scenario.title if a.scenario_id else ""
    ) or f"#{a.id}"


def _rows(sc: Scope) -> list[dict]:
    """Per-assignment progress rows for the asker's learners (teacher-scoped by _assignments_out)."""
    from .api import _assignments_out

    out = []
    for a in _assignments_out(sc.org, sc.assignments, me=sc.me, with_rows=True):
        rows = [r for r in a["rows"] if r["user_id"] in sc.uids]
        out.append(
            {"id": a["id"], "title": (a["course"] or a["scenario"] or {}).get("title", ""), "rows": rows}
        )
    return out


def _by_class(sc: Scope, per_user: dict, agg="avg") -> list[dict]:
    vals = defaultdict(list)
    for uid, v in per_user.items():
        for cid in sc.class_of.get(uid, []):
            vals[cid].append(v)
    out = []
    for cid, name in sc.classes.items():
        if sc.class_id and cid != sc.class_id:
            continue
        v = vals.get(cid, [])
        value = (round(sum(v) / len(v)) if v else 0) if agg == "avg" else sum(v)
        out.append({"label": name, "value": value})
    return out


def _stuck(sc: Scope) -> dict[int, list[str]]:
    from apps.game.models import XPEvent

    today = timezone.localdate()
    recent = set(
        XPEvent.objects.filter(user_id__in=sc.uids, day__gt=today - timedelta(days=7)).values_list(
            "user_id", flat=True
        )
    )
    reasons = defaultdict(list)
    for uid in sc.uids:
        if uid not in recent:
            reasons[uid].append("inactive")
    for a in _rows(sc):
        for r in a["rows"]:
            if r["overdue"] and "overdue" not in reasons[r["user_id"]]:
                reasons[r["user_id"]].append("overdue")
            if (
                r["avg_score"] is not None
                and r["avg_score"] < 0.5
                and "low_scores" not in reasons[r["user_id"]]
            ):
                reasons[r["user_id"]].append("low_scores")
    return {u: v for u, v in reasons.items() if v}


def compute(sc: Scope, metric: str, group: str, days: int) -> tuple[list[dict], dict | None]:
    """→ (chart data [{label, value}], table {columns, rows} or None). First names only."""
    from .api import _first

    names = {m.user_id: _first(m.user) for m in sc.learners}
    table = None
    if metric in ("completion", "overdue"):
        rows = _rows(sc)
        if group == "assignment":
            data = []
            for a in rows:
                rs = a["rows"]
                if metric == "completion":
                    v = round(100 * sum(r["pct"] for r in rs) / len(rs)) if rs else 0
                else:
                    v = sum(1 for r in rs if r["overdue"])
                data.append({"label": a["title"], "value": v})
        else:
            per_user = defaultdict(list)
            for a in rows:
                for r in a["rows"]:
                    per_user[r["user_id"]].append(r["pct"] if metric == "completion" else int(r["overdue"]))
            if metric == "completion":
                data = _by_class(sc, {u: 100 * sum(v) / len(v) for u, v in per_user.items() if v})
            else:
                data = _by_class(sc, {u: int(any(v)) for u, v in per_user.items()}, agg="sum")
        if metric == "overdue":
            late = sorted(
                {(names.get(r["user_id"], ""), a["title"]) for a in rows for r in a["rows"] if r["overdue"]}
            )
            table = {"columns": ["learner", "assignment"], "rows": [list(x) for x in late[:MAX_ROWS]]}
    elif metric == "stuck":
        stuck = _stuck(sc)
        data = _by_class(sc, {u: 1 for u in stuck}, agg="sum")
        table = {
            "columns": ["learner", "class", "reasons"],
            "rows": [
                [
                    names.get(u, ""),
                    ", ".join(sc.classes[c] for c in sc.class_of.get(u, [])),
                    ", ".join(r),
                ]
                for u, r in sorted(stuck.items(), key=lambda x: names.get(x[0], ""))
            ][:MAX_ROWS],
        }
    elif metric == "active":
        from apps.game.models import XPEvent

        today = timezone.localdate()
        since = today - timedelta(days=days - 1)
        per_day = defaultdict(set)
        for uid, d in XPEvent.objects.filter(user_id__in=sc.uids, day__gte=since).values_list(
            "user_id", "day"
        ):
            key = d - timedelta(days=d.weekday()) if group == "week" else d
            per_day[key].add(uid)
        data, d = [], since - timedelta(days=since.weekday()) if group == "week" else since
        while d <= today:
            data.append({"label": d.isoformat(), "value": len(per_day.get(d, ()))})
            d += timedelta(days=7 if group == "week" else 1)
    elif metric == "mastery":
        from apps.learning.models import Subsection
        from apps.review.models import MasteryRecord

        cids = {a.curriculum_id for a in sc.assignments if a.curriculum_id}
        subs = Subsection.objects.filter(section__curriculum_id__in=cids)
        recs = MasteryRecord.objects.filter(user_id__in=sc.uids, subsection__in=subs).select_related(
            "subsection"
        )
        if group == "skill":
            vals = defaultdict(list)
            for rec in recs:
                for k in rec.subsection.skills or []:
                    vals[k].append(rec.p_known)
            data = sorted(
                ({"label": k, "value": round(100 * sum(v) / len(v))} for k, v in vals.items()),
                key=lambda r: r["value"],
            )[:15]
        else:
            per_user = defaultdict(list)
            for rec in recs:
                per_user[rec.user_id].append(rec.p_known)
            data = _by_class(sc, {u: 100 * sum(v) / len(v) for u, v in per_user.items()})
    else:  # workshop_pass
        from apps.workshops.models import WorkshopSession

        since = timezone.now() - timedelta(days=days)
        tally = defaultdict(lambda: [0, 0])
        for title, passed in WorkshopSession.objects.filter(
            run__org=sc.org, user_id__in=sc.uids, started_at__gte=since
        ).values_list("run__workshop__title", "passed"):
            tally[title][0] += int(passed)
            tally[title][1] += 1
        data = [{"label": t, "value": round(100 * p / n)} for t, (p, n) in sorted(tally.items()) if n]
    return data, table


@api_view(["POST"])
@throttle_classes([OrgAskThrottle])
def ask(request, slug):
    from apps.learning.services import content_language
    from llm.base import LLMError
    from llm.prompts.curriculum import LANG_RULE
    from llm.prompts.orgs import ORG_ASK_SYSTEM, OrgAskQuery
    from llm.structured import complete_json_sync

    from .surveys import _ai_guard

    me = require(request.user, slug, "manager")
    q = str(request.data.get("question") or "").strip()
    if not 3 <= len(q) <= 300:
        return Response({"code": "bad_question"}, status=status.HTTP_400_BAD_REQUEST)
    if refused := _ai_guard(request, max_tokens=600):
        return refused
    scope = Scope(me)
    lang = content_language(request.user)
    metrics = "\n".join(f"- {m} [{', '.join(g)}]: {DESCRIPTIONS[m]}" for m, g in ORG_CATALOG.items())
    try:
        aq = complete_json_sync(
            "org_ask",
            ORG_ASK_SYSTEM.format(metrics=metrics, lang_rule=LANG_RULE.get(lang, LANG_RULE["en"])),
            f"Today is {timezone.localdate()}.\n"
            f"{fence('org_data', json.dumps(scope.lists(), ensure_ascii=False))}\n{fence('question', q)}",
            OrgAskQuery,
            max_tokens=600,
        )
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if not aq.supported or aq.metric not in ORG_CATALOG:
        return Response({"supported": False, "note": aq.note[:300]})
    if not scope.valid(aq.class_id, aq.assignment_id):
        # an id outside this organisation or outside the teacher's classes: never computed, never echoed
        return Response({"code": "bad_scope"}, status=status.HTTP_400_BAD_REQUEST)
    group = aq.group_by if aq.group_by in ORG_CATALOG[aq.metric] else ORG_CATALOG[aq.metric][0]
    days = _days(aq.days)
    chart = aq.chart if aq.chart in CHARTS else ("line" if group in ("day", "week") else "hbar")
    if aq.class_id or aq.assignment_id:
        scope = Scope(me, aq.class_id, aq.assignment_id)
    data, table = compute(scope, aq.metric, group, days)
    if chart == "table" and table is None:
        table = {"columns": [group, aq.metric], "rows": [[r["label"], r["value"]] for r in data]}
    return Response(
        {
            "supported": True,
            "title": aq.title[:120],
            "metric": aq.metric,
            "group_by": group,
            "days": days,
            "chart": chart,
            "data": data,
            "unit": "%" if aq.metric in PERCENT else "",
            "table": table,
            "class": scope.classes.get(aq.class_id) if aq.class_id else None,
            "note": aq.note[:300],
        }
    )
