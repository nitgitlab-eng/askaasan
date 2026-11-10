"""AI explainer videos: a narrated, scene-by-scene script per (lesson, language), cached and shared by every learner."""

import hashlib
import json
import logging

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .jobs import enqueue
from .models import LANGS, ExplainerVideo

log = logging.getLogger(__name__)
EXPLAINERS_PER_DAY = 20  # new (uncached) explainers a learner can trigger per day
STALE_AFTER_S = 300


def _hash(sub) -> str:
    raw = json.dumps(
        [1, sub.title, sub.objective, sub.explanation_md, sub.key_points], ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _out(ev: ExplainerVideo | None) -> dict:
    if not ev:
        return {"status": "none"}
    return {
        "status": ev.status,
        "lang": ev.lang,
        "title": ev.title,
        "scenes": ev.scenes if ev.status == "ready" else [],
        "transcript": "\n\n".join(s["narration"] for s in ev.scenes) if ev.status == "ready" else "",
        "error": ev.error,
    }


def build(ev_id: int) -> None:
    from llm.prompts.curriculum import LANG_RULE
    from llm.prompts.study import EXPLAINER_SYSTEM, ExplainerScript
    from llm.structured import complete_json_sync

    ev = ExplainerVideo.objects.select_related("subsection__section__curriculum").get(id=ev_id)
    sub = ev.subsection
    try:
        lesson = (
            f"Course: {sub.section.curriculum.title}\nSection: {sub.section.title}\nLesson: {sub.title}\nObjective: {sub.objective}\n\n"
            f"{sub.explanation_md[:9000]}\n\nKey points:\n" + "\n".join(f"- {k}" for k in sub.key_points)
        )
        out = complete_json_sync(
            "author",
            EXPLAINER_SYSTEM.format(lang_rule=LANG_RULE.get(ev.lang, LANG_RULE["en"])),
            lesson,
            ExplainerScript,
            max_tokens=5000,
        )
        ev.title = out.title[:200]
        ev.scenes = [s.model_dump() for s in out.scenes]
        ev.status, ev.error = ExplainerVideo.Status.READY, ""
    except Exception as e:  # noqa: BLE001 — any provider/parse failure becomes a retryable "failed"
        log.warning("explainer %s failed: %s", ev_id, e)
        ev.status, ev.error = ExplainerVideo.Status.FAILED, "generation_failed"
    ev.save()


@api_view(["GET", "POST"])
def explainer(request, pk):
    """GET → current state (poll while 'generating'). POST → create/rebuild (counts against a daily allowance)."""
    from apps.learning.access import get_viewable_subsection
    from apps.providers.features import refuse_if_off
    from apps.providers.services import BudgetExceeded, charge

    if off := refuse_if_off("explainer"):
        return off
    sub = get_viewable_subsection(request.user, pk)
    lang = request.query_params.get("lang") or request.data.get("lang") or sub.section.curriculum.language
    if lang not in LANGS and lang != "tanglish":
        return Response({"code": "bad_lang"}, status=status.HTTP_400_BAD_REQUEST)
    ev = ExplainerVideo.objects.filter(subsection=sub, lang=lang).first()
    h = _hash(sub)
    if request.method == "GET":
        if ev and ev.status == "ready" and ev.source_hash != h:
            return Response({**_out(ev), "outdated": True})
        return Response(_out(ev))
    if sub.lesson_status != "ready":
        return Response({"code": "lesson_not_ready"}, status=status.HTTP_409_CONFLICT)
    with transaction.atomic():
        ev = ExplainerVideo.objects.select_for_update().filter(subsection=sub, lang=lang).first()
        busy = (
            ev
            and ev.status == "generating"
            and (timezone.now() - ev.updated_at).total_seconds() < STALE_AFTER_S
        )
        if ev and (busy or ev.status == "ready" and ev.source_hash == h):
            return Response(_out(ev))
        try:
            charge(request.user, "explainers", 1, EXPLAINERS_PER_DAY)
        except BudgetExceeded:
            return Response({"code": "explainer_budget"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        if ev:
            ev.status, ev.source_hash, ev.error = ExplainerVideo.Status.GENERATING, h, ""
            ev.save()
        else:
            ev = ExplainerVideo.objects.create(subsection=sub, lang=lang, source_hash=h)
    transaction.on_commit(lambda: enqueue("apps.study.explainer.build", ev.id))
    return Response(_out(ev), status=status.HTTP_202_ACCEPTED)
