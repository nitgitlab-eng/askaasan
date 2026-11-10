from collections import defaultdict

from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.learning import activities as acts
from apps.learning.models import Subsection, UserSubsectionState

from .models import MasteryRecord, ReviewCard
from .scheduling import AUTO_GRADED
from .services import review

SESSION_MAX = 20


def _cards(user):
    """Only cards of courses the learner can still open (a cohort window that ended or a lost enrollment hides them)."""
    from apps.learning.access import viewable_curricula

    return ReviewCard.objects.filter(
        user=user, activity__subsection__section__curriculum__in=viewable_curricula(user).values("id")
    )


@api_view(["GET"])
def overview(request):
    now = timezone.now()
    cards = _cards(request.user)
    due = cards.filter(due__lte=now)
    by_course = (
        due.values(
            "activity__subsection__section__curriculum_id", "activity__subsection__section__curriculum__title"
        )
        .annotate(n=Count("id"))
        .order_by("-n")
    )
    next_due = cards.filter(due__gt=now).order_by("due").values_list("due", flat=True).first()
    return Response(
        {
            "due": due.count(),
            "total": cards.count(),
            "next_due_at": next_due,
            "reviewed_today": cards.filter(logs__created_at__date=timezone.localdate()).distinct().count(),
            "by_course": [
                {
                    "curriculum_id": r["activity__subsection__section__curriculum_id"],
                    "title": r["activity__subsection__section__curriculum__title"],
                    "due": r["n"],
                }
                for r in by_course
            ],
        }
    )


def _card_out(card):
    a = card.activity
    return {
        "card_id": card.id,
        "activity": {"id": a.id, "type": a.type, "title": a.title, "payload": a.payload, "attempt": None},
        "lesson": {"id": a.subsection_id, "title": a.subsection.title},
    }


@api_view(["GET"])
def session(request):
    """mode=due (default): cards due now. mode=section|course: checkpoint quiz over
    every auto-graded lesson activity in that scope, regardless of due date."""
    mode = request.query_params.get("mode", "due")
    try:
        limit = max(1, min(int(request.query_params.get("limit") or SESSION_MAX), SESSION_MAX))
    except ValueError:
        return Response({"code": "bad_limit"}, status=status.HTTP_400_BAD_REQUEST)
    for k in ("curriculum", "section"):  # ids go straight into ORM filters
        if not (request.query_params.get(k) or "0").isdigit():
            return Response({"code": "bad_scope"}, status=status.HTTP_400_BAD_REQUEST)
    qs = _cards(request.user).select_related("activity__subsection")
    if cid := request.query_params.get("curriculum"):
        qs = qs.filter(activity__subsection__section__curriculum_id=cid)
    focus = request.query_params.get("focus") or ""
    if mode in ("due", "quick", "exam"):  # exam = Today's timed round: 10 mixed cards, due or not
        pool = qs.filter(due__lte=timezone.now()).order_by("due") if mode == "due" else qs.order_by("?")
        if focus:  # Today's focus theme: only cards whose lesson builds that skill
            from apps.paths.services import match_skills, skill_index

            idx = skill_index()
            pool = [
                c
                for c in pool[:300]
                if focus in match_skills([*c.activity.subsection.skills, c.activity.subsection.title], idx)
            ]
        cards = list(pool[: (5 if mode == "quick" else 10 if mode == "exam" else limit)])
    else:
        scope = {
            "section": "activity__subsection__section_id",
            "course": "activity__subsection__section__curriculum_id",
        }.get(mode)
        target = request.query_params.get(mode if mode == "section" else "curriculum")
        if not scope or not target:
            return Response({"code": "bad_scope"}, status=status.HTTP_400_BAD_REQUEST)
        # Make sure every lesson activity in scope has a card (even if never attempted).
        from apps.learning.access import viewable_q
        from apps.learning.models import Activity

        owned = Activity.objects.filter(
            viewable_q(request.user, "subsection__section__curriculum__"),
            **{scope.replace("activity__", ""): target},
            kind="lesson",
            type__in=AUTO_GRADED,
            subsection__archived=False,
            subsection__section__archived=False,
        ).distinct()
        for a in owned:
            ReviewCard.objects.get_or_create(user=request.user, activity=a)
        live = qs.filter(activity__subsection__archived=False, activity__subsection__section__archived=False)
        cards = list(live.filter(**{scope: target}, activity__kind="lesson").order_by("?")[:limit])
    return Response({"mode": mode, "cards": [_card_out(c) for c in cards]})


@api_view(["POST"])
def answer(request, pk):
    card = get_object_or_404(
        _cards(request.user).select_related("activity__subsection__section__curriculum"), pk=pk
    )
    ans = request.data.get("answer")
    if not isinstance(ans, dict):
        return Response({"code": "bad_answer"}, status=status.HTTP_400_BAD_REQUEST)
    g = acts.grade(card.activity, ans, card.activity.subsection.section.curriculum.language)
    conf = request.data.get("confidence") if request.data.get("confidence") in (1, 2, 3) else None
    rating, due = review(card, g.score, ans, conf)
    from apps.game.services import on_review

    reward = on_review(request.user, card)
    return Response(
        {
            "score": round(g.score, 3),
            "correct": g.correct,
            "feedback": g.feedback,
            "reveal": g.reveal,
            "rating": rating,
            "next_due": due,
            "reward": reward,
        }
    )


def _level(p):
    return "mastered" if p >= 0.85 else "practicing" if p >= 0.5 else "learning" if p > 0.2 else "new"


@api_view(["GET"])
def mastery_graph(request, curriculum_id):
    from apps.learning.access import get_viewable_curriculum

    cur = get_viewable_curriculum(request.user, curriculum_id)
    subs = list(
        Subsection.objects.filter(section__curriculum=cur, archived=False, section__archived=False)
        .select_related("section")
        .order_by("section__order", "order")
    )
    rec = {m.subsection_id: m for m in MasteryRecord.objects.filter(user=request.user, subsection__in=subs)}
    states = {
        s.subsection_id: s.status
        for s in UserSubsectionState.objects.filter(user=request.user, subsection__in=subs)
    }
    due = dict(
        ReviewCard.objects.filter(user=request.user, activity__subsection__in=subs, due__lte=timezone.now())
        .values_list("activity__subsection_id")
        .annotate(n=Count("id"))
    )
    nodes, edges, skill_vals = [], [], defaultdict(list)
    prev = None
    for s in subs:
        p = rec[s.id].p_known if s.id in rec else 0.0
        nodes.append(
            {
                "id": s.id,
                "title": s.title,
                "section_id": s.section_id,
                "section": s.section.title,
                "section_order": s.section.order,
                "mastery": round(p, 3),
                "level": _level(p),
                "state": states.get(s.id, "not_started"),
                "skills": s.skills,
                "due": due.get(s.id, 0),
            }
        )
        for k in s.skills:
            skill_vals[k].append(p)
        if prev:
            edges.append({"from": prev.id, "to": s.id})
        prev = s
    skills = [
        {"name": k, "mastery": round(sum(skill_vals[k]) / len(skill_vals[k]), 3) if skill_vals[k] else 0.0}
        for k in cur.skills
    ]
    overall = round(sum(n["mastery"] for n in nodes) / len(nodes), 3) if nodes else 0.0
    return Response(
        {
            "curriculum": {"id": cur.id, "title": cur.title},
            "overall": overall,
            "nodes": nodes,
            "edges": edges,
            "skills": skills,
        }
    )
