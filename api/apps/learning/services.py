"""Course + lesson generation. Pure functions over the DB; run them inline
(tests), in a background thread (local dev) or as Celery tasks (Redis)."""

import logging
import re

from django.db import models, transaction

from apps.accounts.preferences import upgrade
from llm.base import LLMError
from llm.prompts.curriculum import (
    CurriculumOutline,
    FlatLessonPackage,
    interactive_for,
    lesson_prompts,
    outline_prompts,
    practice_prompts,
    to_typed,
)
from llm.structured import complete_json_sync

from . import activities
from .models import Activity, Curriculum, Section, Subsection
from .safe_math import valid_expression

log = logging.getLogger(__name__)
MAX_SECTIONS, MAX_SUBS = 6, 5


def content_language(user) -> str:
    """Lesson language follows the learner: explicit reply language, else UI language."""
    reply = upgrade(user.preferences.data)["mentor"]["reply_language"]
    if reply in ("en", "ta", "tanglish"):
        return reply
    lang = user.profile.language
    return lang if lang in ("en", "ta", "hi", "te", "kn", "ml", "bn", "mr", "gu") else "en"


def send_back_for_review(cur) -> None:
    """New content on an approved catalog course goes back to moderation (same rule as hand edits in the Lab)."""
    Curriculum.objects.filter(pk=cur.pk, catalog_status=Curriculum.CatalogStatus.APPROVED).update(
        catalog_status=Curriculum.CatalogStatus.PENDING,
        catalog_note="Changed after approval — waiting for review again.",
    )


def _source_doc_ok(cur) -> bool:
    """The course's source document is used only while its owner can still read it (left the org, doc unshared…),
    the same re-check studio/context.py does for attached documents."""
    from apps.orgs.extras import viewable_documents

    return (
        bool(cur.source_document_id)
        and viewable_documents(cur.owner).filter(id=cur.source_document_id).exists()
    )


def generate_outline(curriculum_id: int) -> None:
    """Any failure, not just the AI call (e.g. a DB error while saving the outline), marks the course failed, so the
    page never polls "building..." forever."""
    try:
        _generate_outline(curriculum_id)
    except Exception:
        log.exception("outline generation crashed for %s", curriculum_id)
        Curriculum.objects.filter(id=curriculum_id, status=Curriculum.Status.GENERATING).update(
            status=Curriculum.Status.FAILED, error="internal_error"
        )


def _generate_outline(curriculum_id: int) -> None:
    cur = Curriculum.objects.get(id=curriculum_id)
    material = ""
    if _source_doc_ok(cur):
        # Outline sees a broad sample of the notes (first ~14k chars).
        material = "\n".join(c.text for c in cur.source_document.chunks.all())[:14000]
    from apps.studio.context import generation_extras

    rules, extra = generation_extras(cur, cur.goal)
    material = "\n\n".join(x for x in (material, extra) if x)
    system, user = outline_prompts(
        cur.goal, cur.level, cur.domain, " ".join(x for x in (cur.notes, rules) if x), cur.language, material
    )
    try:
        outline = complete_json_sync(
            "author", system, user, CurriculumOutline, max_tokens=6000, effort="medium"
        )
    except Exception as e:
        code = e.code if isinstance(e, LLMError) else "internal_error"
        log.exception("outline generation failed for %s: %s", curriculum_id, code)
        Curriculum.objects.filter(id=curriculum_id).update(status=Curriculum.Status.FAILED, error=code)
        return
    with transaction.atomic():
        cur.sections.all().delete()
        for si, sec in enumerate(outline.sections[:MAX_SECTIONS]):
            section = Section.objects.create(
                curriculum=cur, order=si, title=sec.title[:200], summary=sec.summary
            )
            for bi, sub in enumerate(sec.subsections[:MAX_SUBS]):
                skills = [k for k in sub.skills if k in outline.skills][:2]
                Subsection.objects.create(
                    section=section, order=bi, title=sub.title[:200], objective=sub.objective, skills=skills
                )
        cur.title = outline.title[:200]
        cur.description = outline.description
        cur.skills = outline.skills[:8]
        cur.error = ""
        cur.save()  # still GENERATING: nobody opens it until its concept graph exists (see _adaptive_setup)
        send_back_for_review(cur)
    if cur.kind == Curriculum.Kind.AUTHORED:
        from apps.studio.history import record

        record(cur, "AI outline")
    _adaptive_setup(cur)


def _adaptive_setup(cur) -> None:
    """Concept graph for the new outline (part of the author's generation), THEN the course opens, THEN — for a course
    built from a learner's goal — that learner's own path. Opening the course only after the graph exists matters: a
    learner who opened it earlier would get the plain fallback graph, which the AI graph then replaced under their
    path. A failed graph never fails the outline."""
    from apps.adaptive import graph
    from apps.adaptive.services import get_path

    try:
        graph.build(cur, use_ai=True)
    except Exception:
        log.exception("concept graph failed for course %s", cur.id)
    Curriculum.objects.filter(pk=cur.pk).update(status=Curriculum.Status.READY)
    cur.status = Curriculum.Status.READY
    try:
        if getattr(cur, "learning_goal", None):
            get_path(cur.owner, cur)
    except Exception:
        log.exception("adaptive path setup failed for course %s", cur.id)


def _valid(act: dict) -> bool:
    """Drop structurally broken activities instead of failing the lesson."""
    t = act["type"]
    if t in ("quiz", "diagram"):
        n = len(act["options"])
        return n >= 2 and act["correct"] and all(0 <= c < n for c in act["correct"])
    if t == "fill_blank":
        return bool(act["blanks"]) and all(
            f"[[{b['id']}]]" in act["text"] and b["answers"] for b in act["blanks"]
        )
    if t == "sequencing":
        return len(act["items_in_order"]) >= 2
    if t == "categorization":
        cats = set(act["categories"])
        return len(cats) >= 2 and act["items"] and all(i["category"] in cats for i in act["items"])
    if t == "matching":
        return len(act["pairs"]) >= 2
    if t == "slides":
        n = len(act["options"])
        return (
            2 <= len(act["slides"]) <= 6
            and n >= 2
            and act["correct"]
            and all(0 <= c < n for c in act["correct"])
        )
    if t == "concept_map":
        return len(act["links"]) >= 2 and all(lk["label"].strip() for lk in act["links"])
    if t == "viz":
        n = len(act["options"])
        if not (n >= 2 and act["correct"] and all(0 <= c < n for c in act["correct"])):
            return False
        v = act["viz"]
        if v["kind"] == "probability_sim":
            return v["sides"] in (2, 6)
        if v["kind"] == "function_plot":
            names = {p["name"] for p in v["params"]}
            params_ok = all(
                p["min"] < p["max"] and p["step"] > 0 and p["min"] <= p["value"] <= p["max"]
                for p in v["params"]
            )
            return (
                v["x_min"] < v["x_max"]
                and params_ok
                and len(v["params"]) <= 3
                and valid_expression(v["expression"], names | {"x"})
            )
        return False
    if t == "decision_tree":
        return _tree_ok(act["tree"])
    if t == "task":
        return bool(act["steps"]) and bool(act["rubric"])
    if t == "map":
        box = MAP_BOUNDS[act["region"]]
        return (
            2 <= len(act["places"]) <= 8
            and len({p["name"].strip().lower() for p in act["places"]}) == len(act["places"])
            and all(box[0] <= p["lat"] <= box[1] and box[2] <= p["lon"] <= box[3] for p in act["places"])
        )
    if t == "browser_task":
        return bool(act["steps"]) and bool(act["rubric"]) and bool(act["proof"].strip())
    if t == "roleplay":
        return (
            all(
                act[k].strip()
                for k in ("character_name", "character_persona", "learner_role", "opening_line", "goal")
            )
            and 1 <= len(act["objectives"]) <= 4
        )
    if t == "video":
        cps = act["checkpoints"]
        from django.conf import settings

        own = bool(
            re.fullmatch(
                "/?"
                + re.escape(settings.MEDIA_URL.lstrip("/"))
                + r"lectures/\d+/[0-9a-f]{32}\.(mp4|webm|m4a|mp3|wav|ogg)",
                act.get("src") or "",
            )
        )
        if act.get("src") and not own:  # never an external URL
            return False
        if not (
            (VIDEO_ID.match(act["video_id"]) if act["video_id"] else own)
            and 1 <= len(cps) <= 8
            and act["start"] >= 0
            and (act["end"] == 0 or act["end"] > act["start"])
        ):
            return False
        return all(
            len(c["options"]) >= 2
            and c["correct"]
            and all(0 <= i < len(c["options"]) for i in c["correct"])
            and c["at"] >= act["start"]
            and (act["end"] == 0 or c["at"] <= act["end"])
            for c in cps
        )
    if t == "artifact_check":
        checks = act["checks"]
        return (
            1 <= len(checks) <= 12
            and len(act["steps"]) <= 8
            and all(
                (c["value"].strip() if c["kind"] in ("phrase", "heading") else True)
                and len(c["value"]) <= 200
                for c in checks
            )
        )
    if t == "hotspot":
        labels = [x["label"].strip().lower() for x in act["targets"]]
        return (
            is_media_url(act["image"])
            and 1 <= len(labels) <= 10
            and len(set(labels)) == len(labels)
            and all(0 <= x["x"] <= 100 and 0 <= x["y"] <= 100 and 2 <= x["r"] <= 25 for x in act["targets"])
        )
    return True


# (lat_min, lat_max, lon_min, lon_max) — generous boxes; catches swapped/hallucinated coordinates.
MAP_BOUNDS = {
    "india": (6.0, 37.5, 68.0, 97.5),
    "tamil_nadu": (8.0, 13.6, 76.2, 80.4),
    "world": (-90.0, 90.0, -180.0, 180.0),
}
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def is_media_url(u: str) -> bool:
    return bool(re.fullmatch(r"/api/media/[0-9a-f]{32}\.(webp|png|jpg)", u or ""))


def _tree_ok(tree: list[dict]) -> bool:
    """Unique ids, ≥2 choices per node, every next exists, no cycles, ≥1 ending."""
    ids = [n["id"] for n in tree]
    if not tree or len(ids) != len(set(ids)) or len(tree) > 10:
        return False
    nodes = {n["id"]: n for n in tree}
    if any(
        len(n["choices"]) < 2 or any(c["next"] and c["next"] not in nodes for c in n["choices"]) for n in tree
    ):
        return False

    def ends(nid, seen):
        if nid in seen:
            return False  # cycle
        return all((not c["next"]) or ends(c["next"], seen | {nid}) for c in nodes[nid]["choices"])

    has_end = any(not c["next"] for n in tree for c in n["choices"])
    return has_end and ends(tree[0]["id"], frozenset())


def generate_lesson(subsection_id: int) -> None:
    sub = Subsection.objects.select_related("section__curriculum").get(id=subsection_id)
    cur = sub.section.curriculum
    material = ""
    if _source_doc_ok(cur):
        from apps.docs.search import top_chunks

        material = "\n---\n".join(
            c.text for c in top_chunks(cur.source_document, f"{sub.title} {sub.objective}", k=6)
        )
    position = (
        Subsection.objects.filter(section__curriculum=cur)
        .filter(
            models.Q(section__order__lt=sub.section.order)
            | models.Q(section=sub.section, order__lt=sub.order)
        )
        .count()
    )
    interactive = interactive_for(cur.domain, cur.title, position)
    from apps.studio.context import generation_extras

    rules, extra = generation_extras(cur, f"{sub.title} {sub.objective}")
    material = "\n\n".join(x for x in (material, extra) if x)
    from apps.adaptive.models import ConceptLink

    concepts = [
        (lk.concept.key, lk.concept.title)
        for lk in ConceptLink.objects.filter(subsection=sub).select_related("concept")
    ]
    system, user = lesson_prompts(
        cur.title,
        sub.section.title,
        sub.title,
        sub.objective,
        cur.level,
        cur.domain,
        cur.language,
        material,
        interactive,
        concepts,
    )
    if rules:
        user = f"{user}\n\n{rules}"
    try:
        pkg = complete_json_sync("author", system, user, FlatLessonPackage, max_tokens=8000, effort="medium")
    except Exception as e:
        code = e.code if isinstance(e, LLMError) else "internal_error"
        log.exception("lesson generation failed for %s: %s", subsection_id, code)
        Subsection.objects.filter(id=subsection_id).update(
            lesson_status=Subsection.LessonStatus.FAILED, error=code
        )
        return
    acts, hints = [], []
    for f in pkg.activities:
        typed = to_typed(f)
        if typed and _valid(typed):
            acts.append(typed)
            hints.append(f.concept)
        else:  # visible instead of silent: which activity the model got wrong
            log.warning(
                "dropped invalid %s activity in lesson %s (%s)",
                f.type,
                subsection_id,
                "unparseable" if not typed else "failed checks",
            )
    acts = acts[:5]
    with transaction.atomic():
        sub.activities.filter(kind="lesson").delete()
        for i, act in enumerate(acts):
            payload, key = activities.build(act, seed=sub.id * 100 + i)
            Activity.objects.create(
                subsection=sub,
                order=i,
                type=act["type"],
                title=act["title"][:200],
                payload=payload,
                key=key,
                source=act,
            )
        sub.explanation_md = pkg.explanation_md
        sub.key_points = pkg.key_points[:6]
        sub.lesson_status = Subsection.LessonStatus.READY
        sub.error = ""
        sub.save()
        send_back_for_review(cur)  # AI-rewritten lesson text and answer keys need review again
    from apps.adaptive.graph import tag_activities

    tag_activities(sub, dict(enumerate(hints[:5])))
    if cur.kind == Curriculum.Kind.AUTHORED:
        from apps.studio.history import record

        record(cur, f"AI lesson: {sub.title}"[:120])


PRACTICE_TYPES = {"quiz", "fill_blank", "sequencing", "categorization", "matching", "diagram"}


def generate_practice(subsection_id: int) -> None:
    """Append a fresh auto-graded practice set to an already-studied lesson."""
    sub = Subsection.objects.select_related("section__curriculum").get(id=subsection_id)
    cur = sub.section.curriculum
    system, user = practice_prompts(
        cur.title, sub.title, sub.objective, sub.key_points, cur.level, cur.language
    )
    try:
        pkg = complete_json_sync("author", system, user, FlatLessonPackage, max_tokens=6000, effort="medium")
    except Exception as e:
        code = e.code if isinstance(e, LLMError) else "internal_error"
        log.exception("practice generation failed for %s: %s", subsection_id, code)
        Subsection.objects.filter(id=subsection_id).update(practice_status="failed")
        return
    acts = [
        a for a in (to_typed(f) for f in pkg.activities) if a and a["type"] in PRACTICE_TYPES and _valid(a)
    ][:5]
    with transaction.atomic():
        start = (sub.activities.order_by("-order").values_list("order", flat=True).first() or 0) + 1
        for i, act in enumerate(acts):
            payload, key = activities.build(act, seed=sub.id * 1000 + start + i)
            Activity.objects.create(
                subsection=sub,
                order=start + i,
                kind="practice",
                type=act["type"],
                title=act["title"][:200],
                payload=payload,
                key=key,
                source=act,
            )
        Subsection.objects.filter(id=subsection_id).update(practice_status="ready")
