"""Creator Lab: authoring, publishing, catalog moderation and share links.

Authoring endpoints require `user.can_author` AND ownership of the course.
Share/guest endpoints are public by design but expose only published content
and never answer keys."""

from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from pydantic import TypeAdapter, ValidationError
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from apps.accounts.staff import AdminSection
from llm.base import LLMError
from llm.prompts.curriculum import (
    CREATOR_ONLY_TYPES,
    LANG_RULE,
    VIDEO_QUESTIONS_SYSTEM,
    FlatLessonPackage,
    VideoQuestions,
    single_activity_prompts,
    to_typed,
)
from llm.prompts.curriculum import Activity as ActivitySchema
from llm.structured import complete_json_sync

from . import activities as acts
from .jobs import enqueue
from .models import Activity, Curriculum, Enrollment, Section, Subsection, _share_token, next_order
from .services import _valid, content_language

AI_GRADED = {
    "open_input",
    "code",
    "task",
    "browser_task",
    "roleplay",
    "artifact_check",
}  # need an account (AI cost, budgets)


class IsCreator(permissions.BasePermission):
    message = "creator_access_required"

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.can_author)


def _owned_course(request, pk) -> Curriculum:
    return get_object_or_404(Curriculum, pk=pk, owner=request.user, kind=Curriculum.Kind.AUTHORED)


def _owned_section(request, pk) -> Section:
    return get_object_or_404(
        Section.objects.select_related("curriculum"),
        pk=pk,
        curriculum__owner=request.user,
        curriculum__kind="authored",
    )


def _owned_sub(request, pk) -> Subsection:
    return get_object_or_404(
        Subsection.objects.select_related("section__curriculum"),
        pk=pk,
        section__curriculum__owner=request.user,
        section__curriculum__kind="authored",
    )


def _owned_activity(request, pk) -> Activity:
    return get_object_or_404(
        Activity.objects.exclude(kind="fasttrack").select_related("subsection__section__curriculum"),
        pk=pk,
        subsection__section__curriculum__owner=request.user,
        subsection__section__curriculum__kind="authored",
    )


TOUCH_LABELS = {
    "lab_add_section": "Add section",
    "lab_section": "Edit section",
    "lab_add_subsection": "Add lesson",
    "lab_reorder": "Reorder",
    "lab_subsection": "Edit lesson",
    "lab_add_activity": "Add activity",
    "lab_activity": "Edit activity",
    "lab_course": "Edit course",
}


def _touch(cur, label: str = ""):
    """Content changed: bump the timestamp, record an undo step, and send an approved catalog course back for re-moderation."""
    import sys

    from apps.studio.history import record

    record(cur, label or TOUCH_LABELS.get(sys._getframe(1).f_code.co_name, "Edit"))
    Curriculum.objects.filter(pk=cur.pk).update(updated_at=timezone.now())
    Curriculum.objects.filter(pk=cur.pk, catalog_status=Curriculum.CatalogStatus.APPROVED).update(
        catalog_status=Curriculum.CatalogStatus.PENDING,
        catalog_note="Changed after approval — waiting for review again.",
    )


def _activity_out(a: Activity) -> dict:
    return {
        "id": a.id,
        "type": a.type,
        "kind": a.kind,
        "title": a.title,
        "payload": a.payload,
        "source": a.source,
        "editable": a.source is not None,
    }


def _course_out(cur: Curriculum, full=False) -> dict:
    out = {
        "id": cur.id,
        "title": cur.title or cur.goal,
        "goal": cur.goal,
        "description": cur.description,
        "level": cur.level,
        "language": cur.language,
        "cover_emoji": cur.cover_emoji,
        "status": cur.status,
        "error": cur.error,
        "visibility": cur.visibility,
        "catalog_status": cur.catalog_status,
        "catalog_note": cur.catalog_note,
        "published_at": cur.published_at,
        "share_token": cur.share_token,
        "updated_at": cur.updated_at,
        "learners": cur.n_learners if hasattr(cur, "n_learners") else cur.enrollments.count(),
        "template": {
            "scope": cur.template_scope,
            "org": cur.template_org.slug if cur.template_org_id else None,
        },
    }
    if full:
        from apps.studio.history import state

        from .models import feedback_summary

        subs_all = list(Subsection.objects.filter(section__curriculum=cur))
        fb = feedback_summary(subs_all)
        out["sections"] = [
            {
                "id": s.id,
                "title": s.title,
                "summary": s.summary,
                "order": s.order,
                "archived": s.archived,
                "subsections": [
                    {
                        "id": b.id,
                        "title": b.title,
                        "objective": b.objective,
                        "order": b.order,
                        "lesson_status": b.lesson_status,
                        "error": b.error,
                        "archived": b.archived,
                        "activities": b.n_lesson_acts,
                        "rating": (fb.get(b.id) or {}).get("avg"),
                    }
                    for b in s.subsections.all()
                ],
            }
            for s in cur.sections.prefetch_related(
                Prefetch(
                    "subsections",
                    queryset=Subsection.objects.annotate(
                        n_lesson_acts=Count("activities", filter=Q(activities__kind="lesson"))
                    ).order_by("order"),
                )
            )
        ]
        out["feedback"] = _course_feedback(fb)
        out["history"] = state(cur)
        a = cur.authoring or {}
        out["authoring"] = {
            "preset": a.get("preset"),
            "research": a.get("research"),
            "documents": [{"id": d.id, "title": d.title} for d in cur.documents.all()],
        }
    return out


def _course_feedback(fb: dict) -> dict | None:
    """Course-wide roll-up of lesson feedback (M5 aggregated for authors)."""
    rows = [v for v in fb.values() if v and v.get("n")]
    if not rows:
        return None
    n = sum(r["n"] for r in rows)
    avg = round(sum((r.get("avg") or 0) * r["n"] for r in rows) / n, 2)
    hard, easy = sum(r["hard"] for r in rows), sum(r["easy"] for r in rows)
    return {
        "n": n,
        "avg": avg,
        "hard": hard,
        "easy": easy,
        "right": n - hard - easy,
        "lessons_rated": len(rows),
    }


# ── Courses ───────────────────────────────────────────────────────────


class NewCourse(serializers.Serializer):
    mode = serializers.ChoiceField(choices=["ai", "blank"], default="ai")
    goal = serializers.CharField(max_length=300)
    level = serializers.ChoiceField(choices=["beginner", "intermediate", "advanced"], default="beginner")
    language = serializers.ChoiceField(choices=["en", "ta", "tanglish"], required=False)
    notes = serializers.CharField(max_length=1000, required=False, allow_blank=True)


@api_view(["GET", "POST"])
@permission_classes([IsCreator])
def lab_courses(request):
    if request.method == "GET":
        qs = _with_counts(
            Curriculum.objects.filter(owner=request.user, kind=Curriculum.Kind.AUTHORED).select_related(
                "template_org"
            )
        )
        return Response([_course_out(c) for c in qs[:500]])
    ser = NewCourse(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    if d["mode"] == "ai":
        from apps.billing.services import PlanLimit, consume

        try:
            consume(request.user, "ai_courses_per_month", "ai_course")
        except PlanLimit as e:
            return Response(e.payload(), status=status.HTTP_402_PAYMENT_REQUIRED)
    cur = Curriculum.objects.create(
        owner=request.user,
        kind=Curriculum.Kind.AUTHORED,
        goal=d["goal"],
        level=d["level"],
        notes=d.get("notes", ""),
        language=d.get("language") or content_language(request.user),
        title=d["goal"][:200] if d["mode"] == "blank" else "",
        status=Curriculum.Status.GENERATING if d["mode"] == "ai" else Curriculum.Status.READY,
    )
    if d["mode"] == "ai":
        enqueue("generate_outline", cur.id)
    return Response(_course_out(cur, full=True), status=status.HTTP_201_CREATED)


class CoursePatch(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    level = serializers.ChoiceField(choices=["beginner", "intermediate", "advanced"], required=False)
    cover_emoji = serializers.CharField(max_length=8, required=False)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsCreator])
def lab_course(request, pk):
    cur = _owned_course(request, pk)
    if request.method == "DELETE":
        cur.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    if request.method == "PATCH":
        ser = CoursePatch(data=request.data)
        ser.is_valid(raise_exception=True)
        for k, v in ser.validated_data.items():
            setattr(cur, k, v)
        cur.save()
        _touch(cur)
    else:
        from apps.studio.history import ensure_baseline

        ensure_baseline(cur, request.user)
    return Response(_course_out(cur, full=True))


# ── Outline editing ───────────────────────────────────────────────────


class OutlineItem(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    summary = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    objective = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    archived = serializers.BooleanField(required=False)


@api_view(["POST"])
@permission_classes([IsCreator])
def lab_add_section(request, pk):
    cur = _owned_course(request, pk)
    ser = OutlineItem(data=request.data)
    ser.is_valid(raise_exception=True)
    order = next_order(cur.sections)
    Section.objects.create(
        curriculum=cur,
        order=order,
        title=ser.validated_data["title"],
        summary=ser.validated_data.get("summary", ""),
    )
    _touch(cur)
    return Response(_course_out(cur, full=True), status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsCreator])
def lab_section(request, pk):
    sec = _owned_section(request, pk)
    cur = sec.curriculum
    if request.method == "DELETE":
        sec.delete()
    else:
        ser = OutlineItem(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        for k in ("title", "summary", "archived"):
            if k in ser.validated_data:
                setattr(sec, k, ser.validated_data[k])
        sec.save()
    _touch(cur)
    return Response(_course_out(cur, full=True))


@api_view(["POST"])
@permission_classes([IsCreator])
def lab_add_subsection(request, pk):
    sec = _owned_section(request, pk)
    ser = OutlineItem(data=request.data)
    ser.is_valid(raise_exception=True)
    order = next_order(sec.subsections)
    Subsection.objects.create(
        section=sec,
        order=order,
        title=ser.validated_data["title"],
        objective=ser.validated_data.get("objective", ""),
    )
    _touch(sec.curriculum)
    return Response(_course_out(sec.curriculum, full=True), status=status.HTTP_201_CREATED)


class Reorder(serializers.Serializer):
    sections = serializers.ListField(child=serializers.IntegerField(), required=False)
    subsections = serializers.DictField(
        child=serializers.ListField(child=serializers.IntegerField()), required=False
    )


@api_view(["POST"])
@permission_classes([IsCreator])
@transaction.atomic
def lab_reorder(request, pk):
    cur = _owned_course(request, pk)
    ser = Reorder(data=request.data)
    ser.is_valid(raise_exception=True)
    own_sections = set(cur.sections.values_list("id", flat=True))
    if "sections" in ser.validated_data:
        ids = ser.validated_data["sections"]
        if set(ids) != own_sections:
            return Response({"code": "bad_order"}, status=status.HTTP_400_BAD_REQUEST)
        for i, sid in enumerate(ids):
            Section.objects.filter(id=sid).update(order=i)
    for sid, sub_ids in ser.validated_data.get("subsections", {}).items():
        sid = int(sid)
        if sid not in own_sections or set(sub_ids) != set(
            Subsection.objects.filter(section_id=sid).values_list("id", flat=True)
        ):
            return Response({"code": "bad_order"}, status=status.HTTP_400_BAD_REQUEST)
        for i, bid in enumerate(sub_ids):
            Subsection.objects.filter(id=bid).update(order=i)
    _touch(cur)
    return Response(_course_out(cur, full=True))


# ── Lessons ───────────────────────────────────────────────────────────


class LessonPatch(serializers.Serializer):
    archived = serializers.BooleanField(required=False)
    title = serializers.CharField(max_length=200, required=False)
    objective = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    explanation_md = serializers.CharField(max_length=20000, required=False, allow_blank=True)
    key_points = serializers.ListField(
        child=serializers.CharField(max_length=300), max_length=8, required=False
    )


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsCreator])
def lab_subsection(request, pk):
    sub = _owned_sub(request, pk)
    if request.method == "DELETE":
        cur = sub.section.curriculum
        sub.delete()
        _touch(cur)
        return Response(status=status.HTTP_204_NO_CONTENT)
    if request.method == "PATCH":
        ser = LessonPatch(data=request.data)
        ser.is_valid(raise_exception=True)
        for k, v in ser.validated_data.items():
            setattr(sub, k, v)
        if "explanation_md" in ser.validated_data and sub.lesson_status == Subsection.LessonStatus.EMPTY:
            sub.lesson_status = Subsection.LessonStatus.READY  # hand-written lesson
        sub.save()
        _touch(sub.section.curriculum)
    return Response(
        {
            "id": sub.id,
            "title": sub.title,
            "objective": sub.objective,
            "lesson_status": sub.lesson_status,
            "error": sub.error,
            "explanation_md": sub.explanation_md,
            "key_points": sub.key_points,
            "activities": [_activity_out(a) for a in sub.activities.filter(kind="lesson")],
            "feedback": _lesson_feedback(sub),
        }
    )


def _lesson_feedback(sub) -> dict | None:
    """Learners' ratings for authors: average, difficulty split and the latest comments (no names)."""
    from .models import LessonFeedback, feedback_summary

    summary = feedback_summary([sub]).get(sub.id)
    if not summary:
        return None
    comments = list(
        LessonFeedback.objects.filter(subsection=sub)
        .exclude(comment="")
        .order_by("-updated_at")
        .values_list("comment", flat=True)[:5]
    )
    return {**summary, "comments": comments}


def _lab_ai(request):
    """Every AI generation in the Lab counts against the plan (stops free 'blank course + generate all' abuse)."""
    from apps.billing.services import PlanLimit, consume

    try:
        consume(request.user, "lab_ai_per_day", "lab_ai")
    except PlanLimit as e:
        return Response(e.payload(), status=status.HTTP_402_PAYMENT_REQUIRED)
    return None


@api_view(["POST"])
@permission_classes([IsCreator])
def lab_generate_lesson(request, pk):
    sub = _owned_sub(request, pk)
    if sub.lesson_status == Subsection.LessonStatus.GENERATING:
        return Response({"code": "already_generating"}, status=status.HTTP_409_CONFLICT)
    if denied := _lab_ai(request):
        return denied
    Subsection.objects.filter(pk=sub.pk).update(
        lesson_status=Subsection.LessonStatus.GENERATING, error="", generating_since=timezone.now()
    )
    enqueue("generate_lesson", sub.id)
    return Response({"lesson_status": "generating"}, status=status.HTTP_202_ACCEPTED)


# ── Activities ────────────────────────────────────────────────────────

_ADAPTER = TypeAdapter(ActivitySchema)


def _validate_source(src: dict) -> tuple[dict | None, str]:
    """Same strict checks as AI output: schema, then semantic rules."""
    try:
        typed = _ADAPTER.validate_python(src).model_dump()
    except ValidationError as e:
        return None, "; ".join(
            f"{'.'.join(str(x) for x in err['loc'][1:])}: {err['msg']}" for err in e.errors()[:5]
        )
    if not _valid(typed):
        return None, "The activity is incomplete or inconsistent (check answers, options and links)."
    return typed, ""


def _save_activity(sub, typed, activity=None):
    order = activity.order if activity else next_order(sub.activities.exclude(kind="fasttrack"))
    payload, key = acts.build(typed, seed=sub.id * 100 + order)
    if activity:
        activity.type, activity.title, activity.payload, activity.key, activity.source = (
            typed["type"],
            typed["title"][:200],
            payload,
            key,
            typed,
        )
        activity.save()
        return activity
    return Activity.objects.create(
        subsection=sub,
        order=order,
        type=typed["type"],
        title=typed["title"][:200],
        payload=payload,
        key=key,
        source=typed,
    )


def ai_activity(sub, act_type: str, instructions: str = "") -> tuple[dict | None, str]:
    """One AI-written activity for a lesson → (typed source, "") or (None, error code). Caller charges the plan."""
    from apps.studio.context import generation_extras

    cur = sub.section.curriculum
    extra_rules, _material = generation_extras(cur, f"{sub.title} {sub.objective}")
    system, user = single_activity_prompts(
        act_type,
        cur.title,
        sub.title,
        sub.objective,
        sub.explanation_md,
        cur.level,
        cur.language,
        " ".join(x for x in (instructions, extra_rules) if x)[:1200],
    )
    try:
        pkg = complete_json_sync("author", system, user, FlatLessonPackage, max_tokens=4000, effort="medium")
    except LLMError as e:
        return None, e.code
    typed = next(
        (t for t in (to_typed(f) for f in pkg.activities if f.type == act_type) if t and _valid(t)), None
    )
    return (typed, "") if typed else (None, "generation_invalid")


class AddActivity(serializers.Serializer):
    type = serializers.ChoiceField(choices=Activity.TYPES)
    instructions = serializers.CharField(max_length=500, required=False, allow_blank=True)
    source = serializers.DictField(required=False)  # hand-written activity (skip AI)


@api_view(["POST"])
@permission_classes([IsCreator])
def lab_add_activity(request, pk):
    sub = _owned_sub(request, pk)
    ser = AddActivity(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    if d["type"] in CREATOR_ONLY_TYPES and not d.get("source"):
        return Response(
            {"code": "needs_source", "detail": "Video and image-hotspot activities are made by hand."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if d.get("source"):
        typed, err = _validate_source({**d["source"], "type": d["type"]})
        if not typed:
            return Response({"code": "invalid_activity", "detail": err}, status=status.HTTP_400_BAD_REQUEST)
    else:
        if denied := _lab_ai(request):
            return denied
        typed, code = ai_activity(sub, d["type"], d.get("instructions", ""))
        if code == "generation_invalid":
            return Response(
                {"code": code, "detail": "The AI's activity didn't pass checks — try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        if code:
            return Response({"code": code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    a = _save_activity(sub, typed)
    if sub.lesson_status == Subsection.LessonStatus.EMPTY:
        Subsection.objects.filter(pk=sub.pk).update(lesson_status=Subsection.LessonStatus.READY)
    _touch(sub.section.curriculum)
    return Response(_activity_out(a), status=status.HTTP_201_CREATED)


class VideoQuestionsIn(serializers.Serializer):
    notes = serializers.CharField(max_length=12000)
    start = serializers.IntegerField(min_value=0, default=0)
    end = serializers.IntegerField(min_value=0, default=0)


@api_view(["POST"])
@permission_classes([IsCreator])
def lab_video_questions(request, pk):
    """Draft checkpoint questions for a video from the teacher's notes/transcript (we never fetch the video itself)."""
    sub = _owned_sub(request, pk)
    ser = VideoQuestionsIn(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    if denied := _lab_ai(request):
        return denied
    lang = sub.section.curriculum.language
    try:
        out = complete_json_sync(
            "author",
            VIDEO_QUESTIONS_SYSTEM.format(lang_rule=LANG_RULE[lang]),
            f"Lesson: {sub.title}\nVideo segment: {d['start']}s to {d['end'] or 'end'}\nNotes/transcript:\n{d['notes']}",
            VideoQuestions,
            max_tokens=3000,
        )
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    cps = [
        c.model_dump()
        for c in out.checkpoints
        if len(c.options) >= 2 and c.correct and all(0 <= i < len(c.options) for i in c.correct)
    ]
    return Response({"checkpoints": cps[:8]})


@api_view(["PATCH", "DELETE"])
@permission_classes([IsCreator])
def lab_activity(request, pk):
    a = _owned_activity(request, pk)
    if request.method == "DELETE":
        a.delete()
        _touch(a.subsection.section.curriculum)
        return Response(status=status.HTTP_204_NO_CONTENT)
    src = request.data.get("source")
    if not isinstance(src, dict):
        return Response({"code": "bad_source"}, status=status.HTTP_400_BAD_REQUEST)
    typed, err = _validate_source({**src, "type": src.get("type", a.type)})
    if not typed:
        return Response({"code": "invalid_activity", "detail": err}, status=status.HTTP_400_BAD_REQUEST)
    a = _save_activity(a.subsection, typed, a)
    _touch(a.subsection.section.curriculum)
    return Response(_activity_out(a))


# ── Publishing ────────────────────────────────────────────────────────


@api_view(["POST"])
@permission_classes([IsCreator])
def lab_publish(request, pk):
    cur = _owned_course(request, pk)
    visibility = request.data.get("visibility")
    if visibility == "private":  # unpublish
        cur.visibility, cur.published_at, cur.catalog_status = (
            Curriculum.Visibility.PRIVATE,
            None,
            Curriculum.CatalogStatus.NONE,
        )
        cur.share_token = _share_token()  # old links stay dead if the course is published again
        cur.save()
        return Response(_course_out(cur, full=True))
    if visibility not in ("link", "catalog"):
        return Response({"code": "bad_visibility"}, status=status.HTTP_400_BAD_REQUEST)
    subs = Subsection.objects.filter(section__curriculum=cur).annotate(n=Count("activities"))
    problems = [b.title for b in subs if b.lesson_status != Subsection.LessonStatus.READY or b.n == 0]
    if not subs.exists() or problems:
        return Response(
            {"code": "lessons_not_ready", "lessons": problems[:20]}, status=status.HTTP_409_CONFLICT
        )
    cur.visibility = visibility
    cur.published_at = cur.published_at or timezone.now()
    if visibility == "catalog" and cur.catalog_status != Curriculum.CatalogStatus.APPROVED:
        cur.catalog_status, cur.catalog_note = Curriculum.CatalogStatus.PENDING, ""
    if visibility == "link":
        cur.catalog_status = Curriculum.CatalogStatus.NONE
    cur.save()
    return Response(_course_out(cur, full=True))


@api_view(["POST"])
@permission_classes([IsCreator])
def lab_rotate_share(request, pk):
    """Owner only: issue a new share token so every previously shared link stops working."""
    cur = _owned_course(request, pk)
    cur.share_token = _share_token()
    cur.save(update_fields=["share_token", "updated_at"])
    return Response({"share_token": cur.share_token})


# ── Catalog (learners) + moderation (admins) ──────────────────────────


def _with_counts(qs):
    """List views: learner and (non-archived) lesson counts in the same query instead of two COUNTs per course.
    (Meta.ordering doesn't apply to GROUP BY queries, so the default order is restated.)"""
    return qs.order_by(*Curriculum._meta.ordering).annotate(
        n_learners=Count("enrollments", distinct=True),
        n_lessons=Count(
            "sections__subsections",
            distinct=True,
            filter=Q(sections__archived=False, sections__subsections__archived=False),
        ),
    )


def _public_card(cur):
    lessons = (
        cur.n_lessons
        if hasattr(cur, "n_lessons")
        else Subsection.objects.filter(
            section__curriculum=cur, archived=False, section__archived=False
        ).count()
    )
    return {
        "id": cur.id,
        "title": cur.title,
        "description": cur.description,
        "level": cur.level,
        "language": cur.language,
        "cover_emoji": cur.cover_emoji,
        "creator": (cur.owner.profile.display_name or "Aasan creator").split(" ")[0],
        "lessons": lessons,
        "learners": cur.n_learners if hasattr(cur, "n_learners") else cur.enrollments.count(),
        "skills": cur.skills,
        "share_token": cur.share_token,
    }


@api_view(["GET"])
def catalog(request):
    qs = Curriculum.objects.filter(
        kind="authored", visibility="catalog", catalog_status="approved", published_at__isnull=False
    ).select_related("owner__profile")
    if lang := request.query_params.get("language"):
        qs = qs.filter(language=lang)
    return Response([_public_card(c) for c in _with_counts(qs)[:60]])


@api_view(["GET"])
@permission_classes([AdminSection])
def moderation_queue(request):
    qs = _with_counts(
        Curriculum.objects.filter(kind="authored", catalog_status="pending").select_related("owner__profile")
    )
    return Response([{**_public_card(c), "owner_email": c.owner.email} for c in qs[:200]])


@api_view(["POST"])
@permission_classes([AdminSection])
def moderate(request, pk):
    cur = get_object_or_404(Curriculum, pk=pk, kind="authored", catalog_status="pending")
    decision = request.data.get("decision")
    if decision not in ("approve", "reject"):
        return Response({"code": "bad_decision"}, status=status.HTTP_400_BAD_REQUEST)
    cur.catalog_status = "approved" if decision == "approve" else "rejected"
    cur.catalog_note = (request.data.get("note") or "")[:300] if decision == "reject" else ""
    cur.save(update_fields=["catalog_status", "catalog_note", "updated_at"])
    from apps.game.services import notify

    notify(
        cur.owner,
        "catalog",
        ("✅ " if decision == "approve" else "📝 ") + cur.title[:120],
        "Approved for the catalog" if decision == "approve" else f"Needs changes: {cur.catalog_note}",
        "/lab",
    )
    return Response({"catalog_status": cur.catalog_status})


@api_view(["POST"])
@permission_classes([AdminSection])
def set_creator(request):
    from apps.accounts.models import User

    user = get_object_or_404(User, email=(request.data.get("email") or "").lower())
    user.is_creator = bool(request.data.get("is_creator", True))
    user.save(update_fields=["is_creator"])
    return Response({"email": user.email, "is_creator": user.is_creator})


# ── Share links + guest preview ───────────────────────────────────────


def _shared(token) -> Curriculum:
    return get_object_or_404(
        Curriculum.objects.select_related("owner__profile"),
        share_token=token,
        kind="authored",
        published_at__isnull=False,
        visibility__in=["link", "catalog"],
    )


def _first_lesson(cur):
    sub = (
        Subsection.objects.filter(section__curriculum=cur, archived=False, section__archived=False)
        .order_by("section__order", "order")
        .first()
    )
    if not sub:
        raise Http404
    return sub


class GuestReadThrottle(AnonRateThrottle):
    scope = "guest_read"  # own bucket, not shared with other anonymous throttles
    rate = "300/hour"


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
@throttle_classes([GuestReadThrottle])
def share_info(request, token):
    cur = _shared(token)
    sections = [
        {"title": s.title, "lessons": [b.title for b in s.subsections.all() if not b.archived]}
        for s in cur.sections.prefetch_related("subsections")
        if not s.archived
    ]
    enrolled = request.user.is_authenticated and (
        cur.owner_id == request.user.id or cur.enrollments.filter(user=request.user).exists()
    )
    return Response(
        {
            **_public_card(cur),
            "sections": sections,
            "enrolled": bool(enrolled),
            "curriculum_id": cur.id if enrolled else None,
        }
    )


@api_view(["POST"])
def share_enroll(request, token):
    cur = _shared(token)
    if cur.owner_id != request.user.id:
        Enrollment.objects.get_or_create(user=request.user, curriculum=cur)
    return Response({"curriculum_id": cur.id})


class GuestThrottle(AnonRateThrottle):
    rate = "60/hour"


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
@throttle_classes([GuestReadThrottle])
def guest_lesson(request, token):
    """First lesson, free and anonymous. AI-graded activities are locked for guests."""
    cur = _shared(token)
    sub = _first_lesson(cur)
    return Response(
        {
            "course": _public_card(cur),
            "id": sub.id,
            "title": sub.title,
            "objective": sub.objective,
            "explanation_md": sub.explanation_md,
            "key_points": sub.key_points,
            "activities": [
                {
                    "id": a.id,
                    "type": a.type,
                    "title": a.title,
                    "payload": a.payload,
                    "attempt": None,
                    "locked": a.type in AI_GRADED,
                }
                for a in sub.activities.filter(kind="lesson")
            ],
        }
    )


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([GuestThrottle])
def guest_attempt(request, token, activity_id):
    """Grade a guest answer without storing anything (no account, no progress)."""
    cur = _shared(token)
    sub = _first_lesson(cur)
    a = get_object_or_404(Activity, pk=activity_id, subsection=sub, kind="lesson")
    if a.type in AI_GRADED:
        return Response({"code": "signup_required"}, status=status.HTTP_403_FORBIDDEN)
    answer = request.data.get("answer")
    if not isinstance(answer, dict):
        return Response({"code": "bad_answer"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        g = acts.grade(a, answer, cur.language)
    except Exception:  # noqa: BLE001 — a malformed guest answer must be a 400, never a 500
        return Response({"code": "bad_answer"}, status=status.HTTP_400_BAD_REQUEST)
    return Response(
        {"score": round(g.score, 3), "correct": g.correct, "feedback": g.feedback, "reveal": g.reveal}
    )
