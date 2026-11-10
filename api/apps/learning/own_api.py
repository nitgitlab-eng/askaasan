"""Learners shaping their OWN (personal) courses: AI 'add a section', hide/unhide, undo/redo, attach/detach sources."""

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Curriculum, Section, Subsection, next_order

EDITS_PER_DAY = 15


def _own(request, pk) -> Curriculum:
    return get_object_or_404(Curriculum, pk=pk, owner=request.user, kind=Curriculum.Kind.PERSONAL)


def _id(v) -> int | None:
    """A client-sent id as int, or None (so '1abc' is a 400/404, not a ValueError 500)."""
    try:
        return int(v) if v is not None and not isinstance(v, bool) else None
    except (TypeError, ValueError):
        return None


def _record(cur, label, user):
    from apps.studio import history

    history.record(cur, label, user)


def _state(cur):
    from apps.studio import history

    return history.state(cur)


@api_view(["GET"])
def edit_state(request, pk):
    cur = _own(request, pk)
    hidden = [{"id": s.id, "title": s.title, "kind": "section"} for s in cur.sections.filter(archived=True)]
    hidden += [
        {"id": b.id, "title": b.title, "kind": "lesson"}
        for b in Subsection.objects.filter(section__curriculum=cur, archived=True)
    ]
    docs = [{"id": d.id, "title": d.title} for d in cur.documents.all()]
    return Response({**_state(cur), "hidden": hidden, "sources": docs})


@api_view(["POST"])
def add_section(request, pk):
    """AI writes one new section (lessons are generated when opened, as usual)."""
    from apps.providers.services import BudgetExceeded, charge
    from llm.prompts.curriculum import ADD_SECTION_SYSTEM, LANG_RULE, OutlineSection
    from llm.structured import complete_json_sync

    cur = _own(request, pk)
    ask = str(request.data.get("request") or "").strip()[:400]
    if len(ask) < 3:
        return Response({"code": "describe_it"}, status=status.HTTP_400_BAD_REQUEST)
    if cur.sections.count() >= 30:
        return Response({"code": "too_many_sections"}, status=status.HTTP_409_CONFLICT)
    try:
        charge(request.user, "course_edits", 1, EDITS_PER_DAY)
    except BudgetExceeded:
        return Response({"code": "edit_budget"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    outline = "\n".join(
        f"- {s.title}: " + "; ".join(b.title for b in s.subsections.all()) for s in cur.sections.all()
    )
    try:
        sec = complete_json_sync(
            "author",
            ADD_SECTION_SYSTEM.format(lang_rule=LANG_RULE.get(cur.language, LANG_RULE["en"])),
            f"Course: {cur.title}\nGoal: {cur.goal}\nLevel: {cur.level}\nOutline:\n{outline[:5000]}\n\nLearner's request: {ask}",
            OutlineSection,
            max_tokens=2500,
        )
    except Exception:  # noqa: BLE001
        return Response({"code": "ai_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    from apps.studio import history

    with transaction.atomic():
        history.ensure_baseline(cur, request.user)  # so the very first edit can be undone
        s = Section.objects.create(
            curriculum=cur, order=next_order(cur.sections), title=sec.title[:200], summary=sec.summary[:2000]
        )
        for i, b in enumerate(sec.subsections[:5]):
            Subsection.objects.create(
                section=s,
                order=i,
                title=b.title[:200],
                objective=b.objective[:1000],
                skills=[x[:60] for x in b.skills[:3]],
            )
        _record(cur, f"Add section “{s.title}”"[:120], request.user)
    return Response({"section_id": s.id, **_state(cur)}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def toggle_hidden(request, pk):
    """{kind: section|lesson, id, hidden: bool} — hide what you don't need; nothing is deleted."""
    cur = _own(request, pk)
    kind, hidden = request.data.get("kind"), bool(request.data.get("hidden"))
    model = Section if kind == "section" else Subsection if kind == "lesson" else None
    if not model:
        return Response({"code": "bad_kind"}, status=status.HTTP_400_BAD_REQUEST)
    flt = {"curriculum": cur} if model is Section else {"section__curriculum": cur}
    obj = get_object_or_404(model, pk=_id(request.data.get("id")), **flt)
    if model is Section and hidden and cur.sections.filter(archived=False).count() <= 1:
        return Response({"code": "keep_one_section"}, status=status.HTTP_409_CONFLICT)
    from apps.studio import history

    with transaction.atomic():
        history.ensure_baseline(cur, request.user)
        obj.archived = hidden
        obj.save(update_fields=["archived"])
        _record(cur, f"{'Hide' if hidden else 'Show'} “{obj.title}”"[:120], request.user)
    return Response(_state(cur))


@api_view(["POST"])
def reorder_lessons(request, pk):
    """{section_id, lesson_ids: [...]} — put the (visible) lessons of one section of MY course in a new order (undoable)."""
    cur = _own(request, pk)
    sec = get_object_or_404(Section, pk=_id(request.data.get("section_id")), curriculum=cur)
    ids = request.data.get("lesson_ids")
    subs = list(sec.subsections.order_by("order"))
    visible = [b.id for b in subs if not b.archived]
    if (
        not isinstance(ids, list)
        or sorted(i for i in ids if isinstance(i, int)) != sorted(visible)
        or len(ids) != len(visible)
    ):
        return Response({"code": "bad_order"}, status=status.HTTP_400_BAD_REQUEST)
    if ids == visible:
        return Response(_state(cur))
    from apps.studio import history

    by_id = {b.id: b for b in subs}
    new = [by_id[i] for i in ids] + [
        b for b in subs if b.archived
    ]  # hidden lessons keep their place at the end
    with transaction.atomic():
        history.ensure_baseline(cur, request.user)
        for i, b in enumerate(new):
            if b.order != i:
                Subsection.objects.filter(pk=b.pk).update(order=i)
        _record(cur, f"Reorder lessons in “{sec.title}”"[:120], request.user)
    return Response(_state(cur))


@api_view(["POST"])
def undo_redo(request, pk, direction):
    from apps.studio import history

    if direction not in ("undo", "redo"):
        return Response(status=status.HTTP_404_NOT_FOUND)
    cur = _own(request, pk)
    with transaction.atomic():
        ok = history.step(cur, -1 if direction == "undo" else 1)
    if not ok:
        return Response({"code": f"nothing_to_{direction}"}, status=status.HTTP_409_CONFLICT)
    return Response(_state(cur))


@api_view(["POST", "DELETE"])
def sources(request, pk):
    """Attach / detach one of my documents; new lessons are grounded in attached sources."""
    from apps.orgs.extras import viewable_documents

    cur = _own(request, pk)
    doc_id = _id(request.data.get("document_id") or request.query_params.get("document_id"))
    # Attach only what I may read right now (own notes + what my orgs let me read; an ex-admin's knowledge-base upload
    # doesn't count). Detaching works for anything already attached.
    docs = viewable_documents(request.user) if request.method == "POST" else cur.documents.all()
    doc = get_object_or_404(docs, pk=doc_id)
    if request.method == "POST":
        if cur.documents.count() >= 5:
            return Response({"code": "max_5_sources"}, status=status.HTTP_409_CONFLICT)
        cur.documents.add(doc)
    else:
        cur.documents.remove(doc)
    return Response({"sources": [{"id": d.id, "title": d.title} for d in cur.documents.all()]})
