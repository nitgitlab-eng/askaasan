"""Course <-> JSON. Used for undo/redo, named versions, templates, the lesson picker and import/export.

Format (aasan-course v1):
{format, version, course: {title, description, goal, level, language, cover_emoji, skills},
 sections: [{id?, title, summary, archived, lessons: [{id?, title, objective, skills, explanation_md, key_points,
            lesson_status, archived, activities: [{id?, type, kind, title, source, payload?, key?}]}]}]}

`apply(..., trusted=True)` (our own revisions) keeps payload/key as stored so learners' attempts stay valid — unless the
revision was written by an older activity builder (its "build" differs from BUILD): then activities that still have a
valid `source` are rebuilt, so a restore can't bring back payloads from before a builder fix.
Untrusted input (imports, other people's templates) is rebuilt from `source` through the same validation as AI output.
"""

from django.db import transaction

from apps.learning import activities as acts
from apps.learning.models import Activity, Curriculum, Section, Subsection, next_order

FORMAT, VERSION = "aasan-course", 1
BUILD = 1  # bump whenever activities.build() changes how payload/key are derived from a source
MAX_SECTIONS, MAX_LESSONS, MAX_ACTS = 40, 60, 20
COURSE_FIELDS = ("title", "description", "goal", "level", "language", "cover_emoji", "skills")


class SnapshotError(ValueError):
    pass


def lesson_data(sub: Subsection, with_ids=True, with_keys=True) -> dict:
    out = {
        "title": sub.title,
        "objective": sub.objective,
        "skills": sub.skills,
        "explanation_md": sub.explanation_md,
        "key_points": sub.key_points,
        "lesson_status": sub.lesson_status if sub.lesson_status in ("ready", "empty") else "empty",
        "archived": sub.archived,
        "activities": [],
    }
    if with_ids:
        out["id"] = sub.id
    for a in sub.activities.filter(kind="lesson").order_by("order"):
        ad = {"type": a.type, "kind": a.kind, "title": a.title, "source": a.source}
        if with_ids:
            ad["id"] = a.id
        if with_keys:
            ad["payload"], ad["key"] = a.payload, a.key
        out["activities"].append(ad)
    return out


def serialize(cur: Curriculum, with_ids=True, with_keys=True) -> dict:
    return {
        "format": FORMAT,
        "version": VERSION,
        "build": BUILD,
        "course": {k: getattr(cur, k) for k in COURSE_FIELDS},
        "sections": [
            {
                **({"id": s.id} if with_ids else {}),
                "title": s.title,
                "summary": s.summary,
                "archived": s.archived,
                "lessons": [lesson_data(b, with_ids, with_keys) for b in s.subsections.order_by("order")],
            }
            for s in cur.sections.order_by("order")
        ],
    }


def _typed(src) -> dict | None:
    from apps.learning.lab_api import _validate_source

    if not isinstance(src, dict) or not src.get("type"):
        return None
    typed, _err = _validate_source(src)
    return typed


def validate(data: dict) -> dict:
    """Shape/size checks for untrusted input; raises SnapshotError with a human message."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise SnapshotError("Not an Aasan course file (missing format: aasan-course).")
    secs = data.get("sections")
    if not isinstance(secs, list) or not secs:
        raise SnapshotError("The course has no sections.")
    if (
        len(secs) > MAX_SECTIONS
        or sum(len(s.get("lessons") or []) for s in secs if isinstance(s, dict)) > MAX_LESSONS * 4
    ):
        raise SnapshotError("The course is too large to import.")
    for s in secs:
        if not isinstance(s, dict) or not _txt(s.get("title"), 200).strip():
            raise SnapshotError("Every section needs a title.")
        for b in s.get("lessons") or []:
            if not isinstance(b, dict) or not _txt(b.get("title"), 200).strip():
                raise SnapshotError(f"Every lesson in '{s['title']}' needs a title.")
            if len(b.get("activities") or []) > MAX_ACTS:
                raise SnapshotError(f"Lesson '{b['title']}' has too many activities.")
    return data


def _txt(v, n):
    """Plain scalars only — never str() a list/dict (an imported structure could expand to gigabytes)."""
    return str(v)[:n] if isinstance(v, (str, int, float)) and v != "" else ""


def _strs(v, each, most):
    return [_txt(x, each) for x in v[:most] if _txt(x, each)] if isinstance(v, list) else []


def load_yaml(text: str):
    """safe_load, but anchors/aliases are refused (an alias "bomb" can expand a few hundred bytes into gigabytes)."""
    import yaml

    class _NoAliases(yaml.SafeLoader):
        def compose_node(self, parent, index):
            if self.check_event(yaml.AliasEvent):
                raise SnapshotError("YAML aliases (*name) aren't supported in imports.")
            ev = self.peek_event()
            if getattr(ev, "anchor", None):
                raise SnapshotError("YAML anchors (&name) aren't supported in imports.")
            return super().compose_node(parent, index)

    # _NoAliases subclasses SafeLoader, so this is safe_load with aliases refused.
    return yaml.load(text, Loader=_NoAliases)  # nosec B506


def _write_activities(
    sub: Subsection, items: list, trusted: bool, existing: dict[int, Activity], stale: bool = False
) -> int:
    """Create/update a lesson's activities in order. Returns how many untrusted ones were dropped as invalid.
    stale (trusted revision from an older builder): rebuild from `source` when it still validates, else keep stored."""
    keep, dropped = [], 0
    for i, ad in enumerate(items[:MAX_ACTS]):
        a = existing.get(ad.get("id")) if trusted else None
        rebuilt = _typed(ad.get("source")) if trusted and stale else None
        if rebuilt:
            payload, key = acts.build(rebuilt, seed=sub.id * 100 + i)
            typ, src = rebuilt["type"], rebuilt
        elif trusted and "payload" in ad and "key" in ad:
            payload, key, typ, src = ad["payload"], ad["key"], ad["type"], ad.get("source")
        else:
            typed = _typed(ad.get("source"))
            if not typed:
                dropped += 1
                continue
            payload, key = acts.build(typed, seed=sub.id * 100 + i)
            typ, src = typed["type"], typed
        title = _txt(ad.get("title") or (src or {}).get("title"), 200)
        if a:
            a.subsection, a.order, a.type, a.title, a.payload, a.key, a.source, a.kind = (
                sub,
                i,
                typ,
                title,
                payload,
                key,
                src,
                "lesson",
            )
            a.save()
        else:
            a = Activity.objects.create(
                subsection=sub,
                order=i,
                type=typ,
                kind="lesson",
                title=title,
                payload=payload,
                key=key,
                source=src,
            )
        keep.append(a.id)
    sub.activities.filter(kind="lesson").exclude(id__in=keep).delete()
    return dropped


@transaction.atomic
def apply(cur: Curriculum, data: dict, trusted: bool, course_fields=True) -> int:
    """Make `cur` match `data`. Trusted = our own revision (match rows by id); otherwise ids are ignored."""
    if course_fields:
        c = data.get("course") or {}
        for k in COURSE_FIELDS:
            if k in c:
                v = c[k]
                if k == "skills":
                    v = _strs(v, 60, 8)
                elif (
                    k == "level"
                    and v not in ("beginner", "intermediate", "advanced")
                    or k == "language"
                    and v not in ("en", "ta", "tanglish")
                ):
                    continue
                else:
                    v = _txt(v, {"title": 200, "goal": 300, "cover_emoji": 8}.get(k, 4000))
                setattr(cur, k, v)
        cur.save()
    sec_rows = {s.id: s for s in cur.sections.all()}
    sub_rows = {b.id: b for b in Subsection.objects.filter(section__curriculum=cur)}
    act_rows = {a.id: a for a in Activity.objects.filter(subsection__section__curriculum=cur, kind="lesson")}
    keep_secs, keep_subs, dropped = [], [], 0
    for si, sd in enumerate((data.get("sections") or [])[:MAX_SECTIONS]):
        sec = sec_rows.get(sd.get("id")) if trusted else None
        if sec:
            sec.order, sec.title, sec.summary, sec.archived = (
                si,
                _txt(sd.get("title"), 200),
                _txt(sd.get("summary"), 2000),
                bool(sd.get("archived")),
            )
            sec.save()
        else:
            sec = Section.objects.create(
                curriculum=cur,
                order=si,
                title=_txt(sd.get("title"), 200),
                summary=_txt(sd.get("summary"), 2000),
                archived=bool(sd.get("archived")),
            )
        keep_secs.append(sec.id)
        for bi, bd in enumerate((sd.get("lessons") or [])[:MAX_LESSONS]):
            sub = sub_rows.get(bd.get("id")) if trusted else None
            fields = {
                "section": sec,
                "order": bi,
                "title": _txt(bd.get("title"), 200),
                "objective": _txt(bd.get("objective"), 1000),
                "skills": _strs(bd.get("skills"), 60, 4),
                "explanation_md": _txt(bd.get("explanation_md"), 20000),
                "key_points": _strs(bd.get("key_points"), 300, 8),
                "archived": bool(bd.get("archived")),
            }
            status = "ready" if (fields["explanation_md"] or bd.get("activities")) else "empty"
            if sub:
                for k, v in fields.items():
                    setattr(sub, k, v)
                if sub.lesson_status not in ("generating",):
                    sub.lesson_status = status
                sub.save()
            else:
                sub = Subsection.objects.create(lesson_status=status, **fields)
            keep_subs.append(sub.id)
            dropped += _write_activities(
                sub, bd.get("activities") or [], trusted, act_rows, stale=data.get("build") != BUILD
            )
    Subsection.objects.filter(section__curriculum=cur).exclude(id__in=keep_subs).delete()
    cur.sections.exclude(id__in=keep_secs).delete()
    # Any content rewrite (undo/redo/restore included) sends an approved catalog course back for review.
    if Curriculum.objects.filter(pk=cur.pk, catalog_status=Curriculum.CatalogStatus.APPROVED).update(
        catalog_status=Curriculum.CatalogStatus.PENDING,
        catalog_note="Changed after approval — waiting for review again.",
    ):
        cur.catalog_status = Curriculum.CatalogStatus.PENDING
    return dropped


def copy_lesson(src: Subsection, section: Section) -> Subsection:
    """Lesson picker: deep-copy a lesson (activities rebuilt from source) to the end of a section."""

    order = next_order(section.subsections)
    d = lesson_data(src, with_ids=False, with_keys=False)
    sub = Subsection.objects.create(
        section=section,
        order=order,
        title=d["title"],
        objective=d["objective"],
        skills=d["skills"],
        explanation_md=d["explanation_md"],
        key_points=d["key_points"],
        lesson_status="ready" if d["explanation_md"] or d["activities"] else "empty",
    )
    _write_activities(sub, d["activities"], trusted=False, existing={})
    return sub


def from_outline(text: str, title: str = "") -> dict:
    """Pasted outline → course data. '# Section' / 'Section:' headings, '- Lesson' or '1. Lesson' items, optional ': objective'."""
    import re

    sections, cur = [], None
    for raw in text.splitlines()[:600]:
        line = raw.rstrip()
        if not line.strip():
            continue
        m_sec = re.match(r"^\s*(#{1,3})\s+(.+)$", line) or re.match(
            r"^(?:section|module|unit|week)\s*\d*\s*[:.\-]\s*(.+)$", line.strip(), re.IGNORECASE
        )
        m_les = re.match(r"^\s*(?:[-*•]|\d+[.)])\s+(.+)$", line)
        if m_sec and not m_les:
            cur = {"title": m_sec.groups()[-1].strip()[:200], "summary": "", "lessons": []}
            sections.append(cur)
        elif m_les:
            if cur is None:
                cur = {"title": "Section 1", "summary": "", "lessons": []}
                sections.append(cur)
            item = m_les.group(1).strip()
            t, _, obj = item.partition(":")
            cur["lessons"].append(
                {"title": t.strip()[:200], "objective": obj.strip()[:1000], "activities": []}
            )
        elif cur is not None and not cur["lessons"]:
            cur["summary"] = (cur["summary"] + " " + line.strip()).strip()[:1000]
    if not sections:
        raise SnapshotError("Couldn't find any sections or lessons. Use '# Section' and '- Lesson' lines.")
    return {
        "format": FORMAT,
        "version": VERSION,
        "course": {"title": title[:200] or sections[0]["title"]},
        "sections": sections,
    }
