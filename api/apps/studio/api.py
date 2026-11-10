"""Creator studio endpoints (all owner-only, creators only): history & versions, templates, lesson picker,
import/export, presets, grounding (documents + web research), 'Build with Kili' chat, lecture videos."""

import json

from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.learning.lab_api import (
    IsCreator,
    _course_out,
    _lab_ai,
    _owned_course,
    _owned_section,
    _owned_sub,
    _touch,
)
from apps.learning.models import Curriculum, Section, Subsection, next_order

from . import history, snapshot
from .models import AuthoringChat, CourseRevision, GenerationPreset, LectureVideo

MAX_IMPORT_CHARS = 2_000_000


def _full(cur):
    cur.refresh_from_db()
    return _course_out(cur, full=True)


# ── History & versions ───────────────────────────────────────────────


@api_view(["GET"])
@permission_classes([IsCreator])
def course_history(request, pk):
    cur = _owned_course(request, pk)
    return Response({**history.state(cur), "versions": history.versions(cur)})


@api_view(["POST"])
@permission_classes([IsCreator])
def course_undo(request, pk):
    cur = _owned_course(request, pk)
    if not history.step(cur, -1):
        return Response({"code": "nothing_to_undo"}, status=status.HTTP_409_CONFLICT)
    return Response(_full(cur))


@api_view(["POST"])
@permission_classes([IsCreator])
def course_redo(request, pk):
    cur = _owned_course(request, pk)
    if not history.step(cur, +1):
        return Response({"code": "nothing_to_redo"}, status=status.HTTP_409_CONFLICT)
    return Response(_full(cur))


@api_view(["POST"])
@permission_classes([IsCreator])
def course_versions(request, pk):
    cur = _owned_course(request, pk)
    if CourseRevision.objects.filter(curriculum=cur, pinned=True).count() >= 30:
        return Response({"code": "too_many_versions"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    history.save_version(cur, str(request.data.get("label") or "").strip()[:120] or "Version", request.user)
    return Response({**history.state(cur), "versions": history.versions(cur)}, status=status.HTTP_201_CREATED)


@api_view(["POST", "DELETE"])
@permission_classes([IsCreator])
def course_version(request, pk, rid):
    cur = _owned_course(request, pk)
    rev = get_object_or_404(CourseRevision, pk=rid, curriculum=cur, pinned=True)
    if request.method == "DELETE":
        rev.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    history.restore(cur, rev, request.user)
    return Response(_full(cur))


# ── Templates & lesson picker ────────────────────────────────────────


def _visible_templates(user, staff_roles=False):
    """Templates a user may start from. staff_roles=True narrows org templates to schools where the user teaches/admins:
    only those may become an *editable* copy (Lab drafts show answer keys), so a school's learners never get one."""
    from apps.orgs.models import Membership
    from apps.orgs.perms import staff_org_ids

    # staff_roles: org-wide staff only (unit-scoped admins get no editable copies of org templates — consistent with perms.require)
    orgs = (
        staff_org_ids(user)
        if staff_roles
        else Membership.objects.filter(user=user, partner=False).values_list("org_id", flat=True)
    )
    return Curriculum.objects.filter(kind="authored", status="ready").filter(
        Q(template_scope="global")
        | Q(template_scope="org", template_org_id__in=orgs)
        | Q(template_scope__in=["personal", "org", "global"], owner=user)
    )


class TemplateIn(serializers.Serializer):
    scope = serializers.ChoiceField(choices=["", "personal", "org", "global"])
    org = serializers.CharField(required=False, allow_blank=True)


@api_view(["POST"])
@permission_classes([IsCreator])
def course_template(request, pk):
    from apps.orgs.perms import require

    cur = _owned_course(request, pk)
    ser = TemplateIn(data=request.data)
    ser.is_valid(raise_exception=True)
    scope, org = ser.validated_data["scope"], None
    if scope == "global" and not request.user.is_staff:
        return Response({"code": "staff_only"}, status=status.HTTP_403_FORBIDDEN)
    if scope == "org":
        org = require(request.user, ser.validated_data.get("org") or "", "manager").org
    cur.template_scope, cur.template_org = scope, org
    cur.save(update_fields=["template_scope", "template_org"])
    return Response(_full(cur))


@api_view(["GET"])
def templates(request):
    """Templates I can start from; ?for=me ranks the ones matching my followed skills first."""
    from apps.paths.services import match_skills, user_skill_rows

    q = (request.query_params.get("q") or "").strip().lower()
    qs = (
        _visible_templates(request.user)
        .select_related("owner__profile", "template_org")
        .annotate(
            n_lessons=Count(
                "sections__subsections",
                distinct=True,
                filter=Q(sections__archived=False, sections__subsections__archived=False),
            )
        )
        .order_by("-updated_at")[:200]
    )
    followed = {k for k, v in user_skill_rows(request.user).items() if v.followed}
    out = []
    for c in qs:
        if q and q not in f"{c.title} {c.description} {' '.join(c.skills or [])}".lower():
            continue
        matches = sorted(match_skills((c.skills or []) + [c.title]) & followed)
        out.append(
            {
                "id": c.id,
                "title": c.title or c.goal,
                "description": c.description,
                "cover_emoji": c.cover_emoji,
                "level": c.level,
                "scope": c.template_scope,
                "org": c.template_org.name if c.template_org_id else None,
                "mine": c.owner_id == request.user.id,
                "lessons": c.n_lessons,
                "skills": c.skills,
                "matches": matches,
            }
        )
    if request.query_params.get("for") == "me":
        out.sort(key=lambda r: -len(r["matches"]))
    return Response(out[:60])


@api_view(["POST"])
def use_template(request, pk):
    """Start a new course from a template: creators get an editable Lab draft, learners a personal course."""
    src = get_object_or_404(_visible_templates(request.user), pk=pk)
    data = snapshot.serialize(src, with_ids=False, with_keys=False)
    for s in data["sections"]:
        s["lessons"] = [b for b in s["lessons"] if not b.get("archived")]
    data["sections"] = [s for s in data["sections"] if not s.get("archived")]
    authored = (
        request.user.can_author
        and _visible_templates(request.user, staff_roles=True).filter(pk=src.pk).exists()
    )
    with transaction.atomic():
        cur = Curriculum.objects.create(
            owner=request.user,
            kind="authored" if authored else "personal",
            goal=(src.goal or src.title)[:300],
            level=src.level,
            language=src.language,
            status="ready",
            title=src.title,
        )
        snapshot.apply(cur, data, trusted=False)
    if authored:
        history.record(cur, f"From template “{src.title}”"[:120], request.user)
    return Response({"id": cur.id, "kind": cur.kind}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsCreator])
def lesson_library(request):
    """Lessons I can reuse: from my own authored courses and from templates I can see."""
    q = (request.query_params.get("q") or "").strip()
    courses = Curriculum.objects.filter(
        Q(owner=request.user, kind="authored")
        | Q(id__in=_visible_templates(request.user, staff_roles=True).values("id"))
    )
    qs = (
        Subsection.objects.filter(section__curriculum__in=courses)
        .exclude(lesson_status="empty")
        .select_related("section__curriculum")
        .annotate(n_lesson_acts=Count("activities", filter=Q(activities__kind="lesson")))
    )
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(objective__icontains=q))
    return Response(
        [
            {
                "id": b.id,
                "title": b.title,
                "objective": b.objective,
                "course": b.section.curriculum.title,
                "activities": b.n_lesson_acts,
            }
            for b in qs.order_by("-section__curriculum__updated_at")[:50]
        ]
    )


@api_view(["POST"])
@permission_classes([IsCreator])
def import_lesson(request, pk):
    sec = _owned_section(request, pk)
    courses = Curriculum.objects.filter(
        Q(owner=request.user, kind="authored")
        | Q(id__in=_visible_templates(request.user, staff_roles=True).values("id"))
    )
    src = get_object_or_404(
        Subsection.objects.filter(section__curriculum__in=courses), pk=request.data.get("subsection_id")
    )
    snapshot.copy_lesson(src, sec)
    _touch(sec.curriculum, f"Reuse lesson “{src.title}”"[:120])
    return Response(_full(sec.curriculum), status=status.HTTP_201_CREATED)


# ── Import / export ──────────────────────────────────────────────────


@api_view(["GET"])
@permission_classes([IsCreator])
def course_export(request, pk):
    cur = _owned_course(request, pk)
    data = snapshot.serialize(
        cur, with_ids=False, with_keys=False
    )  # sources only — answer keys are rebuilt on import
    fmt = request.query_params.get("as", "json")
    name = (
        "".join(ch for ch in (cur.title or "course") if ch.isalnum() or ch in " -_")[:60].strip() or "course"
    )
    if fmt == "yaml":
        import yaml

        body, ctype, ext = (
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            "application/yaml",
            "yaml",
        )
    else:
        body, ctype, ext = json.dumps(data, ensure_ascii=False, indent=2), "application/json", "json"
    resp = HttpResponse(body, content_type=f"{ctype}; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{name}.{ext}"'
    return resp


class ImportIn(serializers.Serializer):
    format = serializers.ChoiceField(choices=["json", "yaml", "outline"])
    text = serializers.CharField(max_length=MAX_IMPORT_CHARS, trim_whitespace=False)
    title = serializers.CharField(max_length=200, required=False, allow_blank=True)
    org = serializers.SlugField(
        required=False, allow_blank=True
    )  # import straight into an org's template library


@api_view(["POST"])
@permission_classes([IsCreator])
def course_import(request):
    ser = ImportIn(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    try:
        if d["format"] == "outline":
            data = snapshot.from_outline(d["text"], d.get("title", ""))
        elif d["format"] == "yaml":
            data = snapshot.validate(snapshot.load_yaml(d["text"]))
        else:
            data = snapshot.validate(json.loads(d["text"]))
    except (ValueError, TypeError) as e:  # SnapshotError, JSONDecodeError
        return Response(
            {"code": "invalid_import", "detail": str(e)[:300]}, status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:  # noqa: BLE001 — yaml.YAMLError and friends
        return Response(
            {"code": "invalid_import", "detail": str(e)[:300]}, status=status.HTTP_400_BAD_REQUEST
        )
    org = None
    if d.get("org"):
        from apps.orgs.perms import require

        org = require(request.user, d["org"], "manager").org
    if Curriculum.objects.filter(owner=request.user, kind="authored").count() >= 200:
        return Response({"code": "too_many_courses"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    from apps.learning.services import content_language

    with transaction.atomic():
        c = data.get("course") or {}
        cur = Curriculum.objects.create(
            owner=request.user,
            kind="authored",
            status="ready",
            goal=snapshot._txt(c.get("goal"), 300) or snapshot._txt(c.get("title"), 300) or "Imported course",
            title=d.get("title") or snapshot._txt(c.get("title"), 200) or "Imported course",
            language=content_language(request.user),
        )
        dropped = snapshot.apply(cur, data, trusted=False)
        if d.get("title"):
            Curriculum.objects.filter(pk=cur.pk).update(title=d["title"][:200])
        if org:
            Curriculum.objects.filter(pk=cur.pk).update(template_scope="org", template_org=org)
    history.record(cur, "Imported", request.user)
    return Response({**_full(cur), "dropped_activities": dropped}, status=status.HTTP_201_CREATED)


# ── Presets (saved pipelines) ────────────────────────────────────────


class PresetSer(serializers.ModelSerializer):
    class Meta:
        model = GenerationPreset
        fields = [
            "id",
            "name",
            "level",
            "language",
            "activity_types",
            "tone",
            "lessons_per_section",
            "instructions",
        ]

    def validate_activity_types(self, v):
        from apps.learning.models import Activity

        allowed = set(Activity.TYPES)
        if not isinstance(v, list) or not set(v) <= allowed or len(v) > 10:
            raise serializers.ValidationError("unknown activity type")
        return v

    def validate_tone(self, v):
        if v not in ("friendly", "formal", "playful", "exam"):
            raise serializers.ValidationError("bad tone")
        return v

    def validate_level(self, v):
        if v not in ("", "beginner", "intermediate", "advanced"):
            raise serializers.ValidationError("bad level")
        return v

    def validate_language(self, v):
        if v not in ("", "en", "ta", "tanglish"):
            raise serializers.ValidationError("bad language")
        return v

    def validate_lessons_per_section(self, v):
        if not 0 <= v <= 12:
            raise serializers.ValidationError("0-12")
        return v


@api_view(["GET", "POST"])
@permission_classes([IsCreator])
def presets(request):
    if request.method == "POST":
        if GenerationPreset.objects.filter(owner=request.user).count() >= 30:
            return Response({"code": "too_many_presets"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        ser = PresetSer(data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save(owner=request.user)
        return Response(ser.data, status=status.HTTP_201_CREATED)
    return Response(PresetSer(GenerationPreset.objects.filter(owner=request.user), many=True).data)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsCreator])
def preset_detail(request, pk):
    p = get_object_or_404(GenerationPreset, pk=pk, owner=request.user)
    if request.method == "DELETE":
        p.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    ser = PresetSer(p, data=request.data, partial=True)
    ser.is_valid(raise_exception=True)
    ser.save()
    return Response(ser.data)


@api_view(["POST"])
@permission_classes([IsCreator])
def course_preset(request, pk):
    """Attach a preset to a course (copied, so later preset edits don't silently change it). null detaches."""
    cur = _owned_course(request, pk)
    before = (cur.level, cur.language)
    pid = request.data.get("preset_id")
    a = dict(cur.authoring or {})
    if pid in (None, ""):
        a.pop("preset", None)
    else:
        p = get_object_or_404(GenerationPreset, pk=pid, owner=request.user)
        a["preset"] = PresetSer(p).data
        if p.level:
            cur.level = p.level
        if p.language:
            cur.language = p.language
    cur.authoring = a
    cur.save()
    if (
        cur.level,
        cur.language,
    ) != before:  # learner-visible change: an approved catalog course is re-moderated
        _touch(cur, "Preset")
        cur.refresh_from_db(fields=["catalog_status", "catalog_note"])
    return Response(_full(cur))


# ── Grounding: attached documents + web research ─────────────────────


@api_view(["POST"])
@permission_classes([IsCreator])
def course_documents(request, pk):
    from apps.orgs.extras import viewable_documents

    cur = _owned_course(request, pk)
    ids = request.data.get("document_ids") or []
    if not isinstance(ids, list) or len(ids) > 5:
        return Response({"code": "max_5_documents"}, status=status.HTTP_400_BAD_REQUEST)
    # Only documents the author may read right now (an ex-admin's knowledge-base upload doesn't count through ownership).
    docs = list(
        viewable_documents(request.user).filter(
            id__in=[i for i in ids if isinstance(i, int) and not isinstance(i, bool)]
        )
    )
    cur.documents.set(docs)
    return Response(_full(cur))


@api_view(["POST", "DELETE"])
@permission_classes([IsCreator])
def course_research(request, pk):
    from llm.base import LLMError
    from llm.research import research

    cur = _owned_course(request, pk)
    a = dict(cur.authoring or {})
    if request.method == "DELETE":
        a.pop("research", None)
    else:
        topic = str(request.data.get("topic") or cur.title or cur.goal).strip()[:300]
        if len(topic) < 3:
            return Response({"code": "bad_topic"}, status=status.HTTP_400_BAD_REQUEST)
        if denied := _lab_ai(request):
            return denied
        try:
            r = research(topic, f"{cur.title} — {cur.level} level")
        except LLMError as e:
            return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        a["research"] = {"topic": topic, **r}
    cur.authoring = a
    cur.save(update_fields=["authoring"])
    return Response(_full(cur))


# ── Build with Kili (chat authoring) ─────────────────────────────────


def _outline_for_ai(cur) -> str:
    lines = [f"Course: {cur.title} ({cur.level}, {cur.language})"]
    for s in cur.sections.order_by("order"):
        lines.append(f"[section_id={s.id}] {s.title}{' (archived)' if s.archived else ''}")
        for b in s.subsections.order_by("order"):
            n = b.activities.filter(kind="lesson").count()
            lines.append(
                f"  [lesson_id={b.id}] {b.title} — {b.objective[:120]} ({b.lesson_status}, {n} activities)"
            )
    return "\n".join(lines)[:8000]


@api_view(["GET", "POST"])
@permission_classes([IsCreator])
def course_chat(request, pk):
    from apps.learning.models import Activity
    from llm.base import LLMError
    from llm.prompts.curriculum import LANG_RULE
    from llm.prompts.studio import CHAT_SYSTEM, ChatOut
    from llm.structured import complete_json_sync

    cur = _owned_course(request, pk)
    chat, _ = AuthoringChat.objects.get_or_create(curriculum=cur)
    if request.method == "GET":
        return Response({"messages": chat.messages})
    text = str(request.data.get("message") or "").strip()
    if not 1 <= len(text) <= 2000:
        return Response({"code": "bad_message"}, status=status.HTTP_400_BAD_REQUEST)
    if denied := _lab_ai(request):
        return denied
    from apps.accounts.companion import as_companion

    history_txt = "\n".join(f"{m['role']}: {m['content'][:600]}" for m in chat.messages[-8:])
    types = ", ".join(Activity.TYPES)
    try:
        out = complete_json_sync(
            "author",
            as_companion(
                CHAT_SYSTEM.format(types=types, lang_rule=LANG_RULE.get(cur.language, LANG_RULE["en"])),
                request.user,
            ),
            f"OUTLINE:\n{_outline_for_ai(cur)}\n\nEARLIER:\n{history_txt}\n\nTEACHER: {text}",
            ChatOut,
            max_tokens=6000,
            effort="medium",
        )
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    changes = [c.model_dump() for c in out.changes[:12]]
    chat.messages = [
        *chat.messages,
        {"role": "user", "content": text},
        {"role": "assistant", "content": out.reply, "changes": changes, "applied": [], "rejected": []},
    ][-40:]
    chat.save()
    return Response({"messages": chat.messages})


class ApplyIn(serializers.Serializer):
    turn = serializers.IntegerField(min_value=0)
    accept = serializers.ListField(child=serializers.IntegerField(min_value=0), max_length=12)
    reject = serializers.ListField(child=serializers.IntegerField(min_value=0), max_length=12, required=False)


def _do(cur, ch: dict, made: dict[int, Section], i: int, request) -> str:
    """Execute one accepted change. Returns "" or a short error code. Ids must belong to this course."""

    from apps.learning.jobs import enqueue
    from apps.learning.lab_api import _save_activity, ai_activity

    op = ch["op"]
    sec = (made.get(ch["ref"]) if ch.get("ref", -1) >= 0 else None) or Section.objects.filter(
        pk=ch.get("section_id"), curriculum=cur
    ).first()
    sub = Subsection.objects.filter(pk=ch.get("lesson_id"), section__curriculum=cur).first()
    title = (ch.get("title") or "").strip()[:200]
    text = (ch.get("text") or "").strip()
    if op == "edit_course":
        if not title and not text:
            return "empty"
        cur.title = title or cur.title
        cur.description = text[:2000] or cur.description
        cur.save(update_fields=["title", "description"])
    elif op == "add_section":
        if not title:
            return "missing_title"
        order = next_order(cur.sections)
        made[i] = Section.objects.create(curriculum=cur, order=order, title=title, summary=text[:1000])
    elif op == "rename_section":
        if not sec:
            return "unknown_section"
        sec.title, sec.summary = title or sec.title, text[:1000] or sec.summary
        sec.save()
    elif op == "delete_section":
        if not sec:
            return "unknown_section"
        sec.delete()
    elif op == "add_lesson":
        if not sec or not title:
            return "unknown_section" if not sec else "missing_title"
        order = next_order(sec.subsections)
        Subsection.objects.create(section=sec, order=order, title=title, objective=text[:1000])
    elif op in ("edit_lesson", "write_lesson", "generate_lesson", "add_activity", "delete_lesson"):
        if not sub:
            return "unknown_lesson"
        if op == "edit_lesson":
            sub.title, sub.objective = title or sub.title, text[:1000] or sub.objective
            sub.save()
        elif op == "write_lesson":
            if not text:
                return "empty"
            sub.explanation_md = text[:20000]
            sub.key_points = [str(k)[:300] for k in (ch.get("key_points") or [])][:8] or sub.key_points
            if sub.lesson_status == "empty":
                sub.lesson_status = "ready"
            sub.save()
        elif op == "delete_lesson":
            sub.delete()
        elif op == "generate_lesson":
            if sub.lesson_status == "generating":
                return "already_generating"
            if _lab_ai(request):
                return "plan_limit"
            from django.utils import timezone

            Subsection.objects.filter(pk=sub.pk).update(
                lesson_status="generating", error="", generating_since=timezone.now()
            )
            transaction.on_commit(lambda sid=sub.id: enqueue("generate_lesson", sid))
        elif op == "add_activity":
            if _lab_ai(request):
                return "plan_limit"
            typed, code = ai_activity(
                sub, ch.get("activity_type") or "quiz", (ch.get("instructions") or "")[:500]
            )
            if not typed:
                return code
            _save_activity(sub, typed)
            if sub.lesson_status == "empty":
                Subsection.objects.filter(pk=sub.pk).update(lesson_status="ready")
    return ""


@api_view(["POST"])
@permission_classes([IsCreator])
def course_chat_apply(request, pk):
    cur = _owned_course(request, pk)
    ser = ApplyIn(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    chat = get_object_or_404(AuthoringChat, curriculum=cur)
    msgs = list(chat.messages)
    if d["turn"] >= len(msgs) or msgs[d["turn"]].get("role") != "assistant":
        return Response({"code": "bad_turn"}, status=status.HTTP_400_BAD_REQUEST)
    turn = dict(msgs[d["turn"]])
    changes, done = (
        turn.get("changes") or [],
        set(turn.get("applied") or []) | set(turn.get("rejected") or []),
    )
    results, made = {}, {}
    with transaction.atomic():
        for i in sorted(set(d["accept"])):
            if i >= len(changes) or i in done:
                continue
            results[i] = _do(cur, changes[i], made, i, request)
        applied = [i for i, err in results.items() if not err]
        turn["applied"] = sorted(set(turn.get("applied") or []) | set(applied))
        turn["rejected"] = sorted(
            (set(turn.get("rejected") or []) | set(d.get("reject") or [])) - set(turn["applied"])
        )
        turn["errors"] = {**(turn.get("errors") or {}), **{str(i): e for i, e in results.items() if e}}
        msgs[d["turn"]] = turn
        chat.messages = msgs
        chat.save()
        if applied:
            _touch(cur, f"Kili: {len(applied)} change{'s' if len(applied) != 1 else ''}")
    return Response({"messages": chat.messages, "course": _full(cur), "results": results})


# ── Lecture videos ───────────────────────────────────────────────────

MAX_LECTURE_BYTES = 50 * 1024 * 1024
MAX_LECTURE_UPLOADS = 60  # per creator; LectureVideo has no size column yet, so cap the count
MAGIC = (
    (b"\x1aE\xdf\xa3", "video/webm"),
    (b"ID3", "audio/mpeg"),
    (b"\xff\xfb", "audio/mpeg"),
    (b"\xff\xf3", "audio/mpeg"),
    (b"RIFF", "audio/wav"),
    (b"OggS", "audio/ogg"),
)


def _sniff(head: bytes) -> str:
    if head[4:8] == b"ftyp":
        return "audio/mp4" if head[8:12] in (b"M4A ", b"M4B ") else "video/mp4"
    return next((m for sig, m in MAGIC if head.startswith(sig)), "")


def _yt_id(url: str) -> str:
    import re

    m = re.search(r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})", url or "") or re.fullmatch(
        r"([A-Za-z0-9_-]{11})", (url or "").strip()
    )
    return m.group(1) if m else ""


EXT = {
    "video/mp4": "mp4",
    "audio/mp4": "m4a",
    "video/webm": "webm",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/ogg": "ogg",
}


def _lecture_src(lv: LectureVideo) -> str:
    return (
        "/" + lv.file.url.lstrip("/") if lv.file else ""
    )  # site-absolute: the player only loads our own files


def _lecture_out(lv: LectureVideo) -> dict:
    return {
        "id": lv.id,
        "kind": lv.kind,
        "video_id": lv.video_id,
        "src": _lecture_src(lv),
        "duration": lv.duration,
        "title": lv.title,
        "status": lv.status,
        "error": lv.error,
        "segments": lv.segments,
        "transcript": lv.transcript[:20000],
    }


@api_view(["GET", "POST"])
@permission_classes([IsCreator])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def lectures(request, pk):
    """POST multipart {file, duration} (upload → speech-to-text) or {youtube_url, transcript, duration}. Segmented by AI."""
    from .lecture import enqueue_process

    sub = _owned_sub(request, pk)
    if request.method == "GET":
        return Response([_lecture_out(lv) for lv in sub.lectures.order_by("-created_at")[:10]])
    try:
        duration = max(0, min(4 * 3600, int(float(request.data.get("duration") or 0))))
    except (TypeError, ValueError):
        duration = 0
    from apps.billing.services import lock_user

    with transaction.atomic():
        lock_user(request.user)  # both counts below are checked and the row created under the user's lock
        if (
            LectureVideo.objects.filter(owner=request.user, status__in=["transcribing", "segmenting"]).count()
            >= 2
        ):
            return Response({"code": "too_many_processing"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        f = request.FILES.get("file")
        if f:
            if LectureVideo.objects.filter(owner=request.user, kind="upload").count() >= MAX_LECTURE_UPLOADS:
                return Response(
                    {"code": "lecture_quota", "max": MAX_LECTURE_UPLOADS}, status=status.HTTP_409_CONFLICT
                )
            if f.size > MAX_LECTURE_BYTES:
                return Response(
                    {"code": "file_too_large", "max_mb": MAX_LECTURE_BYTES // (1024 * 1024)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            mime = _sniff(f.read(16))
            f.seek(0)
            if not mime:
                return Response({"code": "unsupported_file"}, status=status.HTTP_400_BAD_REQUEST)
            if denied := _lab_ai(request):
                return denied
            title = str(request.data.get("title") or f.name)[:200]
            f.name = f"lecture.{EXT[mime]}"  # stored extension comes from the sniffed type, never the uploader's name
            lv = LectureVideo.objects.create(
                owner=request.user,
                subsection=sub,
                kind="upload",
                file=f,
                mime=mime,
                duration=duration,
                title=title,
            )
        else:
            vid = _yt_id(str(request.data.get("youtube_url") or ""))
            transcript = str(request.data.get("transcript") or "").strip()[:200000]
            if not vid:
                return Response({"code": "bad_youtube_url"}, status=status.HTTP_400_BAD_REQUEST)
            if len(transcript) < 40:
                return Response({"code": "transcript_required"}, status=status.HTTP_400_BAD_REQUEST)
            if denied := _lab_ai(request):
                return denied
            lv = LectureVideo.objects.create(
                owner=request.user,
                subsection=sub,
                kind="youtube",
                video_id=vid,
                transcript=transcript,
                duration=duration,
                title=str(request.data.get("title") or "")[:200],
                status="segmenting",
            )
    transaction.on_commit(lambda: enqueue_process(lv.id))
    return Response(_lecture_out(lv), status=status.HTTP_202_ACCEPTED)


@api_view(["GET", "DELETE"])
@permission_classes([IsCreator])
def lecture_detail(request, lid):
    lv = get_object_or_404(LectureVideo, pk=lid, owner=request.user)
    if request.method == "DELETE":
        if lv.file:
            lv.file.delete(save=False)
        lv.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    return Response(_lecture_out(lv))


class SegIn(serializers.Serializer):
    start = serializers.IntegerField(min_value=0)
    end = serializers.IntegerField(min_value=0)
    title = serializers.CharField(max_length=200)
    checkpoints = serializers.ListField(child=serializers.DictField(), max_length=6)


@api_view(["POST"])
@permission_classes([IsCreator])
def lecture_build(request, lid):
    """Accepted (possibly re-trimmed) segments → one video activity each, with their checkpoint questions."""
    from apps.learning.lab_api import _save_activity, _validate_source

    lv = get_object_or_404(
        LectureVideo.objects.select_related("subsection__section__curriculum"),
        pk=lid,
        owner=request.user,
        status="ready",
    )
    ser = SegIn(data=request.data.get("segments") or [], many=True)
    ser.is_valid(raise_exception=True)
    if not ser.validated_data or len(ser.validated_data) > 12:
        return Response({"code": "pick_segments"}, status=status.HTTP_400_BAD_REQUEST)
    built, errors = 0, []
    with transaction.atomic():
        for i, sg in enumerate(ser.validated_data):
            end = sg["end"] if sg["end"] > sg["start"] else 0
            cps = [
                {
                    "at": max(sg["start"], min(int(c.get("at", end or sg["start"])), end or 10**6)),
                    "question": str(c.get("question", ""))[:300],
                    "options": [str(o)[:200] for o in (c.get("options") or [])][:6],
                    "correct": [int(x) for x in (c.get("correct") or []) if str(x).isdigit()],
                }
                for c in sg["checkpoints"]
            ]
            src = {
                "type": "video",
                "title": sg["title"][:200],
                "prompt": f"Watch {sg['title']} and answer the checkpoint questions.",
                "video_id": lv.video_id,
                "src": _lecture_src(lv),
                "start": sg["start"],
                "end": end,
                "checkpoints": cps,
                "explanation": "",
            }
            typed, err = _validate_source(src)
            if not typed:
                errors.append({"segment": i, "detail": err})
                continue
            _save_activity(lv.subsection, typed)
            built += 1
        if built and lv.subsection.lesson_status == "empty":
            Subsection.objects.filter(pk=lv.subsection_id).update(lesson_status="ready")
        if built:
            _touch(
                lv.subsection.section.curriculum, f"Lecture: {built} video segment{'s' if built != 1 else ''}"
            )
    return Response(
        {"built": built, "errors": errors},
        status=status.HTTP_201_CREATED if built else status.HTTP_400_BAD_REQUEST,
    )
