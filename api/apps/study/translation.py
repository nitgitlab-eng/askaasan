"""On-the-fly lesson translation, shared and cached per (lesson, language).

Only learner-facing *text* is translated; ids, code, URLs and answer keys stay untouched, so grading
is language-neutral. Text answers (categories, concept-map labels) are mapped back to the original,
and fill-in-the-blank gets translated accepted answers added at grading time."""

import copy
import hashlib
import json
import logging
import re

from django.db import transaction
from django.utils import timezone

from .models import LANGS, LessonTranslation

log = logging.getLogger(__name__)

# Keys whose values are identifiers / code / data — never translated (also skips their whole subtree).
SKIP_KEYS = {
    "id",
    "ids",
    "blank_ids",
    "next",
    "start",
    "mermaid",
    "video_id",
    "image",
    "link",
    "language",
    "starter_code",
    "expected_output",
    "region",
    "lat",
    "lon",
    "viz",
    "proof",
    "at",
    "end",
    "multiple",
    "x",
    "y",
    "r",
    "checklist",
}
CHUNK_ITEMS, CHUNK_CHARS = 60, 7000
STALE_AFTER_S = 600
HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
PLACEHOLDER = re.compile(r"\[\[[^\]]+\]\]")


def _collect(obj, path=()):
    """Yield (path, text) for every translatable string in a JSON value."""
    if isinstance(obj, str):
        if HAS_LETTER.search(obj):
            yield path, obj
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _collect(v, (*path, i))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k not in SKIP_KEYS:
                yield from _collect(v, (*path, k))


def _set(obj, path, value):
    for p in path[:-1]:
        obj = obj[p]
    obj[path[-1]] = value


def source_hash(sub) -> str:
    acts = [
        (a.id, a.title, a.payload, (a.key or {}).get("explanation", ""), (a.key or {}).get("blanks"))
        for a in sub.activities.filter(kind="lesson").order_by("order")
    ]
    raw = json.dumps(
        [2, sub.title, sub.objective, sub.explanation_md, sub.key_points, sub.section.title, acts],
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _translate_strings(strings: list[str], lang: str) -> list[str]:
    from llm.prompts.study import TRANSLATE_SYSTEM, Translated
    from llm.structured import complete_json_sync

    out: list[str] = []
    i = 0
    while i < len(strings):
        chunk, size = [], 0
        while (
            i < len(strings)
            and len(chunk) < CHUNK_ITEMS
            and (not chunk or size + len(strings[i]) < CHUNK_CHARS)
        ):
            chunk.append(strings[i])
            size += len(strings[i])
            i += 1
        res = complete_json_sync(
            "author",
            TRANSLATE_SYSTEM.format(lang_name=LANGS[lang], n=len(chunk)),
            "STRINGS:\n" + json.dumps(chunk, ensure_ascii=False),
            Translated,
            max_tokens=12000,
        )
        got = res.translations
        if len(got) != len(chunk):
            raise ValueError(f"translation count mismatch {len(got)} != {len(chunk)}")
        for src, dst in zip(chunk, got, strict=True):
            # A translation that drops placeholders/code would break the activity — keep the original instead.
            ok = sorted(PLACEHOLDER.findall(src)) == sorted(PLACEHOLDER.findall(dst)) and src.count(
                "```"
            ) == dst.count("```")
            out.append(dst if ok and dst.strip() else src)
    return out


def translate(tr_id: int) -> None:
    """Background job: fill one LessonTranslation."""
    tr = LessonTranslation.objects.select_related("subsection").get(id=tr_id)
    sub = tr.subsection
    try:
        acts = list(sub.activities.filter(kind="lesson").order_by("order"))
        slots: list[tuple] = []  # (target, path, text)
        head = {
            "title": sub.title,
            "objective": sub.objective,
            "explanation_md": sub.explanation_md,
            "key_points": list(sub.key_points or []),
            "section": sub.section.title,
        }
        for path, text in _collect(head):
            slots.append(("head", path, text))
        payloads = {a.id: copy.deepcopy(a.payload) for a in acts}
        for a in acts:
            if HAS_LETTER.search(a.title or ""):
                slots.append((("title", a.id), (), a.title))
            for path, text in _collect(payloads[a.id]):
                slots.append((("payload", a.id), path, text))
            key = a.key or {}
            if key.get("explanation"):
                slots.append((("expl", a.id), (), key["explanation"]))
            for bid, answers in (key.get("blanks") or {}).items():
                for k, ans in enumerate(answers[:4]):
                    if HAS_LETTER.search(str(ans)):
                        slots.append((("accept", a.id), (bid, k), str(ans)))
        done = _translate_strings([s[2] for s in slots], tr.lang)

        out = {
            str(a.id): {
                "payload": payloads[a.id],
                "title": a.title,
                "explanation": "",
                "accept": {},
                "back": {},
            }
            for a in acts
        }
        for (target, path, src), dst in zip(slots, done, strict=True):
            if target == "head":
                _set(head, path, dst)
            elif target[0] == "payload":
                _set(out[str(target[1])]["payload"], path, dst)
                # Text the learner submits back as an answer → map to the original for grading.
                if len(path) == 2 and path[0] in ("categories", "labels") and isinstance(path[1], int):
                    out[str(target[1])]["back"][dst] = src
            elif target[0] == "title":
                out[str(target[1])]["title"] = dst
            elif target[0] == "expl":
                out[str(target[1])]["explanation"] = dst
            elif target[0] == "accept":
                out[str(target[1])]["accept"].setdefault(path[0], []).append(dst)
        tr.title, tr.objective, tr.explanation_md, tr.key_points = (
            head["title"],
            head["objective"],
            head["explanation_md"],
            head["key_points"],
        )
        tr.activities, tr.status, tr.error = (
            {**out, "_section": head["section"]},
            LessonTranslation.Status.READY,
            "",
        )
    except Exception as e:
        log.exception("translation %s failed", tr_id)
        tr.status, tr.error = LessonTranslation.Status.FAILED, str(e)[:300]
    tr.save()


def enqueue(tr_id: int) -> None:
    from django.conf import settings

    if getattr(settings, "LEARNING_JOBS_INLINE", False):
        translate(tr_id)
    elif settings.REDIS_URL:
        from .tasks import translate_lesson

        translate_lesson.delay(tr_id)
    else:
        from apps.learning.jobs import _thread

        _thread(translate, tr_id)


def ensure(sub, lang: str, user) -> LessonTranslation | None:
    """Return the translation (starting it if needed). None when not applicable."""
    from apps.providers.services import BudgetExceeded, charge

    if lang not in LANGS or lang == sub.section.curriculum.language or sub.lesson_status != "ready":
        return None
    h = source_hash(sub)
    with transaction.atomic():
        tr = LessonTranslation.objects.select_for_update().filter(subsection=sub, lang=lang).first()
        stale = (
            tr
            and tr.status == "translating"
            and (timezone.now() - tr.updated_at).total_seconds() > STALE_AFTER_S
        )
        if tr and tr.source_hash == h and tr.status == "ready":
            return tr
        if tr and tr.status == "translating" and not stale:
            return tr
        try:
            charge(user, "translations", 1, TRANSLATIONS_PER_DAY)
        except BudgetExceeded:
            t = tr or LessonTranslation(subsection=sub, lang=lang, source_hash=h)
            t.status = "budget"  # not saved — just tells the client
            return t
        if tr:
            tr.status, tr.source_hash, tr.error = LessonTranslation.Status.TRANSLATING, h, ""
            tr.save()
        else:
            tr = LessonTranslation.objects.create(subsection=sub, lang=lang, source_hash=h)
    transaction.on_commit(lambda: enqueue(tr.id))
    return tr


TRANSLATIONS_PER_DAY = 30  # new (uncached) lesson translations a learner can trigger per day


def overlay(lesson: dict, tr: LessonTranslation) -> dict:
    """Swap learner-facing text for the translated version (ids/attempts unchanged)."""
    out = {
        **lesson,
        "title": tr.title or lesson["title"],
        "objective": tr.objective or lesson["objective"],
        "explanation_md": tr.explanation_md or lesson["explanation_md"],
        "key_points": tr.key_points or lesson["key_points"],
    }
    acts = []
    for a in lesson["activities"]:
        t = tr.activities.get(str(a["id"]))
        acts.append({**a, "payload": t["payload"], "title": t.get("title") or a["title"]} if t else a)
    out["activities"] = acts
    if tr.activities.get("_section"):
        out["section"] = {**lesson["section"], "title": tr.activities["_section"]}
    return out


def grading_view(activity, answer: dict, lang: str):
    """For an answer given in a translated lesson: (answer mapped to the original, extra accepted blanks, translated explanation)."""
    if not lang or lang not in LANGS:
        return answer, None, None
    tr = LessonTranslation.objects.filter(
        subsection_id=activity.subsection_id, lang=lang, status="ready"
    ).first()
    t = tr and tr.activities.get(str(activity.id))
    if not t:
        return answer, None, None
    back = t.get("back") or {}
    ans = copy.deepcopy(answer)
    for field in ("assign", "labels"):
        if isinstance(ans.get(field), dict):
            ans[field] = {k: back.get(v, v) for k, v in ans[field].items()}
    return ans, t.get("accept") or None, t.get("explanation") or None
