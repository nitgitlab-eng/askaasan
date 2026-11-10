import logging
import re

from django.core.files.storage import default_storage
from django.http import FileResponse, Http404
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.learning.lab_api import IsCreator
from apps.providers.services import BudgetExceeded, charge, needs_key, resolve

from .images import ImageError, generate, process, store
from .models import MediaAsset

log = logging.getLogger(__name__)

NAME = re.compile(r"^[0-9a-f]{32}\.(webp|png|jpg)$")
IMAGE_TYPES = {"webp": "image/webp", "png": "image/png", "jpg": "image/jpeg"}
MAX_ASSETS = 500  # per creator
UPLOADS_PER_DAY = 60


def _out(a: MediaAsset) -> dict:
    return {
        "id": a.id,
        "url": a.url,
        "width": a.width,
        "height": a.height,
        "kind": a.kind,
        "prompt": a.prompt,
        "alt": a.alt,
    }


@api_view(["POST"])
@permission_classes([IsCreator])
@parser_classes([MultiPartParser])
def upload(request):
    f = request.FILES.get("file")
    if not f:
        return Response({"code": "no_file"}, status=status.HTTP_400_BAD_REQUEST)
    if MediaAsset.objects.filter(owner=request.user).count() >= MAX_ASSETS:
        return Response({"code": "media_quota"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    try:
        charge(request.user, "uploads", 1, UPLOADS_PER_DAY)
    except BudgetExceeded:
        return Response({"code": "media_quota"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    try:
        data, w, h = process(f.read())
    except ImageError as e:
        return Response({"code": e.code}, status=status.HTTP_400_BAD_REQUEST)
    return Response(
        _out(store(request.user, data, w, h, kind="upload", alt=str(request.data.get("alt", "")))),
        status=status.HTTP_201_CREATED,
    )


class GenerateIn(serializers.Serializer):
    prompt = serializers.CharField(min_length=4, max_length=400)
    alt = serializers.CharField(max_length=200, required=False, allow_blank=True)


@api_view(["POST"])
@permission_classes([IsCreator])
@parser_classes([JSONParser])
def generate_image(request):
    ser = GenerateIn(data=request.data)
    ser.is_valid(raise_exception=True)
    cfg = resolve("image")
    if not cfg.enabled or (needs_key(cfg.provider, "image") and not cfg.key and cfg.provider != "fake"):
        from django.conf import settings

        if settings.LLM_FORCE_PROVIDER != "fake":
            return Response({"code": "provider_not_configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    try:
        charge(request.user, "images", 1, cfg.limits.get("images_per_day", 0))
    except BudgetExceeded:
        return Response({"code": "image_budget_exceeded"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    try:
        data, w, h = process(generate(cfg, ser.validated_data["prompt"]))
    except ImageError as e:
        # provider text can name accounts, orgs or quotas: staff see it, creators only get the code
        log.warning("image generation failed (%s): %s", e.code, str(e)[:300])
        out = {"code": e.code, "detail": str(e)[:300]} if request.user.is_staff else {"code": e.code}
        return Response(out, status=status.HTTP_502_BAD_GATEWAY)
    a = store(
        request.user,
        data,
        w,
        h,
        kind="generated",
        prompt=ser.validated_data["prompt"],
        alt=ser.validated_data.get("alt", ""),
    )
    return Response(_out(a), status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsCreator])
def mine(request):
    return Response([_out(a) for a in MediaAsset.objects.filter(owner=request.user)[:60]])


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def serve(request, name):
    """Public by unguessable name (lesson images also appear on guest share pages)."""
    if not NAME.match(name) or not default_storage.exists(f"aasan/{name}"):
        raise Http404
    resp = FileResponse(
        default_storage.open(f"aasan/{name}", "rb"), content_type=IMAGE_TYPES[name.rsplit(".", 1)[1]]
    )
    resp["Cache-Control"] = "public, max-age=31536000, immutable"
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Content-Security-Policy"] = "default-src 'none'"
    return resp


LECTURE = re.compile(r"^[0-9a-f]{32}\.(mp4|webm|m4a|mp3|wav|ogg)$")
LECTURE_TYPES = {
    "mp4": "video/mp4",
    "webm": "video/webm",
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
}


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def serve_lecture(request, uid, name):
    """Lecture uploads, public by unguessable name (a <video> tag can't send our auth header). Supports Range so
    learners can seek; in production nginx may serve these directly instead."""
    path = f"lectures/{uid}/{name}"
    if not LECTURE.match(name) or not default_storage.exists(path):
        raise Http404
    return _ranged(request, path, LECTURE_TYPES[name.rsplit(".", 1)[1]])


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def serve_speech(request, name):
    """Shared speech clips (apps/providers/clips.py), public by content hash so <audio> can load them; immutable, so
    browsers and nginx cache them for a year. In production nginx serves these straight from the media volume."""
    from apps.providers.clips import NAME as SPEECH

    path = f"speech/{name}"
    if not SPEECH.match(name) or not default_storage.exists(path):
        raise Http404
    return _ranged(request, path, LECTURE_TYPES[name.rsplit(".", 1)[1]])


def _ranged(request, path: str, ctype: str):
    """A media file with Range support (Safari needs it for <audio>/<video>) and immutable cache headers."""
    from django.http import HttpResponse

    size = default_storage.size(path)
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", request.headers.get("Range", "").strip())
    if m and (m.group(1) or m.group(2)):
        if m.group(1):
            start = int(m.group(1))
            end = min(int(m.group(2)) if m.group(2) else size - 1, size - 1)
        else:  # suffix range: the last N bytes
            start, end = max(0, size - int(m.group(2))), size - 1
        if start > end or start >= size:
            resp = HttpResponse(status=416)
            resp["Content-Range"] = f"bytes */{size}"
            return resp
        with default_storage.open(path, "rb") as fh:
            fh.seek(start)
            data = fh.read(min(end - start + 1, 8 * 1024 * 1024))  # serve at most 8 MB per range request
        resp = HttpResponse(data, status=206, content_type=ctype)
        resp["Content-Range"] = f"bytes {start}-{start + len(data) - 1}/{size}"
    else:
        resp = FileResponse(default_storage.open(path, "rb"), content_type=ctype)
    resp["Accept-Ranges"] = "bytes"
    resp["Cache-Control"] = "public, max-age=31536000, immutable"
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Content-Security-Policy"] = "default-src 'none'"
    return resp
