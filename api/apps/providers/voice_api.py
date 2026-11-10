"""Learner-facing voice endpoints. Keys never leave the server."""

import math

from django.db import transaction
from django.http import HttpResponse
from rest_framework import serializers, status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response

from .clips import MAX_WARM, MAX_WARM_CHARS, ROLES, NoServerVoice, clean, get_clip, line_lang, route, url_of
from .services import BudgetExceeded, charge, needs_key, resolve
from .voice import live
from .voice.adapters import VoiceError, synthesize, transcribe
from .voice.stream import streaming_available

MAX_AUDIO_BYTES = 4 * 1024 * 1024  # one utterance is far smaller; charged by size (see _charge_bytes_per_sec)
MAX_TTS_CHARS = 600  # one sentence-joined part at a time


def _engine(cfg, capability):
    # A keyed provider with no key would 503 every request, so the client should use the browser voice.
    if cfg.provider == "browser" or not cfg.enabled or (needs_key(cfg.provider, capability) and not cfg.key):
        return "browser"
    return "server"


@api_view(["GET"])
def voice_config(request):
    stt, tts, tts_ta = resolve("stt"), resolve("tts"), resolve("tts_ta")
    return Response(
        {
            # streaming: live conversation can stream the mic to Deepgram over ws/voice-stream/.
            "stt": {
                "engine": _engine(stt, "stt"),
                "provider": stt.provider,
                "streaming": streaming_available(stt),
            },
            "tts": {"engine": _engine(tts, "tts"), "provider": tts.provider},
            # Tamil lines: their own voice when set up, else whatever "tts" can do.
            "tts_ta": {"engine": _engine(tts_ta, "tts_ta"), "provider": tts_ta.provider},
            # live: a WebRTC voice call with Aasan's voice agent (LiveKit + Sarvam), like ChatGPT voice.
            "live": live.available(),
        }
    )


def _charge_bytes_per_sec() -> int:
    """STT is charged from the clip size, since the audio is never decoded here. The default 4000 B/s (32 kbps) matches
    a browser's usual recording rate, so normal clips are charged their real length. A deliberately low-bitrate clip
    can carry more audio than it is charged for; lower STT_CHARGE_BYTES_PER_SEC (750 = a 6 kbps floor) to close that,
    at the cost of over-charging normal clips. Exact charging needs the clip decoded."""
    from django.conf import settings

    return max(1, int(getattr(settings, "STT_CHARGE_BYTES_PER_SEC", 4000)))


def _err(code, http=status.HTTP_400_BAD_REQUEST):
    return Response({"code": code}, status=http)


@api_view(["POST"])
@parser_classes([MultiPartParser])
def transcribe_view(request):
    from apps.orgs.extras import refusal

    if code := refusal(request.user, "voice"):  # an under-18's voice waits for their guardian's consent
        return _err(code, status.HTTP_403_FORBIDDEN)
    cfg = resolve("stt")
    if cfg.provider == "browser" or not cfg.enabled:
        return _err("use_browser_engine")
    if needs_key(cfg.provider, "stt") and not cfg.key:
        return _err("provider_not_configured", status.HTTP_503_SERVICE_UNAVAILABLE)
    clip = request.FILES.get("audio")
    if not clip or clip.size > MAX_AUDIO_BYTES:
        return _err("bad_audio")
    try:
        claimed = float(request.data.get("seconds") or 0)
    except ValueError:
        claimed = 0.0
    if not math.isfinite(claimed):
        claimed = 0.0
    # The client can only raise the charge, never lower it below the clip-size estimate (at the conservative bitrate
    # floor). Not capped: the whole clip goes to the provider, so the whole estimated length is charged.
    rate = _charge_bytes_per_sec()
    seconds = min(MAX_AUDIO_BYTES / rate, max(clip.size / rate, claimed, 1.0))
    from apps.billing.services import PlanLimit, check, lock_user

    with transaction.atomic():  # plan check and charge together, so parallel clips can't all pass the check
        lock_user(request.user)
        try:
            check(request.user, "voice_minutes_per_day", seconds / 60)
        except PlanLimit as e:
            return Response(e.payload(), status=status.HTTP_402_PAYMENT_REQUIRED)
        try:
            charge(request.user, "stt_seconds", seconds, cfg.limits.get("stt_seconds_per_day", 0))
        except BudgetExceeded:
            return _err("voice_budget_exceeded", status.HTTP_429_TOO_MANY_REQUESTS)
    lang = request.data.get("lang") if request.data.get("lang") in ("en", "ta") else None
    try:
        text = transcribe(cfg, clip.read(), clip.content_type or "audio/webm", lang)
    except VoiceError as e:
        charge(request.user, "stt_seconds", -seconds, 0)  # refund: nothing was transcribed
        return _err(e.code, status.HTTP_502_BAD_GATEWAY)
    return Response({"text": text})


@api_view(["POST"])
@parser_classes([JSONParser])
def speak_view(request):
    raw = request.data.get("text")
    if not isinstance(raw, str):
        return _err("empty")
    text = raw.strip()[:MAX_TTS_CHARS]
    if not text:
        return _err("empty")
    lang = line_lang(text, request.data.get("lang"))
    capability, cfg = route(lang)  # a Tamil line uses "Speaking: Tamil" when it is set up
    if cfg.provider == "browser" or not cfg.enabled:
        return _err("use_browser_engine")
    if needs_key(cfg.provider, capability) and not cfg.key:
        return _err("provider_not_configured", status.HTTP_503_SERVICE_UNAVAILABLE)
    from apps.billing.services import PlanLimit, check, lock_user

    with transaction.atomic():  # plan check and charge together (parallel requests can't all pass)
        lock_user(request.user)
        try:
            check(request.user, "tts_chars_per_day", len(text))
        except PlanLimit as e:
            return Response(e.payload(), status=status.HTTP_402_PAYMENT_REQUIRED)
        try:
            charge(request.user, "tts_chars", len(text), cfg.limits.get("tts_chars_per_day", 0))
        except BudgetExceeded:
            return _err("voice_budget_exceeded", status.HTTP_429_TOO_MANY_REQUESTS)
    try:
        audio, mime = synthesize(cfg, text, lang)
    except VoiceError as e:
        charge(request.user, "tts_chars", -len(text), 0)  # refund: nothing was spoken
        if (
            e.code == "unsupported_language"
        ):  # e.g. a Tamil line with an English-only voice: the client reads it
            return _err(
                e.code, status.HTTP_422_UNPROCESSABLE_ENTITY
            )  # with the browser voice, just this once
        return _err(e.code, status.HTTP_502_BAD_GATEWAY)
    resp = HttpResponse(audio, content_type=mime)
    resp["Cache-Control"] = "no-store"
    return resp


class ClipItem(serializers.Serializer):
    text = serializers.CharField(max_length=MAX_TTS_CHARS * 2, trim_whitespace=True)
    lang = serializers.ChoiceField(choices=["en", "ta"], required=False)
    voice_role = serializers.ChoiceField(choices=list(ROLES), default="narrator")


class ClipIn(ClipItem):
    # The rest of the episode / lesson, made in the background so the next lines (and other learners) start instantly.
    warm = ClipItem(many=True, required=False)


@api_view(["POST"])
@parser_classes([JSONParser])
def clip_view(request):
    """POST {text, lang?, voice_role?, warm?: [{text, lang?, voice_role?}]} → {url, cached}. One whole part (sentence-
    joined, ≤ MAX_TTS_CHARS) per clip, generated once and shared by every learner; charged only when first made."""
    ser = ClipIn(data=request.data)
    if not ser.is_valid():
        return _err("bad_input")
    data = ser.validated_data
    text = clean(data["text"])
    if not text:
        return _err("empty")
    if len(text) > MAX_TTS_CHARS:
        return _err("too_long")
    from apps.billing.services import PlanLimit

    try:
        clip, made = get_clip(request.user, text, data.get("lang"), data["voice_role"])
    except NoServerVoice:
        return _err("use_browser_engine")
    except PlanLimit as e:
        return Response(e.payload(), status=status.HTTP_402_PAYMENT_REQUIRED)
    except BudgetExceeded:
        return _err("voice_budget_exceeded", status.HTTP_429_TOO_MANY_REQUESTS)
    except VoiceError as e:
        if e.code == "unsupported_language":  # the client reads this line with the browser voice
            return _err(e.code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        return _err(e.code, status.HTTP_502_BAD_GATEWAY)
    items = [
        {"text": clean(w["text"]), "lang": w.get("lang"), "voice_role": w["voice_role"]}
        for w in data.get("warm") or []
    ]
    items = [w for w in items if w["text"] and len(w["text"]) <= MAX_TTS_CHARS][:MAX_WARM]
    total, kept = 0, []
    for w in items:
        total += len(w["text"])
        if total > MAX_WARM_CHARS:
            break
        kept.append(w)
    if kept:
        from apps.study.jobs import enqueue

        transaction.on_commit(lambda: enqueue("apps.providers.clips.warm", request.user.id, kept))
    return Response(
        {"url": url_of(clip), "cached": not made, "mime": clip.mime, "duration_ms": clip.duration_ms}
    )


# Which org feature switch covers live voice on each screen.
LIVE_FEATURES = {"mentor": "mentor", "live": "live", "roleplay": "roleplay", "workshop": "workshops"}


@api_view(["POST"])
@parser_classes([JSONParser])
def live_token_view(request):
    """Join a live voice call: a LiveKit room with Aasan's voice agent in it."""
    from apps.orgs.extras import refusal

    from .voice.stream import _too_many_starts

    feature = request.data.get("feature") or "mentor"
    if feature not in LIVE_FEATURES:
        return _err("bad_feature")
    if not live.available():
        return _err("live_unavailable", status.HTTP_503_SERVICE_UNAVAILABLE)
    if code := refusal(request.user, LIVE_FEATURES[feature]):
        return _err(code, status.HTTP_403_FORBIDDEN)
    if _too_many_starts(request.user.pk):
        return _err("rate_limited", status.HTTP_429_TOO_MANY_REQUESTS)
    if live.calls_full(request.user):  # the browser falls back to streamed voice
        resp = _err("voice_busy", status.HTTP_503_SERVICE_UNAVAILABLE)
        resp["Retry-After"] = "60"
        return resp
    from apps.billing.services import PlanLimit, check

    try:  # at least a minute of voice left today, or the call isn't worth starting
        check(request.user, "voice_minutes_per_day", 1)
    except PlanLimit as e:
        return Response(e.payload(), status=status.HTTP_402_PAYMENT_REQUIRED)
    return Response(live.issue_token(request.user, str(request.data.get("lang") or "en"), feature))
