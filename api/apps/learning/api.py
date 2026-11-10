from datetime import timedelta

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.game import services as game
from apps.review.services import record_attempt

from . import activities as acts
from .access import (
    get_viewable_activity,
    get_viewable_curriculum,
    get_viewable_subsection,
    is_owner,
    viewable_curricula,
)
from .jobs import enqueue
from .models import Activity, ActivityAttempt, Curriculum, Subsection, UserSubsectionState
from .services import content_language


class CreateCurriculum(serializers.Serializer):
    goal = serializers.CharField(max_length=300, required=False)
    goal_id = serializers.IntegerField(required=False)  # an adaptive LearningGoal (topic → chosen scenario)
    level = serializers.ChoiceField(choices=["beginner", "intermediate", "advanced"], default="beginner")
    domain = serializers.CharField(max_length=64, required=False, allow_blank=True)
    notes = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    document_id = serializers.IntegerField(required=False)
    # Course options (all optional): how it sounds, how long each sitting is, what kind of learning to lean on.
    tone = serializers.ChoiceField(choices=["friendly", "formal", "playful", "exam"], required=False)
    session_minutes = serializers.ChoiceField(choices=[5, 10, 20], required=False)
    styles = serializers.MultipleChoiceField(
        choices=["explanations", "exercises", "examples", "video", "roleplay"], required=False
    )

    def validate(self, attrs):
        if not attrs.get("goal") and not attrs.get("goal_id"):
            raise serializers.ValidationError({"goal": ["This field is required."]})
        return attrs


STALE_AFTER = timedelta(minutes=8)


def _expire_stale(user):
    """Jobs that died with the process (crash/restart) must not block the learner."""
    Curriculum.objects.filter(
        owner=user, status=Curriculum.Status.GENERATING, updated_at__lt=timezone.now() - STALE_AFTER
    ).update(status=Curriculum.Status.FAILED, error="timed_out")


def _states(user, subsection_ids):
    return {
        s.subsection_id: s
        for s in UserSubsectionState.objects.filter(user=user, subsection_id__in=subsection_ids)
    }


def _curriculum_summary(cur, user):
    subs = Subsection.objects.filter(section__curriculum=cur, archived=False, section__archived=False)
    total = subs.count()
    done = UserSubsectionState.objects.filter(
        user=user, subsection__in=subs, status=UserSubsectionState.Status.COMPLETED
    ).count()
    return {
        "id": cur.id,
        "title": cur.title or cur.goal,
        "goal": cur.goal,
        "description": cur.description,
        "level": cur.level,
        "language": cur.language,
        "skills": cur.skills,
        "status": cur.status,
        "error": cur.error,
        "source_document": {"id": cur.source_document_id, "title": cur.source_document.title}
        if cur.source_document_id
        else None,
        "kind": cur.kind,
        "cover_emoji": cur.cover_emoji,
        "is_owner": cur.owner_id == user.id,
        "creator": (cur.owner.profile.display_name or "").split(" ")[0] if cur.kind == "authored" else None,
        "progress": {"done": done, "total": total},
        "updated_at": cur.updated_at,
        "options": {
            k: v
            for k, v in ((cur.authoring or {}).get("preset") or {}).items()
            if k in ("tone", "session_minutes", "styles")
        },
    }


@api_view(["GET", "POST"])
def curriculums(request):
    _expire_stale(request.user)
    if request.method == "POST":
        ser = CreateCurriculum(data=request.data)
        ser.is_valid(raise_exception=True)
        if Curriculum.objects.filter(owner=request.user, status=Curriculum.Status.GENERATING).count() >= 2:
            return Response({"code": "too_many_generating"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        from apps.billing.services import PlanLimit, consume

        data = dict(ser.validated_data)
        learning_goal = None
        if goal_id := data.pop("goal_id", None):
            from apps.adaptive.api import course_fields
            from apps.adaptive.models import LearningGoal

            learning_goal = LearningGoal.objects.filter(
                pk=goal_id,
                user=request.user,
                status__in=[LearningGoal.Status.CHOSEN, LearningGoal.Status.READY],
            ).first()
            if not learning_goal:
                return Response({"code": "goal_not_ready"}, status=status.HTTP_409_CONFLICT)
            data = {**data, **course_fields(learning_goal)}
        opts = {k: data.pop(k) for k in ("tone", "session_minutes", "styles") if k in data}
        if "styles" in opts:
            opts["styles"] = sorted(opts["styles"])
        doc = None
        if doc_id := data.pop("document_id", None):
            from apps.orgs.extras import viewable_documents

            # Same rule as the mentor: own notes + what the user's orgs currently let them read (an ex-admin who still
            # "owns" a school knowledge-base upload gets nothing through that ownership).
            doc = viewable_documents(request.user).filter(id=doc_id).first()
            if not doc:
                return Response({"code": "document_not_found"}, status=status.HTTP_404_NOT_FOUND)
        try:  # after the document lookup, so a 404 doesn't use up a course
            consume(request.user, "ai_courses_per_month", "ai_course")
        except PlanLimit as e:
            return Response(e.payload(), status=status.HTTP_402_PAYMENT_REQUIRED)
        cur = Curriculum.objects.create(
            owner=request.user,
            language=content_language(request.user),
            source_document=doc,
            domain=data.pop("domain", "") or request.user.profile.domain,
            authoring={"preset": opts} if opts else {},
            **data,
        )
        if learning_goal:
            learning_goal.curriculum, learning_goal.status = cur, learning_goal.Status.USED
            learning_goal.save(update_fields=["curriculum", "status", "updated_at"])
        enqueue("generate_outline", cur.id)
        return Response(_curriculum_summary(cur, request.user), status=status.HTTP_202_ACCEPTED)
    # My personal courses + shared courses I enrolled in (authored drafts live in the Lab).
    mine = viewable_curricula(request.user).exclude(
        owner=request.user, kind=Curriculum.Kind.AUTHORED, published_at__isnull=True
    )
    from apps.study.journey import ordered  # the learner's own order (drag to reorder on /learn)

    return Response(ordered(request.user, [_curriculum_summary(c, request.user) for c in mine[:50]]))


@api_view(["GET", "DELETE"])
def curriculum_detail(request, pk):
    _expire_stale(request.user)
    cur = get_viewable_curriculum(request.user, pk)
    if request.method == "DELETE":
        if is_owner(request.user, cur):
            cur.delete()
        else:  # a learner leaving a shared course; their progress rows go with the enrollment
            cur.enrollments.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    sections = [s for s in cur.sections.prefetch_related("subsections") if not s.archived]
    sub_ids = [b.id for s in sections for b in s.subsections.all() if not b.archived]
    states = _states(request.user, sub_ids)
    # Lesson activity counts by type, for the course map's cards (one query; practice items aren't counted).
    kinds = {}
    for row in (
        Activity.objects.filter(subsection_id__in=sub_ids, kind="lesson")
        .values("subsection_id", "type")
        .annotate(n=Count("id"))
        .order_by("-n", "type")
    ):
        kinds.setdefault(row["subsection_id"], {})[row["type"]] = row["n"]
    prev_done = True
    out_sections = []
    for s in sections:
        subs = []
        for b in s.subsections.all():
            if b.archived:
                continue
            st = states.get(b.id)
            state = st.status if st else "not_started"
            subs.append(
                {
                    "id": b.id,
                    "title": b.title,
                    "objective": b.objective,
                    "lesson_status": b.lesson_status,
                    "state": state,
                    "score": st.score if st else None,
                    "skills": b.skills,
                    "activity_count": sum(kinds.get(b.id, {}).values()),
                    "activity_types": list(kinds.get(b.id, {}))[:4],
                    # Rough: a couple of minutes reading plus ~2 per activity. Unknown until the lesson is generated.
                    "minutes": 2 + 2 * sum(kinds[b.id].values()) if b.id in kinds else None,
                    # Quest-path unlocking: a lesson opens once the previous one is done.
                    "locked": not prev_done and state == "not_started",
                }
            )
            prev_done = state == "completed"
        out_sections.append({"id": s.id, "title": s.title, "summary": s.summary, "subsections": subs})
    from apps.adaptive.models import LearnerPath

    adaptive = LearnerPath.objects.filter(user=request.user, curriculum=cur).exists()
    return Response(
        {**_curriculum_summary(cur, request.user), "sections": out_sections, "adaptive": adaptive}
    )


@api_view(["POST"])
def curriculum_reset(request, pk):
    """Start a course over: clears *my* progress, answers, reviews and mastery for it (the course itself is untouched)."""
    from django.db import transaction

    from apps.review.models import MasteryRecord, ReviewCard

    cur = get_viewable_curriculum(request.user, pk)
    with transaction.atomic():
        n = UserSubsectionState.objects.filter(
            user=request.user, subsection__section__curriculum=cur
        ).delete()[0]
        ActivityAttempt.objects.filter(
            user=request.user, activity__subsection__section__curriculum=cur
        ).delete()
        ReviewCard.objects.filter(user=request.user, activity__subsection__section__curriculum=cur).delete()
        MasteryRecord.objects.filter(user=request.user, subsection__section__curriculum=cur).delete()
    return Response({"reset": True, "lessons": n})


@api_view(["POST"])
def curriculum_retry(request, pk):
    cur = get_object_or_404(Curriculum, pk=pk, owner=request.user, status=Curriculum.Status.FAILED)
    cur.status, cur.error = Curriculum.Status.GENERATING, ""
    cur.save(update_fields=["status", "error"])
    enqueue("generate_outline", cur.id)
    return Response(_curriculum_summary(cur, request.user), status=status.HTTP_202_ACCEPTED)


LESSON_STALE_AFTER = timedelta(minutes=5)


def _own_subsection(request, pk):
    sub = get_viewable_subsection(request.user, pk)
    # A job killed mid-flight (deploy, crash, dev reload) must not leave the learner waiting forever.
    if sub.generating_since and timezone.now() - sub.generating_since > LESSON_STALE_AFTER:
        changed = {}
        if sub.lesson_status == Subsection.LessonStatus.GENERATING:
            changed.update(lesson_status=Subsection.LessonStatus.FAILED, error="timed_out")
        if sub.practice_status == "generating":
            changed["practice_status"] = "failed"
        if changed:
            Subsection.objects.filter(pk=sub.pk).update(generating_since=None, **changed)
            sub.refresh_from_db()
    return sub


def _lesson(sub, user):
    latest = {}
    for a in ActivityAttempt.objects.filter(user=user, activity__subsection=sub).order_by("created_at"):
        latest[a.activity_id] = a
    acts_out = []
    for a in sub.activities.filter(kind="lesson"):
        att = latest.get(a.id)
        acts_out.append(
            {
                "id": a.id,
                "type": a.type,
                "title": a.title,
                "payload": a.payload,
                "attempt": {
                    "score": att.score,
                    "correct": att.correct,
                    "feedback": att.feedback,
                    "answer": att.answer,
                }
                if att
                else None,
            }
        )
    st = UserSubsectionState.objects.filter(user=user, subsection=sub).first()
    cur = sub.section.curriculum
    return {
        "id": sub.id,
        "title": sub.title,
        "objective": sub.objective,
        "lesson_status": sub.lesson_status,
        "error": sub.error,
        "explanation_md": sub.explanation_md,
        "key_points": sub.key_points,
        "activities": acts_out,
        "state": st.status if st else "not_started",
        "curriculum": {"id": cur.id, "title": cur.title, "language": cur.language},
        "section": {"id": sub.section_id, "title": sub.section.title},
    }


@api_view(["GET"])
def subsection_detail(request, pk):
    sub = _own_subsection(request, pk)
    return Response(_localized(_lesson(sub, request.user), sub, request))


def _localized(lesson: dict, sub, request) -> dict:
    """?lang=xx → overlay a cached translation (started on first request; client polls while 'translating')."""
    from apps.study.models import LANGS
    from apps.study.translation import ensure, overlay

    lang = request.query_params.get("lang") or ""
    lesson["translation"] = {
        "lang": "",
        "status": "",
        "available": list(LANGS),
        "source": sub.section.curriculum.language,
    }
    if not lang or lang not in LANGS:
        return lesson
    tr = ensure(sub, lang, request.user)
    if tr is None:
        return lesson
    lesson["translation"].update(lang=lang, status=tr.status)
    return overlay(lesson, tr) if tr.status == "ready" else lesson


@api_view(["POST"])
def subsection_start(request, pk):
    sub = _own_subsection(request, pk)
    if sub.lesson_status in (Subsection.LessonStatus.EMPTY, Subsection.LessonStatus.FAILED):
        if not is_owner(request.user, sub.section.curriculum):
            # Learners on a shared course never trigger (paid) generation; creators publish ready lessons.
            return Response({"code": "lesson_not_ready"}, status=status.HTTP_409_CONFLICT)
        Subsection.objects.filter(pk=sub.pk).update(
            lesson_status=Subsection.LessonStatus.GENERATING, error="", generating_since=timezone.now()
        )
        enqueue("generate_lesson", sub.id)
        sub.refresh_from_db()
    st, _ = UserSubsectionState.objects.get_or_create(user=request.user, subsection=sub)
    if st.status == UserSubsectionState.Status.NOT_STARTED:
        st.status, st.started_at = UserSubsectionState.Status.IN_PROGRESS, timezone.now()
        st.save()
    return Response(_localized(_lesson(sub, request.user), sub, request))


AI_GRADED_TYPES = {"open_input", "code", "task", "browser_task"}
AI_GRADES_PER_DAY = 200  # AI-marked answers per learner per day (cost guard; generous for real study)
PRACTICE_SETS_PER_DAY = 20  # fresh AI practice sets per learner per day (each is one AI generation)
ARTIFACT_CHECKS_PER_HOUR = 10  # live page fetches per learner per hour (we fetch learner-supplied URLs)


def _artifact_check_allowed(user) -> bool:
    """Reserve one live-page fetch BEFORE fetching (atomic row lock), so parallel requests can't slip past the cap.
    Window = the current clock hour (the usage row is per day + metric)."""
    from apps.providers.services import BudgetExceeded, charge

    try:
        charge(user, f"artifact_checks_h{timezone.localtime().hour:02d}", 1, ARTIFACT_CHECKS_PER_HOUR)
    except BudgetExceeded:
        return False
    return True


@api_view(["POST"])
def activity_attempt(request, pk):
    activity = get_viewable_activity(request.user, pk)
    answer = request.data.get("answer")
    if not isinstance(answer, dict):
        return Response({"code": "bad_answer"}, status=status.HTTP_400_BAD_REQUEST)
    lang = activity.subsection.section.curriculum.language
    if activity.type == "artifact_check" and not _artifact_check_allowed(request.user):
        return Response({"code": "artifact_check_rate_limited"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    if activity.type == "browser_task":
        from apps.extension.api import _optional_for, _steps_for

        # Same rule as the extension's submit: the web path carries no watched-steps evidence, so a task whose
        # author requires observed steps can only be completed from the side panel.
        if _steps_for([activity.id]).get(activity.id) and activity.id not in _optional_for([activity.id]):
            return Response({"code": "steps_required"}, status=422)
    if activity.type in AI_GRADED_TYPES:
        from apps.providers.services import BudgetExceeded, charge

        try:
            # weighted by the grader's output budget (1500 tokens = 1 unit today; bigger graders cost more)
            charge(request.user, "ai_grades", 1, AI_GRADES_PER_DAY, max_tokens=1500)
        except BudgetExceeded:
            return Response({"code": "grading_budget_exceeded"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    from apps.study.translation import grading_view

    shown_lang = str(request.data.get("lang") or "")
    answer, extra_accept, tr_expl = grading_view(activity, answer, shown_lang)
    if extra_accept and activity.type == "fill_blank":  # in-memory only: accept translated answers too
        blanks = {b: [*a, *extra_accept.get(b, [])] for b, a in activity.key["blanks"].items()}
        activity.key = {**activity.key, "blanks": blanks}
    if tr_expl or shown_lang in ("hi", "te", "kn", "ml", "bn", "mr", "gu", "en", "ta"):
        lang = shown_lang or lang  # AI feedback in the language the learner is reading
    try:
        g = acts.grade(activity, answer, lang, user=request.user)
    except Exception:  # noqa: BLE001 — AI grading outage shouldn't 500 the lesson
        return Response({"code": "grading_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if tr_expl and g.feedback == (activity.key or {}).get("explanation", ""):
        g.feedback = tr_expl
    first_try = not ActivityAttempt.objects.filter(user=request.user, activity=activity).exists()
    stored = (
        {**answer, "image": "[screenshot not stored]"} if "image" in answer else answer
    )  # never keep learner images
    conf = request.data.get("confidence") if request.data.get("confidence") in (1, 2, 3) else None
    ActivityAttempt.objects.create(
        user=request.user,
        activity=activity,
        answer=stored,
        score=g.score,
        correct=g.correct,
        feedback=g.feedback,
        confidence=conf,
    )
    record_attempt(request.user, activity, g.score)
    if first_try:  # adaptive mastery counts first attempts only (a retry after the reveal proves little)
        from apps.adaptive.services import observe

        observe(request.user, activity, g.score)
    reward = game.on_activity(request.user, activity, g.score, first_try)
    return Response(
        {
            "score": round(g.score, 3),
            "correct": g.correct,
            "feedback": g.feedback,
            "reveal": g.reveal,
            "reward": reward,
        }
    )


@api_view(["POST"])
def activity_roleplay(request, pk):
    """Start (or resume) the practice conversation behind a lesson's role-play activity."""
    from apps.roleplay.models import RolePlaySession
    from apps.roleplay.services import scenario_from_brief, start_session

    activity = get_viewable_activity(request.user, pk)
    if activity.type != "roleplay":
        return Response({"code": "not_roleplay"}, status=status.HTTP_400_BAD_REQUEST)
    s = RolePlaySession.objects.filter(user=request.user, activity=activity, status="active").first()
    if not s:
        s = start_session(
            request.user, scenario_from_brief(request.user, activity.key["scenario"]), activity=activity
        )
    return Response({"session_id": s.id}, status=status.HTTP_201_CREATED)


class MatchIn(serializers.Serializer):
    spoken = serializers.CharField(max_length=300)
    options = serializers.ListField(child=serializers.CharField(max_length=300), min_length=2, max_length=6)


@api_view(["POST"])
def match_choice(request):
    """Voice mode: which option did the learner say? Free local match first; AI only for unclear speech."""
    from apps.providers.services import BudgetExceeded, charge

    from .voice_match import ai_match, local_match

    ser = MatchIn(data=request.data)
    ser.is_valid(raise_exception=True)
    spoken, options = ser.validated_data["spoken"], ser.validated_data["options"]
    idx = local_match(spoken, options)
    if idx is not None:
        return Response({"index": idx, "via": "local"})
    try:
        charge(request.user, "ai_grades", 1, AI_GRADES_PER_DAY, max_tokens=200)
    except BudgetExceeded:
        return Response({"index": None, "via": "budget"})
    try:
        return Response({"index": ai_match(spoken, options), "via": "ai"})
    except Exception:  # noqa: BLE001 — the learner can still tap a choice
        return Response({"index": None, "via": "error"})


class LessonFeedbackIn(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    difficulty = serializers.ChoiceField(choices=["easy", "right", "hard"], required=False, allow_blank=True)
    clarity = serializers.IntegerField(min_value=1, max_value=5, required=False, allow_null=True)
    comment = serializers.CharField(max_length=500, required=False, allow_blank=True)


@api_view(["POST"])
def subsection_feedback(request, pk):
    from .models import LessonFeedback

    sub = get_viewable_subsection(request.user, pk)
    ser = LessonFeedbackIn(data=request.data)
    ser.is_valid(raise_exception=True)
    LessonFeedback.objects.update_or_create(user=request.user, subsection=sub, defaults=ser.validated_data)
    return Response({"ok": True})


@api_view(["POST"])
def subsection_complete(request, pk):
    sub = _own_subsection(request, pk)
    best = {}  # first attempt per activity: retrying after the answer is revealed can't inflate the score
    for a in ActivityAttempt.objects.filter(
        user=request.user, activity__subsection=sub, activity__kind="lesson"
    ).order_by("created_at", "id"):
        best.setdefault(a.activity_id, a.score)
    total = sub.activities.filter(kind="lesson").count()
    score = (
        sum(best.values()) / total if total else None
    )  # a lesson with nothing to answer has no score, not 100%
    from apps.adaptive import services as adaptive

    allowed, score, remediation = adaptive.gate(request.user, sub, score, total)
    if (
        not allowed
    ):  # adaptive course, below the pass mark: practise first, then finish (the lesson stays open)
        return Response(
            {
                "passed": False,
                "score": round(score, 3),
                "answered": len(best),
                "total": total,
                "correct": sum(1 for v in best.values() if v >= acts.PASS),
                "remediation": remediation,
                "key_points": sub.key_points,
                "next_subsection_id": None,
            }
        )
    st, _ = UserSubsectionState.objects.get_or_create(user=request.user, subsection=sub)
    st.status, st.score = UserSubsectionState.Status.COMPLETED, None if score is None else round(score, 3)
    st.completed_at = (
        st.completed_at or timezone.now()
    )  # finishing again doesn't move the original completion date
    st.save()
    nxt = (
        Subsection.objects.filter(
            section__curriculum=sub.section.curriculum, archived=False, section__archived=False
        )
        .filter(Q(section__order__gt=sub.section.order) | Q(section=sub.section, order__gt=sub.order))
        .order_by("section__order", "order")
        .first()
    )
    # Clicking Finish without answering anything still moves the learner on (score 0), but earns no lesson XP.
    reward = (
        {"xp": 0, "coins": 0, "badges": []}
        if total and not best
        else game.on_lesson_complete(request.user, sub, score or 0.0)
    )
    adaptive.on_progress(request.user, sub)
    return Response(
        {
            "passed": True,
            "reward": reward,
            "score": None if score is None else round(score, 3),
            "answered": len(best),
            "total": total,
            "correct": sum(1 for v in best.values() if v >= acts.PASS),
            "key_points": sub.key_points,
            "next_subsection_id": nxt.id if nxt else None,
            "feedback_survey": _feedback_survey(request.user, sub),
        }
    )


def _feedback_survey(user, sub):
    """After the last lesson of a course a school assigned: its end-of-training survey (teacher tools, M9)."""
    from apps.orgs.teach import feedback_survey_for

    return feedback_survey_for(user, curriculum_id=sub.section.curriculum_id)


@api_view(["GET"])
def continue_learning(request):
    """Next lesson to resume: first in-progress, else the first not-completed in the newest course."""
    st = (
        UserSubsectionState.objects.filter(
            user=request.user,
            status=UserSubsectionState.Status.IN_PROGRESS,
            subsection__archived=False,
            subsection__section__archived=False,
            # lapsed access (expired partner enrolment, left the org…) drops the course from "continue"
            subsection__section__curriculum__in=viewable_curricula(request.user).values("id"),
        )
        .select_related("subsection__section__curriculum")
        .order_by("-started_at")
        .first()
    )
    sub = st.subsection if st else None
    if not sub:
        from apps.study.journey import ordered

        cur = next(
            iter(
                ordered(
                    request.user,
                    list(
                        viewable_curricula(request.user)
                        .filter(status=Curriculum.Status.READY)
                        .exclude(owner=request.user, kind=Curriculum.Kind.AUTHORED)[:50]
                    ),
                    key=lambda c: c.id,
                )
            ),
            None,
        )
        if cur:
            done = UserSubsectionState.objects.filter(
                user=request.user, status=UserSubsectionState.Status.COMPLETED
            ).values("subsection_id")
            sub = (
                Subsection.objects.filter(section__curriculum=cur, archived=False, section__archived=False)
                .exclude(id__in=done)
                .order_by("section__order", "order")
                .select_related("section__curriculum")
                .first()
            )
    if not sub:
        return Response(None)
    cur = sub.section.curriculum
    return Response(
        {
            "curriculum_id": cur.id,
            "curriculum_title": cur.title,
            "subsection_id": sub.id,
            "subsection_title": sub.title,
        }
    )


def _public_acts(qs):
    return [{"id": a.id, "type": a.type, "title": a.title, "payload": a.payload, "attempt": None} for a in qs]


@api_view(["GET", "POST"])
def subsection_practice(request, pk):
    """GET: current practice set. POST: generate a fresh set (appended)."""
    sub = _own_subsection(request, pk)
    if request.method == "POST":
        if sub.lesson_status != Subsection.LessonStatus.READY:
            return Response({"code": "lesson_not_ready"}, status=status.HTTP_409_CONFLICT)
        if sub.practice_status != "generating":
            from apps.providers.services import BudgetExceeded, charge

            try:  # each set is a paid AI generation on the platform key: daily cap per learner, like AI grading
                charge(request.user, "practice_sets", 1, PRACTICE_SETS_PER_DAY)
            except BudgetExceeded:
                return Response(
                    {"code": "practice_budget_exceeded"}, status=status.HTTP_429_TOO_MANY_REQUESTS
                )
            if (
                Subsection.objects.filter(pk=sub.pk)
                .exclude(practice_status="generating")
                .update(practice_status="generating", generating_since=timezone.now())
            ):  # one job even if two requests race
                enqueue("generate_practice", sub.id)
        sub.refresh_from_db()
    latest_ids = list(
        sub.activities.filter(kind="practice").order_by("-order").values_list("id", flat=True)[:5]
    )
    acts = sub.activities.filter(id__in=latest_ids).order_by("order")
    return Response({"status": sub.practice_status, "title": sub.title, "activities": _public_acts(acts)})
