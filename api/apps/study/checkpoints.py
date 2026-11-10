"""Pre/post course tests (learning gain) and "My checkpoints"."""

import logging

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .jobs import enqueue
from .models import CheckpointAttempt, CourseCheckpoint

log = logging.getLogger(__name__)
N_QUESTIONS = 8
STALE_AFTER_S = 300


def build(cp_id: int) -> None:
    from llm.prompts.curriculum import LANG_RULE
    from llm.prompts.study import CHECKPOINT_SYSTEM, CheckpointSet
    from llm.structured import complete_json_sync

    cp = CourseCheckpoint.objects.select_related("curriculum").get(id=cp_id)
    cur = cp.curriculum
    outline = "\n".join(
        f"## {s.title}\n"
        + "\n".join(f"- {b.title}: {b.objective}" for b in s.subsections.filter(archived=False))
        for s in cur.sections.filter(archived=False)
    )
    try:
        out = complete_json_sync(
            "author",
            CHECKPOINT_SYSTEM.format(n=N_QUESTIONS, lang_rule=LANG_RULE.get(cur.language, LANG_RULE["en"])),
            f"Course: {cur.title}\nGoal: {cur.goal}\nLevel: {cur.level}\n\n{outline[:8000]}",
            CheckpointSet,
            max_tokens=5000,
        )
        items = []
        for i, q in enumerate(out.items):
            if q.correct < len(q.options):
                items.append(
                    {
                        "id": f"q{i}",
                        "prompt": q.prompt,
                        "options": q.options,
                        "correct": [q.correct],
                        "explanation": q.explanation,
                        "lesson": q.lesson,
                    }
                )
        cp.items, cp.status = items, "ready" if len(items) >= 4 else "failed"
    except Exception as e:  # noqa: BLE001
        log.warning("checkpoint %s failed: %s", cp_id, e)
        cp.status = "failed"
    cp.save()


def _public(items):
    return [
        {"id": q["id"], "prompt": q["prompt"], "options": q["options"], "lesson": q.get("lesson", "")}
        for q in items
    ]


def _attempt_out(a: CheckpointAttempt | None):
    return {"score": a.score, "correct": a.correct, "total": a.total, "at": a.created_at} if a else None


def summary(user, cur) -> dict:
    pre = (
        CheckpointAttempt.objects.filter(user=user, curriculum=cur, kind="pre").order_by("created_at").first()
    )
    post = (
        CheckpointAttempt.objects.filter(user=user, curriculum=cur, kind="post")
        .order_by("-created_at")
        .first()
    )
    return {
        "pre": _attempt_out(pre),
        "post": _attempt_out(post),
        "gain": round(post.score - pre.score, 3) if pre and post else None,
    }


@api_view(["GET", "POST"])
def checkpoint(request, pk):
    """GET: questions (no answers) + my pre/post results. POST: prepare the question set (once per course)."""
    from apps.learning.access import get_viewable_curriculum
    from apps.providers.services import BudgetExceeded, charge

    cur = get_viewable_curriculum(request.user, pk)
    cp = CourseCheckpoint.objects.filter(curriculum=cur).first()
    if request.method == "POST" and cur.status == "ready":
        with transaction.atomic():
            cp = CourseCheckpoint.objects.select_for_update().filter(curriculum=cur).first()
            stale = (
                cp
                and cp.status == "generating"
                and (timezone.now() - cp.updated_at).total_seconds() > STALE_AFTER_S
            )
            if not cp or cp.status == "failed" or stale:
                try:
                    charge(request.user, "checkpoints", 1, 10)
                except BudgetExceeded:
                    return Response({"code": "checkpoint_budget"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
                if cp:
                    cp.status = "generating"
                    cp.save()
                else:
                    cp = CourseCheckpoint.objects.create(curriculum=cur)
                transaction.on_commit(lambda: enqueue("apps.study.checkpoints.build", cp.id))
    return Response(
        {
            "status": cp.status if cp else "none",
            "questions": _public(cp.items) if cp and cp.status == "ready" else [],
            **summary(request.user, cur),
        }
    )


@api_view(["POST"])
def checkpoint_submit(request, pk):
    from apps.learning.access import get_viewable_curriculum

    cur = get_viewable_curriculum(request.user, pk)
    cp = CourseCheckpoint.objects.filter(curriculum=cur, status="ready").first()
    kind = request.data.get("kind")
    if not cp or kind not in ("pre", "post"):
        return Response({"code": "not_ready"}, status=status.HTTP_409_CONFLICT)
    mine = CheckpointAttempt.objects.filter(user=request.user, curriculum=cur)
    if kind == "pre" and mine.filter(kind="pre").exists():
        return Response({"code": "pre_done"}, status=status.HTTP_409_CONFLICT)  # the baseline is taken once
    if (
        kind == "post"
        and mine.filter(kind="post", created_at__gte=timezone.now() - timezone.timedelta(hours=1)).exists()
    ):
        return Response({"code": "try_later"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    answers = request.data.get("answers") if isinstance(request.data.get("answers"), dict) else {}
    conf = request.data.get("confidence") if isinstance(request.data.get("confidence"), dict) else {}
    review, correct = [], 0
    for q in cp.items:
        a = answers.get(q["id"])
        picked = (
            [a] if isinstance(a, int) else [x for x in a if isinstance(x, int)] if isinstance(a, list) else []
        )
        ok = sorted(picked) == sorted(q["correct"])
        correct += ok
        row = {
            "id": q["id"],
            "picked": picked,
            "ok": ok,
            "confidence": conf.get(q["id"]) if conf.get(q["id"]) in (1, 2, 3) else None,
        }
        if kind == "post":  # the post-test reuses these items, so the pre-test never reveals the key
            row.update(correct=q["correct"], explanation=q["explanation"])
        review.append(row)
    CheckpointAttempt.objects.create(
        user=request.user,
        curriculum=cur,
        kind=kind,
        correct=correct,
        total=len(cp.items),
        answers={k: v for k, v in answers.items() if k.startswith("q")},
        confidence={k: v for k, v in conf.items() if v in (1, 2, 3)},
    )
    from apps.adaptive.services import on_checkpoint

    on_checkpoint(request.user, cur, kind, cp.items, review)  # the pre-test is the adaptive diagnostic
    return Response({"review": review, **summary(request.user, cur)}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def my_checkpoints(request):
    from apps.learning.models import Curriculum

    ids = (
        CheckpointAttempt.objects.filter(user=request.user).values_list("curriculum_id", flat=True).distinct()
    )
    rows = [
        {
            "course": {"id": c.id, "title": c.title or c.goal, "emoji": c.cover_emoji},
            **summary(request.user, c),
        }
        for c in Curriculum.objects.filter(id__in=ids)
    ]
    return Response(sorted(rows, key=lambda r: (r["post"] or r["pre"] or {}).get("at") or 0, reverse=True))
