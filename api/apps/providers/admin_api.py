"""Staff-only endpoints behind the Aasan admin console."""

import asyncio

from rest_framework import serializers, status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.staff import AdminSection

from . import crypto
from .catalog import CAPABILITIES, DEFAULT_LIMITS, ENV_KEYS, TTS_CAPABILITIES
from .models import ProviderConfig
from .services import needs_key, resolve
from .voice.adapters import VoiceError, synthesize, transcribe

LIMIT_KEYS = set(DEFAULT_LIMITS)
# Narrator voice per language ("en", "ta") plus the two podcast hosts ("en_host_a", "ta_host_b", ...).
VOICE_KEYS = {f"{lang}{suffix}" for lang in ("en", "ta") for suffix in ("", "_host_a", "_host_b")}


def _public(capability: str) -> dict:
    r = resolve(capability)
    row = ProviderConfig.objects.filter(capability=capability).first()
    db_key = row.get_key() if row and row.encrypted_key else ""
    return {
        "capability": capability,
        "label": CAPABILITIES[capability]["label"],
        "provider": r.provider,
        "model": r.model,
        "voices": r.voices,
        "enabled": r.enabled,
        "limits": r.limits,
        "source": r.source,
        "key": {
            "needed": needs_key(r.provider, capability),
            "set": bool(r.key),
            "from": "admin" if db_key else ("env" if r.key else None),
            "masked": crypto.mask(r.key) if r.key else None,
            "env_var": ENV_KEYS.get(r.provider),
        },
        "updated_at": row.updated_at if row else None,
    }


@api_view(["GET"])
@permission_classes([AdminSection])
def list_providers(request):
    return Response(
        {
            "catalog": CAPABILITIES,
            "configs": [_public(c) for c in CAPABILITIES],
        }
    )


class ConfigPatch(serializers.Serializer):
    provider = serializers.CharField(required=False)
    model = serializers.CharField(required=False, allow_blank=True, max_length=80)
    voices = serializers.DictField(
        child=serializers.CharField(allow_blank=True, max_length=60), required=False
    )
    enabled = serializers.BooleanField(required=False)
    limits = serializers.DictField(
        child=serializers.IntegerField(min_value=0, max_value=10_000_000), required=False
    )
    # api_key: omitted = keep, "" = clear, value = replace
    api_key = serializers.CharField(required=False, allow_blank=True, max_length=512, trim_whitespace=True)

    def validate_voices(self, v):
        if set(v) - VOICE_KEYS:
            raise serializers.ValidationError(f"voices keys must be among {sorted(VOICE_KEYS)}")
        return v

    def validate_limits(self, v):
        if set(v) - LIMIT_KEYS:
            raise serializers.ValidationError(f"allowed limits: {sorted(LIMIT_KEYS)}")
        return v


@api_view(["PATCH"])
@permission_classes([AdminSection])
def update_provider(request, capability):
    if capability not in CAPABILITIES:
        return Response(status=status.HTTP_404_NOT_FOUND)
    ser = ConfigPatch(data=request.data)
    ser.is_valid(raise_exception=True)
    data = ser.validated_data
    current = resolve(capability)
    row, _ = ProviderConfig.objects.get_or_create(
        capability=capability,
        defaults={"provider": current.provider, "model": current.model, "limits": current.limits},
    )
    providers = CAPABILITIES[capability]["providers"]
    if "provider" in data:
        if data["provider"] not in providers:
            return Response({"provider": [f"choose one of {sorted(providers)}"]}, status=400)
        if data["provider"] != row.provider:
            row.provider = data["provider"]
            row.model = data.get("model") or providers[row.provider]["default_model"]
            row.voices = {}
            row.encrypted_key = ""  # a key for one vendor is never valid for another
    if "model" in data:
        row.model = data["model"] or providers[row.provider]["default_model"]
    if "voices" in data:
        row.voices = {**row.voices, **data["voices"]}
    if "enabled" in data:
        row.enabled = data["enabled"]
    if "limits" in data:
        row.limits = {**row.limits, **data["limits"]}
    if "api_key" in data:
        row.set_key(data["api_key"])
    row.updated_by = request.user
    row.save()
    return Response(_public(capability))


SAMPLE = {"en": "Hello! I am Aasan, your learning companion.", "ta": "வணக்கம்! நான் ஆசான், உங்கள் கற்றல் துணை."}


@api_view(["POST"])
@permission_classes([AdminSection])
@parser_classes([MultiPartParser, JSONParser])
def test_provider(request, capability):
    """Make one tiny real call with the saved config."""
    if capability not in CAPABILITIES:
        return Response(status=status.HTTP_404_NOT_FOUND)
    cfg = resolve(capability)
    if cfg.provider == "browser":
        return Response({"ok": True, "detail": "Runs in the learner's browser; test it from this page."})
    if needs_key(cfg.provider, capability) and not cfg.key:
        return Response(
            {"ok": False, "code": "missing_key", "detail": "No API key saved or in .env"}, status=400
        )
    try:
        if capability in TTS_CAPABILITIES:
            from dataclasses import replace

            from .clips import ROLES, voice_for

            default_lang = "ta" if capability == "tts_ta" else "en"
            lang = request.data.get("lang") if request.data.get("lang") in SAMPLE else default_lang
            role = request.data.get("role") if request.data.get("role") in ROLES else "narrator"
            # Plays the narrator, host A or host B voice exactly as learners will hear it.
            voice = voice_for(cfg, capability, lang, role)
            audio, mime = synthesize(replace(cfg, voices={lang: voice}), SAMPLE[lang], lang)
            from django.http import HttpResponse

            resp = HttpResponse(audio, content_type=mime)
            resp["X-Test-Ok"] = "1"
            return resp
        if capability == "embedding":
            from apps.docs.embeddings import embed

            v = embed(["Aasan connection test"])
            if not v:
                return Response(
                    {
                        "ok": False,
                        "code": "provider_error",
                        "detail": "No embedding came back. Check the key and model.",
                    },
                    status=400,
                )
            return Response({"ok": True, "detail": f"Got a {len(v[0])}-dimension embedding."})
        if capability == "image":
            import base64

            from apps.media.images import ImageError, generate, process

            try:
                data, w, h = process(generate(cfg, "a small orange parrot reading a book"))
            except ImageError as e:
                return Response({"ok": False, "code": e.code, "detail": str(e)[:300]}, status=400)
            return Response(
                {
                    "ok": True,
                    "detail": f"Generated a {w}×{h} test image.",
                    "image": "data:image/webp;base64," + base64.b64encode(data).decode(),
                }
            )
        if capability == "stt":
            clip = request.FILES.get("audio")
            if not clip:
                return Response(
                    {"ok": False, "code": "no_audio", "detail": "Record a short clip to test"}, status=400
                )
            text = transcribe(cfg, clip.read(), clip.content_type or "audio/webm", request.data.get("lang"))
            return Response({"ok": True, "detail": text or "(no speech detected)"})
        # LLM capabilities
        from llm.base import ChatMessage, LLMError, LLMRequest
        from llm.router import complete_once, provider_for

        provider = provider_for(cfg)
        try:
            reply = asyncio.run(
                complete_once(
                    provider,
                    LLMRequest(
                        model=cfg.model,
                        system="You are a connection test.",
                        messages=[ChatMessage("user", "Reply with exactly: OK")],
                        max_tokens=200,
                    ),
                )
            )
        except LLMError as e:
            return Response({"ok": False, "code": e.code, "detail": str(e)[:300]}, status=400)
        return Response({"ok": True, "detail": reply.strip()[:120]})
    except VoiceError as e:
        return Response({"ok": False, "code": e.code, "detail": str(e)[:300]}, status=400)
