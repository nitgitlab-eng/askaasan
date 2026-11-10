"""Milestone 9 — company knowledge base: org documents read in the background (queued → reading → ready / failed),
key topics extracted by AI once per document (cached), and a topic ↔ document graph for the cockpit.

Ready documents are ordinary shared OrgDocuments, so members can ask the mentor about them (extras.viewable_documents)."""

import logging

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.docs.extract import MAX_BYTES, MAX_CHARS, ExtractError, chunk, extract, sniff

from .models import OrgDocument
from .perms import require

log = logging.getLogger(__name__)
MAX_KB_DOCS = 50
TOPICS_PER_DAY = 100  # per uploader: AI topic extraction allowance


def kb_out(od) -> dict:
    return {
        "id": od.id,
        "title": od.title,
        "filename": od.filename,
        "kind": od.kind,
        "size": od.size,
        "status": od.status,
        "error": od.error,
        "document_id": od.document_id,
        "pages": od.document.pages if od.document_id else 0,
        "topics": od.topics if od.topics_done else [],
        "learners_can_read": od.learners_can_read,
        "created_at": od.created_at,
    }


@api_view(["GET", "POST"])
@parser_classes([MultiPartParser, JSONParser])
def knowledge(request, slug):
    if request.method == "GET":
        me = require(request.user, slug, "manager")
        qs = (
            me.org.documents.filter(source="kb")
            .select_related("document")
            .defer("raw")
            .order_by("-created_at")
        )
        return Response([kb_out(od) for od in qs])
    me = require(request.user, slug, "admin")
    f = request.FILES.get("file")
    if not f:
        return Response({"code": "no_file"}, status=status.HTTP_400_BAD_REQUEST)
    if f.size > MAX_BYTES:
        return Response({"code": "too_large"}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
    if me.org.documents.filter(source="kb").count() >= MAX_KB_DOCS:
        return Response({"code": "too_many_documents"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    data = f.read(MAX_BYTES + 1)
    name = (f.name or "document.txt")[-200:]
    try:
        kind = sniff(data, name)  # magic bytes decide (PDF / DOCX zip); .txt/.md must be UTF-8 text
    except ExtractError as e:
        return Response({"code": e.code}, status=status.HTTP_400_BAD_REQUEST)
    title = (str(request.data.get("title") or "") or name.rsplit(".", 1)[0]).strip()[:200] or "Document"
    od = OrgDocument.objects.create(
        org=me.org,
        source="kb",
        shared_by=request.user,
        title=title,
        filename=name,
        kind=kind,
        size=len(data),
        status="queued",
        raw=data,
        learners_can_read=str(request.data.get("learners_can_read", "")).lower() in ("true", "1", "on"),
    )  # staff-only by default
    from apps.study.jobs import enqueue

    transaction.on_commit(lambda: enqueue("apps.orgs.knowledge.build", od.id))
    return Response(kb_out(od), status=status.HTTP_202_ACCEPTED)


@api_view(["GET", "PATCH", "DELETE"])
def knowledge_detail(request, slug, pk):
    me = require(request.user, slug, "manager" if request.method == "GET" else "admin")
    od = get_object_or_404(
        OrgDocument.objects.select_related("document").defer("raw"), pk=pk, org=me.org, source="kb"
    )
    if request.method == "DELETE":
        with transaction.atomic():
            if od.document_id:
                od.document.delete()  # cascades to this OrgDocument and the chunks
            else:
                od.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    if request.method == "PATCH":  # who may read it: staff only, or learners too (cohort partners never)
        v = request.data.get("learners_can_read")
        if not isinstance(v, bool):
            return Response({"code": "bad_value"}, status=status.HTTP_400_BAD_REQUEST)
        od.learners_can_read = v
        od.save(update_fields=["learners_can_read"])
    return Response(kb_out(od))


@api_view(["GET"])
def knowledge_graph(request, slug):
    """Topics ↔ documents: nodes for every ready document and its (cached) topics, merged case-insensitively."""
    me = require(request.user, slug, "manager")
    docs = list(
        me.org.documents.filter(source="kb", status="ready", topics_done=True)
        .defer("raw")
        .order_by("-created_at")[:MAX_KB_DOCS]
    )
    topics: dict[str, dict] = {}
    links = []
    for od in docs:
        for t in od.topics:
            key = t.casefold()
            row = topics.setdefault(key, {"key": key, "label": t, "count": 0})
            row["count"] += 1
            links.append({"doc": od.id, "topic": key})
    keep = {t["key"] for t in sorted(topics.values(), key=lambda r: -r["count"])[:60]}
    return Response(
        {
            "documents": [{"id": od.id, "title": od.title} for od in docs],
            "topics": [t for t in topics.values() if t["key"] in keep],
            "links": [x for x in links if x["topic"] in keep],
        }
    )


# ── Background job ───────────────────────────────────────────────────


def clean_topics(raw: list[str]) -> list[str]:
    out, seen = [], set()
    for t in raw:
        t = " ".join(str(t).split())[:40].strip(" .,;:-")
        if len(t) >= 2 and t.casefold() not in seen:
            seen.add(t.casefold())
            out.append(t)
    return out[:8]


def _topics(od, text: str):
    from apps.providers.services import BudgetExceeded, charge
    from llm.base import LLMError
    from llm.prompts.orgs import KB_TOPICS_SYSTEM, KbTopics
    from llm.structured import complete_json_sync

    try:
        if od.shared_by_id:
            charge(od.shared_by, "kb_topics", 1, TOPICS_PER_DAY)
        out = complete_json_sync(
            "suggest",
            KB_TOPICS_SYSTEM,
            f"Title: {od.title}\n<document>\n{text[:6000]}\n</document>",
            KbTopics,
            max_tokens=600,
        )
    except (BudgetExceeded, LLMError):
        log.info("kb topics skipped for %s", od.id)
        return
    OrgDocument.objects.filter(pk=od.pk).update(topics=clean_topics(out.topics), topics_done=True)


def build(od_id: int):
    """queued → reading → ready (Document + chunks created, raw bytes dropped) or failed (with an error code)."""
    from apps.docs.models import Chunk, Document

    if not OrgDocument.objects.filter(pk=od_id, status="queued").update(status="reading"):
        return  # already claimed by another worker (or deleted)
    od = OrgDocument.objects.select_related("shared_by").get(pk=od_id)
    try:
        if not od.shared_by_id:
            raise ExtractError("no_owner")
        pages = extract(bytes(od.raw or b""), od.kind)
        text_len = sum(len(t) for _, t in pages)
        if text_len < 50:
            raise ExtractError("no_text")  # e.g. a scanned PDF
        if text_len > MAX_CHARS:
            raise ExtractError("too_much_text")
        parts = chunk(pages)
        from apps.docs.embeddings import embed

        vectors = embed([t for _, t in parts]) or [None] * len(parts)
        with transaction.atomic():
            doc = Document.objects.create(
                owner=od.shared_by,
                title=od.title,
                filename=od.filename,
                kind=od.kind,
                pages=sum(1 for p, _ in pages if p) or 0,
                chars=text_len,
            )
            Chunk.objects.bulk_create(
                [
                    Chunk(document=doc, index=i, page=p, text=t, embedding=vectors[i])
                    for i, (p, t) in enumerate(parts)
                ]
            )
            OrgDocument.objects.filter(pk=od.pk).update(document=doc, status="ready", error="", raw=None)
    except ExtractError as e:
        OrgDocument.objects.filter(pk=od.pk).update(status="failed", error=e.code, raw=None)
        return
    except Exception:  # never leave a document stuck in "reading"
        log.warning("kb build %s failed", od_id, exc_info=True)
        OrgDocument.objects.filter(pk=od.pk).update(status="failed", error="read_failed", raw=None)
        return
    _topics(od, "\n".join(t for _, t in parts))
