from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, throttle_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from .extract import MAX_BYTES, MAX_CHARS, ExtractError, chunk, extract, sniff
from .models import Chunk, Document

MAX_DOCS_PER_USER = 30


def _out(d):
    return {
        "id": d.id,
        "title": d.title,
        "filename": d.filename,
        "kind": d.kind,
        "pages": d.pages,
        "chars": d.chars,
        "created_at": d.created_at,
    }


class UploadThrottle(UserRateThrottle):
    """Each upload is parsed on the request thread (PDF extraction can take seconds): cap uploads, not listing."""

    scope = "doc_upload"
    rate = "20/hour"

    def allow_request(self, request, view):
        return request.method != "POST" or super().allow_request(request, view)


@api_view(["GET", "POST"])
@parser_classes([MultiPartParser])
@throttle_classes([UploadThrottle])
def documents(request):
    if request.method == "GET":
        return Response(
            [_out(d) for d in Document.objects.filter(owner=request.user).exclude(shared_in__source="kb")]
        )  # org knowledge base lives in the cockpit
    from apps.orgs.extras import refusal_response

    if denied := refusal_response(request.user, "docs"):
        return denied
    f = request.FILES.get("file")
    if not f:
        return Response({"code": "no_file"}, status=status.HTTP_400_BAD_REQUEST)
    if f.size > MAX_BYTES:
        return Response({"code": "too_large"}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
    if (
        Document.objects.filter(owner=request.user).exclude(shared_in__source="kb").count()
        >= MAX_DOCS_PER_USER
    ):
        return Response({"code": "too_many_documents"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    from apps.billing.services import PlanLimit, check

    try:
        check(request.user, "documents")
    except PlanLimit as e:
        return Response(e.payload(), status=status.HTTP_402_PAYMENT_REQUIRED)
    data = f.read()
    name = (f.name or "notes.txt")[-200:]
    try:
        kind = sniff(data, name)
        pages = extract(data, kind)
    except ExtractError as e:
        return Response({"code": e.code}, status=status.HTTP_400_BAD_REQUEST)
    text_len = sum(len(t) for _, t in pages)
    if text_len < 50:
        return Response({"code": "no_text"}, status=status.HTTP_400_BAD_REQUEST)  # e.g. scanned PDF images
    if text_len > MAX_CHARS:
        return Response({"code": "too_much_text"}, status=status.HTTP_400_BAD_REQUEST)
    parts = chunk(pages)
    title = (request.data.get("title") or name.rsplit(".", 1)[0]).strip()[:200] or "Notes"
    from apps.billing.services import lock_user

    from .embeddings import embed

    vectors = embed([t for _, t in parts]) or [None] * len(
        parts
    )  # outside the lock: may call an embedding API
    with transaction.atomic():
        lock_user(
            request.user
        )  # re-check both limits under the user's row lock so parallel uploads can't all pass
        if (
            Document.objects.filter(owner=request.user).exclude(shared_in__source="kb").count()
            >= MAX_DOCS_PER_USER
        ):
            return Response({"code": "too_many_documents"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        try:
            check(request.user, "documents")
        except PlanLimit as e:
            return Response(e.payload(), status=status.HTTP_402_PAYMENT_REQUIRED)
        doc = Document.objects.create(
            owner=request.user,
            title=title,
            filename=name,
            kind=kind,
            pages=sum(1 for p, _ in pages if p) or 0,
            chars=text_len,
        )
        Chunk.objects.bulk_create(
            [
                Chunk(document=doc, index=i, page=p, text=t, embedding=vectors[i])
                for i, (p, t) in enumerate(parts)
            ]
        )
    return Response(_out(doc), status=status.HTTP_201_CREATED)


@api_view(["GET", "DELETE"])
def document_detail(request, pk):
    doc = get_object_or_404(
        Document.objects.exclude(shared_in__source="kb"), pk=pk, owner=request.user
    )  # KB docs: cockpit only
    if request.method == "DELETE":
        doc.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    preview = [{"index": c.index, "page": c.page, "text": c.text[:300]} for c in doc.chunks.all()[:3]]
    return Response({**_out(doc), "preview": preview, "chunks": doc.chunks.count()})
