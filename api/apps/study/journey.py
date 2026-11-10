"""Milestone 9 learner features:
- two-host lesson podcasts (cached per lesson + language, like explainer videos) with a warm-up quiz from key points,
- listening progress (≥80% of Listen-mode parts or podcast turns → 'listened' badge; never completes the lesson),
- fast-track ("I already know this"): a short harder check whose attempts are real graded ActivityAttempts,
- the learner's own course order on /learn, plus an AI "suggest an order"."""

import hashlib
import json
import logging
import math
import random
import re

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .jobs import enqueue
from .models import LANGS, CourseOrder, FastTrackRun, ListenProgress, PodcastEpisode

log = logging.getLogger(__name__)
PODCASTS_PER_DAY = 15  # new (uncached) episodes a learner can trigger per day
FAST_TRACKS_PER_DAY = 8
ORDER_SUGGESTIONS_PER_DAY = 10
STALE_AFTER_S = 300
LISTENED_AT = 0.8  # share of parts heard that counts as "listened"


def _lang(request, sub) -> str | None:
    lang = request.query_params.get("lang") or request.data.get("lang") or sub.section.curriculum.language
    return lang if lang in LANGS or lang == "tanglish" else None


# ── Podcast ──────────────────────────────────────────────────────────


def _hash(sub) -> str:
    raw = json.dumps(
        ["pod1", sub.title, sub.objective, sub.explanation_md, sub.key_points],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


WORD = re.compile(r"[^\W\d_][\w'’-]*", re.UNICODE)


def warmup(sub, n: int = 3) -> list[dict]:
    """2–3 quick 'fill the missing word' questions from the lesson's (already visible) key points.
    Never uses activity answer keys, so the answer can travel with the question."""
    sources = [str(k) for k in (sub.key_points or []) if isinstance(k, str) and k.strip()]
    if len(sources) < 2 and sub.objective:
        sources += [s for s in re.split(r"(?<=[.!?])\s+", sub.objective) if s.strip()]
    longest = []
    for s in sources:
        words = [w for w in WORD.findall(s) if len(w) >= 4]
        longest.append(max(words, key=len) if words else "")
    pool = list(dict.fromkeys(w for s in sources + [sub.title] for w in WORD.findall(s) if len(w) >= 4))
    rng = random.Random(sub.id)
    out = []
    for s, word in zip(sources, longest, strict=False):
        if not word:
            continue
        distractors = [
            w for w in pool if w.casefold() != word.casefold() and w.casefold() not in s.casefold()
        ]
        rng.shuffle(distractors)
        options = [word, *distractors[:3]]
        if len(options) < 2:
            continue
        rng.shuffle(options)
        out.append(
            {"prompt": s.replace(word, "_____", 1)[:300], "options": options, "answer": options.index(word)}
        )
        if len(out) >= n:
            break
    return out


def _stuck(ep: PodcastEpisode) -> bool:
    """A 'generating' episode older than STALE_AFTER_S lost its job (worker restart, crash): it may be rebuilt."""
    return ep.status == "generating" and (timezone.now() - ep.updated_at).total_seconds() >= STALE_AFTER_S


def _pod_out(ep: PodcastEpisode | None, sub) -> dict:
    base = {"warmup": warmup(sub)}
    if not ep:
        return {**base, "status": "none"}
    ready = ep.status == "ready"
    return {
        **base,
        "status": ep.status,
        "lang": ep.lang,
        "title": ep.title if ready else "",
        "hosts": ep.hosts if ready else {},
        "turns": ep.turns if ready else [],
        "error": ep.error,
        "updated_at": ep.updated_at.isoformat(),
        "stuck": _stuck(ep),
    }


TURN_MAX = 700  # one spoken turn; longer ones become consecutive turns by the same host
SENTENCE_END = re.compile(r"(?<=[.!?।॥])\s+")


def split_turn(text: str, limit: int = TURN_MAX) -> list[str]:
    """Split a long turn at sentence boundaries into chunks of at most `limit` characters
    (a single over-long sentence is cut at the last space before the limit, else hard at the limit)."""
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []
    out, cur = [], ""
    for s in (x.strip() for x in SENTENCE_END.split(text)):
        while len(s) > limit:
            cut = s.rfind(" ", 0, limit + 1)
            cut = cut if cut > 0 else limit
            if cur:
                out.append(cur)
                cur = ""
            out.append(s[:cut].strip())
            s = s[cut:].strip()
        if not s:
            continue
        if cur and len(cur) + 1 + len(s) > limit:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}" if cur else s
    if cur:
        out.append(cur)
    return out


def build_podcast(ep_id: int) -> None:
    from llm.base import LLMError
    from llm.prompts.curriculum import LANG_RULE
    from llm.prompts.journey import PODCAST_SYSTEM, PodcastScript
    from llm.structured import complete_json_sync

    ep = PodcastEpisode.objects.select_related("subsection__section__curriculum").get(id=ep_id)
    sub = ep.subsection
    try:
        lesson = (
            f"Course: {sub.section.curriculum.title}\nSection: {sub.section.title}\nLesson: {sub.title}\nObjective: {sub.objective}\n\n"
            f"{sub.explanation_md[:9000]}\n\nKey points:\n" + "\n".join(f"- {k}" for k in sub.key_points)
        )
        out = complete_json_sync(
            "author",
            PODCAST_SYSTEM.format(lang_rule=LANG_RULE.get(ep.lang, LANG_RULE["en"])),
            lesson,
            PodcastScript,
            max_tokens=6000,
        )
        turns = [{"speaker": t.speaker, "text": part} for t in out.turns for part in split_turn(t.text)]
        if len(turns) < 4:
            raise ValueError("too_short")
        ep.title, ep.turns = out.title[:200], turns
        ep.hosts = {"A": out.host_a.strip()[:40] or "Meera", "B": out.host_b.strip()[:40] or "Arjun"}
        ep.status, ep.error = "ready", ""
    except LLMError as e:
        log.warning("podcast %s failed: %s", ep_id, e)
        ep.status, ep.error = (
            "failed",
            "provider_not_configured" if e.code == "provider_not_configured" else "generation_failed",
        )
    except Exception as e:  # noqa: BLE001 — any provider/parse failure becomes a retryable "failed"
        log.warning("podcast %s failed: %s", ep_id, e)
        ep.status, ep.error = "failed", "generation_failed"
    ep.save()


@api_view(["GET", "POST"])
def podcast(request, pk):
    """GET → current state + warm-up quiz (poll while 'generating'). POST → create/rebuild (daily allowance)."""
    from apps.learning.access import get_viewable_subsection
    from apps.providers.features import refuse_if_off
    from apps.providers.services import BudgetExceeded, charge

    if off := refuse_if_off("podcast"):
        return off
    sub = get_viewable_subsection(request.user, pk)
    lang = _lang(request, sub)
    if not lang:
        return Response({"code": "bad_lang"}, status=status.HTTP_400_BAD_REQUEST)
    ep = PodcastEpisode.objects.filter(subsection=sub, lang=lang).first()
    h = _hash(sub)
    if request.method == "GET":
        out = _pod_out(ep, sub)
        if ep and ep.status == "ready" and ep.source_hash != h:
            out["outdated"] = True
        return Response(out)
    if sub.lesson_status != "ready":
        return Response({"code": "lesson_not_ready"}, status=status.HTTP_409_CONFLICT)
    with transaction.atomic():
        ep = PodcastEpisode.objects.select_for_update().filter(subsection=sub, lang=lang).first()
        busy = ep and ep.status == "generating" and not _stuck(ep)
        if ep and (busy or ep.status == "ready" and ep.source_hash == h):
            return Response(_pod_out(ep, sub))
        try:
            charge(request.user, "podcasts", 1, PODCASTS_PER_DAY)
        except BudgetExceeded:
            return Response({"code": "podcast_budget"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        if ep:
            ep.status, ep.source_hash, ep.error = "generating", h, ""
            ep.save()
        else:
            ep = PodcastEpisode.objects.create(subsection=sub, lang=lang, source_hash=h)
    transaction.on_commit(lambda: enqueue("apps.study.journey.build_podcast", ep.id))
    return Response(_pod_out(ep, sub), status=status.HTTP_202_ACCEPTED)


# ── Listening progress ───────────────────────────────────────────────


def listen_part_count(md: str, key_points) -> int:
    """Mirror of the web's lessonParts(): heading blocks, else ~3 paragraphs per part; +1 for key points."""
    blocks = [b.strip() for b in re.split(r"\n(?=#{1,4}\s)", md or "") if b.strip()]
    if len(blocks) > 1:
        n = len(blocks)
    else:
        paras = [p for p in re.split(r"\n{2,}", md or "") if p.strip()]
        n = max(1, math.ceil(len(paras) / 3))
    return n + (1 if key_points else 0)


def _listen_total(sub, lang: str) -> int:
    from .models import LessonTranslation

    tr = LessonTranslation.objects.filter(subsection=sub, lang=lang, status="ready").first() if lang else None
    if tr and tr.explanation_md:
        return listen_part_count(tr.explanation_md, tr.key_points or sub.key_points)
    return listen_part_count(sub.explanation_md, sub.key_points)


def _listen_out(lp: ListenProgress | None) -> dict:
    if not lp:
        return {"listened": False, "listen": 0.0, "podcast": 0.0}
    pct = lambda parts, total: round(len(parts) / total, 3) if total else 0.0
    return {
        "listened": bool(lp.listened_at),
        "listen": pct(lp.listen_parts, lp.listen_total),
        "podcast": pct(lp.podcast_parts, lp.podcast_total),
    }


@api_view(["GET", "POST"])
def listened(request, pk):
    """POST {kind: listen|podcast, parts: [index heard to the end, ...], lang?} — totals are computed server-side."""
    from apps.learning.access import get_viewable_subsection

    sub = get_viewable_subsection(request.user, pk)
    lp = ListenProgress.objects.filter(user=request.user, subsection=sub).first()
    if request.method == "GET":
        return Response(_listen_out(lp))
    kind, parts = request.data.get("kind"), request.data.get("parts")
    if kind not in ("listen", "podcast") or not isinstance(parts, list) or len(parts) > 200:
        return Response({"code": "bad_input"}, status=status.HTTP_400_BAD_REQUEST)
    from apps.providers.features import refuse_if_off

    if off := refuse_if_off(kind):  # Listen mode / podcast switched off by the admin
        return off
    lang = str(request.data.get("lang") or "")
    if kind == "podcast":
        ep = PodcastEpisode.objects.filter(
            subsection=sub, lang=lang or sub.section.curriculum.language, status="ready"
        ).first()
        if not ep:
            return Response({"code": "no_podcast"}, status=status.HTTP_409_CONFLICT)
        total = len(ep.turns)
    else:
        total = _listen_total(sub, lang if lang in LANGS else "")
    heard = {p for p in parts if isinstance(p, int) and not isinstance(p, bool) and 0 <= p < total}
    with transaction.atomic():
        lp, _ = ListenProgress.objects.select_for_update().get_or_create(user=request.user, subsection=sub)
        field = f"{kind}_parts"
        if getattr(lp, f"{kind}_total") != total:  # the lesson/episode changed shape: start counting again
            setattr(lp, field, [])
        setattr(lp, field, sorted(set(getattr(lp, field)) | heard))
        setattr(lp, f"{kind}_total", total)
        if not lp.listened_at and total and len(getattr(lp, field)) / total >= LISTENED_AT:
            lp.listened_at = timezone.now()
        lp.save()
    return Response(_listen_out(lp))


@api_view(["GET"])
def course_listened(request, pk):
    """Lesson ids of a course whose explanation I've listened to (🎧 badges on the course map)."""
    from apps.learning.access import get_viewable_curriculum

    cur = get_viewable_curriculum(request.user, pk)
    ids = ListenProgress.objects.filter(
        user=request.user, subsection__section__curriculum=cur, listened_at__isnull=False
    )
    return Response({"lessons": list(ids.values_list("subsection_id", flat=True))})


# ── Fast-track ───────────────────────────────────────────────────────


@api_view(["POST"])
def fast_track(request, pk):
    """Generate a 2–3 question harder check for this lesson. Keys never leave the server."""
    from apps.learning import activities as acts
    from apps.learning.access import get_viewable_subsection
    from apps.learning.models import Activity, UserSubsectionState, next_order
    from apps.providers.services import BudgetExceeded, charge
    from llm.prompts.curriculum import LANG_RULE
    from llm.prompts.journey import FAST_TRACK_SYSTEM, FastTrackSet
    from llm.structured import complete_json_sync

    sub = get_viewable_subsection(request.user, pk)
    if sub.lesson_status != "ready":
        return Response({"code": "lesson_not_ready"}, status=status.HTTP_409_CONFLICT)
    if UserSubsectionState.objects.filter(user=request.user, subsection=sub, status="completed").exists():
        return Response({"code": "already_completed"}, status=status.HTTP_409_CONFLICT)
    lang = _lang(request, sub) or sub.section.curriculum.language
    try:
        charge(request.user, "fast_tracks", 1, FAST_TRACKS_PER_DAY)
    except BudgetExceeded:
        return Response({"code": "fast_track_budget"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    lesson = (
        f"Lesson: {sub.title}\nObjective: {sub.objective}\n\n{sub.explanation_md[:6000]}\n\nKey points:\n"
        + "\n".join(f"- {k}" for k in sub.key_points)
    )
    try:
        out = complete_json_sync(
            "author",
            FAST_TRACK_SYSTEM.format(n=3, lang_rule=LANG_RULE.get(lang, LANG_RULE["en"])),
            lesson,
            FastTrackSet,
            max_tokens=2000,
        )
    except Exception:  # noqa: BLE001
        return Response({"code": "ai_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    qs = [q for q in out.questions if 0 <= q.correct < len(q.options) and q.prompt.strip()][:3]
    if len(qs) < 2:
        return Response({"code": "ai_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    with transaction.atomic():
        _prune_fast_tracks(request.user, sub)
        run = FastTrackRun.objects.create(user=request.user, subsection=sub)
        made = []
        start = next_order(sub.activities)
        for i, q in enumerate(qs):
            spec = {
                "type": "quiz",
                "prompt": q.prompt[:400],
                "options": [o[:200] for o in q.options],
                "correct": [q.correct],
                "explanation": q.explanation[:400],
            }
            payload, key = acts.build(spec, seed=run.id * 10 + i)
            made.append(
                Activity.objects.create(
                    subsection=sub,
                    order=start + i,
                    kind="fasttrack",
                    type="quiz",
                    title=f"Fast-track {i + 1}",
                    payload=payload,
                    key=key,
                    source=spec,
                )
            )
        run.activity_ids = [a.id for a in made]
        run.save(update_fields=["activity_ids"])
    return Response(
        {
            "run_id": run.id,
            "questions": [
                {"id": a.id, "prompt": a.payload["prompt"], "options": a.payload["options"]} for a in made
            ],
        },
        status=status.HTTP_201_CREATED,
    )


FAST_TRACK_KEEP_DAYS = 7


def _prune_fast_tracks(user, sub) -> None:
    """Fast-track questions are throwaway rows on the lesson: drop this learner's unanswered runs for the lesson and
    anyone's runs older than a week that weren't passed (passed runs stay as certificate evidence)."""
    from datetime import timedelta

    from apps.learning.models import Activity

    old = (
        FastTrackRun.objects.filter(subsection=sub)
        .exclude(passed=True)
        .filter(
            Q(user=user, submitted_at__isnull=True)
            | Q(created_at__lt=timezone.now() - timedelta(days=FAST_TRACK_KEEP_DAYS))
        )
    )
    ids = [i for ids in old.values_list("activity_ids", flat=True) for i in (ids or [])]
    Activity.objects.filter(id__in=ids, subsection=sub, kind="fasttrack").delete()
    old.delete()


def _clean_answers(answers) -> dict[str, dict] | None:
    """{activity_id: {selected: [int, ...]}} only — anything else is a 400, never a 500."""
    if not isinstance(answers, dict) or len(answers) > 10:
        return None
    out = {}
    for k, v in answers.items():
        sel = v.get("selected") if isinstance(v, dict) else None
        if (
            not isinstance(sel, list)
            or len(sel) > 10
            or not all(isinstance(x, int) and not isinstance(x, bool) for x in sel)
        ):
            return None
        out[str(k)] = {"selected": sel}
    return out


def _complete(user, sub, score: float) -> dict:
    """The normal completion path (state → COMPLETED, rewards, certificate signal) with the earned score."""
    from apps.game import services as game
    from apps.learning.models import Subsection, UserSubsectionState

    st, _ = UserSubsectionState.objects.get_or_create(user=user, subsection=sub)
    st.status, st.score, st.completed_at = (
        UserSubsectionState.Status.COMPLETED,
        round(score, 3),
        timezone.now(),
    )
    st.started_at = st.started_at or timezone.now()
    st.save()
    nxt = (
        Subsection.objects.filter(
            section__curriculum=sub.section.curriculum, archived=False, section__archived=False
        )
        .filter(Q(section__order__gt=sub.section.order) | Q(section=sub.section, order__gt=sub.order))
        .order_by("section__order", "order")
        .first()
    )
    return {
        "reward": game.on_lesson_complete(user, sub, score),
        "next_subsection_id": nxt.id if nxt else None,
    }


@api_view(["POST"])
def fast_track_submit(request, run_id):
    """{answers: {activity_id: {selected: [i]}}} — all correct → lesson completed with the earned score."""
    from apps.learning import activities as acts
    from apps.learning.models import Activity, ActivityAttempt

    run = get_object_or_404(
        FastTrackRun.objects.select_related("subsection__section__curriculum"), pk=run_id, user=request.user
    )
    from apps.learning.access import get_viewable_subsection

    sub = get_viewable_subsection(request.user, run.subsection_id)  # still allowed to learn this course?
    answers = _clean_answers(request.data.get("answers"))
    if answers is None:
        return Response({"code": "bad_answer"}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        run = FastTrackRun.objects.select_for_update().get(pk=run.pk)
        if run.submitted_at:
            return Response({"code": "already_submitted"}, status=status.HTTP_409_CONFLICT)
        items = list(
            Activity.objects.filter(
                id__in=run.activity_ids, subsection_id=run.subsection_id, kind="fasttrack"
            ).order_by("order")
        )
        if ActivityAttempt.objects.filter(user=request.user, activity__in=items).exists():
            return Response(
                {"code": "already_answered"}, status=status.HTTP_409_CONFLICT
            )  # answered elsewhere first
        results, scores = [], []
        for a in items:
            given = answers.get(str(a.id)) or {"selected": []}
            g = acts.grade(a, given, sub.section.curriculum.language, user=request.user)
            ActivityAttempt.objects.create(
                user=request.user,
                activity=a,
                answer=given,
                score=g.score,
                correct=g.correct,
                feedback=g.feedback,
            )
            scores.append(g.score)
            results.append(
                {
                    "id": a.id,
                    "correct": g.correct,
                    "explanation": g.feedback,
                    "answer": g.reveal.get("correct", []),
                }
            )
        score = sum(scores) / len(scores) if scores else 0.0
        run.passed = bool(scores) and all(r["correct"] for r in results)
        run.score, run.submitted_at = round(score, 3), timezone.now()
        run.save()
    from apps.adaptive import services as adaptive

    for a, sc in zip(items, scores, strict=True):  # first attempts by construction (checked above)
        adaptive.observe(request.user, a, sc)
    out = {"passed": run.passed, "score": run.score, "results": results}
    if run.passed:
        out.update(_complete(request.user, sub, score))
    adaptive.on_progress(
        request.user, sub
    )  # a pass completes the lesson; a fail may turn a skip into a lesson
    return Response(out)


# ── My course order (/learn) ─────────────────────────────────────────


def _learn_courses(user):
    """Same set the /learn library shows: own personal courses + shared ones I enrolled in (not unpublished drafts)."""
    from apps.learning.access import viewable_curricula
    from apps.learning.models import Curriculum

    return viewable_curricula(user).exclude(
        owner=user, kind=Curriculum.Kind.AUTHORED, published_at__isnull=True
    )


def ordered(user, items: list, key=lambda x: x["id"]) -> list:
    """Sort `items` by the learner's saved order; unknown ones keep their current (newest-first) order after the saved ones,
    except brand-new courses, which go first so they're easy to find."""
    co = CourseOrder.objects.filter(user=user).first()
    if not co or not co.ids:
        return items
    pos = {cid: i for i, cid in enumerate(co.ids)}
    return sorted(items, key=lambda x: pos.get(key(x), -1))  # stable: unsaved (new) ones first, newest first


@api_view(["GET", "PUT"])
def course_order(request):
    co = CourseOrder.objects.filter(user=request.user).first()
    if request.method == "GET":
        return Response({"ids": co.ids if co else []})
    ids = request.data.get("ids")
    if (
        not isinstance(ids, list)
        or len(ids) > 200
        or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids)
    ):
        return Response({"code": "bad_input"}, status=status.HTTP_400_BAD_REQUEST)
    mine = set(_learn_courses(request.user).filter(id__in=ids).values_list("id", flat=True))
    if any(i not in mine for i in ids):
        return Response({"code": "not_your_course"}, status=status.HTTP_404_NOT_FOUND)
    clean = list(dict.fromkeys(ids))
    CourseOrder.objects.update_or_create(user=request.user, defaults={"ids": clean})
    return Response({"ids": clean})


@api_view(["POST"])
def course_order_suggest(request):
    """AI proposes an order for my active courses (goals, followed skills, progress). Nothing is saved until accepted."""
    from apps.learning.models import Subsection, UserSubsectionState
    from apps.paths.models import UserSkill
    from apps.providers.services import BudgetExceeded, charge
    from llm.prompts.curriculum import LANG_RULE
    from llm.prompts.journey import ORDER_SYSTEM, OrderSuggestion
    from llm.structured import complete_json_sync

    user = request.user
    rows = []
    for cur in _learn_courses(user).filter(status="ready")[:40]:
        subs = Subsection.objects.filter(section__curriculum=cur, archived=False, section__archived=False)
        total = subs.count()
        done = UserSubsectionState.objects.filter(user=user, subsection__in=subs, status="completed").count()
        if total and done < total:
            rows.append(
                {
                    "id": cur.id,
                    "title": cur.title or cur.goal,
                    "level": cur.level,
                    "skills": cur.skills[:6],
                    "done": done,
                    "total": total,
                }
            )
    if len(rows) < 2:
        return Response({"code": "need_two_courses"}, status=status.HTTP_409_CONFLICT)
    try:
        charge(user, "order_suggestions", 1, ORDER_SUGGESTIONS_PER_DAY)
    except BudgetExceeded:
        return Response({"code": "suggest_budget"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    prof = getattr(user, "profile", None)
    skills = list(
        UserSkill.objects.filter(user=user, followed=True)
        .select_related("skill")
        .values_list("skill__name", flat=True)[:12]
    )
    msg = (
        f"Goals: {', '.join(str(g) for g in (getattr(prof, 'goals', None) or []))[:600]}\nFollowed skills: {', '.join(skills)}\n\nCourses:\n"
        + "\n".join(
            f"- id {r['id']}: {r['title']} ({r['level']}; skills: {', '.join(r['skills'])}; {r['done']}/{r['total']} lessons done)"
            for r in rows
        )
    )
    lang = getattr(prof, "language", "en") or "en"
    try:
        out = complete_json_sync(
            "suggest",
            ORDER_SYSTEM.format(lang_rule=LANG_RULE.get(lang, LANG_RULE["en"])),
            msg,
            OrderSuggestion,
            max_tokens=1500,
        )
    except Exception:  # noqa: BLE001
        return Response({"code": "ai_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    valid = {r["id"]: r for r in rows}
    order = [i for i in dict.fromkeys(out.order) if i in valid]
    order += [r["id"] for r in rows if r["id"] not in order]  # the AI may forget some; never drop a course
    reasons = {r.id: r.reason for r in out.reasons if r.id in valid}
    return Response(
        {
            "order": order,
            "note": out.note,
            "courses": [
                {
                    "id": i,
                    "title": valid[i]["title"],
                    "done": valid[i]["done"],
                    "total": valid[i]["total"],
                    "reason": reasons.get(i, ""),
                }
                for i in order
            ],
        }
    )
