"""Speech clips: language-routed voices and a shared, generate-once audio cache.

- Routing: a Tamil line uses "Speaking: Tamil" (tts_ta) when it is set up, else "Speaking" (tts); the client falls back
  to the browser voice when neither can say it.
- Roles: narrator (Listen, explainer), host_a and host_b (the two podcast hosts, always different voices).
- Cache: one SpeechClip per sha256(provider|model|voice|lang|text), its audio in media storage under speech/. Every
  learner gets the same URL for the same line, and TTS characters are charged only when a clip is first generated."""

import hashlib
import logging
import re
import time
from dataclasses import replace

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction

from .catalog import CAPABILITIES
from .models import SpeechClip
from .services import BudgetExceeded, Resolved, charge, needs_key, resolve
from .voice.adapters import VoiceError, sarvam_speaker, synthesize

log = logging.getLogger(__name__)

ROLES = ("narrator", "host_a", "host_b")
TAMIL = re.compile(r"[஀-௿]")
EXT = {"audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/ogg": "ogg", "audio/mp4": "m4a"}
MIME = {"mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg", "m4a": "audio/mp4"}
NAME = re.compile(r"^[0-9a-f]{64}\.(mp3|wav|ogg|m4a)$")
URL_PREFIX = "/api/media/speech/"
LOCK_S = 60  # one generation per clip at a time; others wait for it
WAIT_S = 20


class NoServerVoice(Exception):
    """Neither speaking capability can say this line: the client reads it with the browser voice."""


def line_lang(text: str, hint: str | None) -> str:
    # Tamil script (incl. Tanglish) needs the Tamil voice even if the client said "en".
    if TAMIL.search(text):
        return "ta"
    return hint if hint in ("en", "ta") else "en"


def usable(cfg: Resolved, capability: str) -> bool:
    return (
        cfg.provider != "browser"
        and cfg.enabled
        and (not needs_key(cfg.provider, capability) or bool(cfg.key) or cfg.provider == "fake")
    )


def route(lang: str) -> tuple[str, Resolved]:
    """The speaking capability for a line in this language: tts_ta for Tamil when it is set up, else tts."""
    if lang == "ta":
        ta = resolve("tts_ta")
        if usable(ta, "tts_ta"):
            return "tts_ta", ta
    return "tts", resolve("tts")


def _hosts(cfg: Resolved, capability: str, lang: str) -> list[str]:
    spec = CAPABILITIES[capability]["providers"].get(cfg.provider, {})
    by_model = (spec.get("host_voices_by_model") or {}).get(cfg.model)
    return list((by_model or spec.get("host_voices") or {}).get(lang) or [])


def _all_voices(cfg: Resolved, capability: str, lang: str) -> list[str]:
    spec = CAPABILITIES[capability]["providers"].get(cfg.provider, {})
    by_model = (spec.get("voices_by_model") or {}).get(cfg.model)
    return list((by_model or spec.get("voices") or {}).get(lang) or [])


def _fit(cfg: Resolved, lang: str, voice: str) -> str:
    """The speaker the adapter will really use (so the cache key names the actual voice)."""
    if cfg.provider == "sarvam":
        return sarvam_speaker(cfg.model or "bulbul:v4-flash", lang, voice)
    if cfg.provider == "deepgram":
        return voice or "aura-2-thalia-en"
    if cfg.provider == "openai":
        return voice or "coral"
    return voice


def voice_for(cfg: Resolved, capability: str, lang: str, role: str) -> str:
    """Narrator: the admin's voice for the language. Hosts: the admin's host A / host B voices, else the catalog pair.
    Host A and host B never come out the same."""
    saved = cfg.voices or {}
    narrator = _fit(cfg, lang, saved.get(lang) or "")
    if role == "narrator":
        return narrator
    pair = _hosts(cfg, capability, lang)
    a = _fit(cfg, lang, saved.get(f"{lang}_host_a") or (pair[0] if pair else "") or narrator)
    b = _fit(cfg, lang, saved.get(f"{lang}_host_b") or (pair[1] if len(pair) > 1 else ""))
    if role == "host_a":
        return a
    if not b or b == a:
        others = [v for v in [*pair, *_all_voices(cfg, capability, lang)] if _fit(cfg, lang, v) != a]
        b = _fit(cfg, lang, others[0]) if others else b
    return b


def clip_key(provider: str, model: str, voice: str, lang: str, text: str) -> str:
    return hashlib.sha256(f"{provider}|{model}|{voice}|{lang}|{text}".encode()).hexdigest()


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def url_of(clip: SpeechClip) -> str:
    return URL_PREFIX + clip.file.rsplit("/", 1)[-1]


def _wav_ms(audio: bytes) -> int | None:
    """Duration of a PCM WAV (Sarvam, the fake provider); other formats leave it unknown."""
    if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        return None
    byte_rate = int.from_bytes(audio[28:32], "little")
    return int((len(audio) - 44) * 1000 / byte_rate) if byte_rate else None


def _wait_for(key: str) -> SpeechClip | None:
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        time.sleep(0.25)
        if hit := SpeechClip.objects.filter(key=key).first():
            return hit
        if cache.get(f"speechclip:{key}") is None:  # the other generation gave up
            return None
    return None


def get_clip(user, text: str, lang_hint: str | None, role: str) -> tuple[SpeechClip, bool]:
    """(clip, made_now). Raises NoServerVoice, BudgetExceeded, PlanLimit or VoiceError."""
    text = clean(text)
    lang = line_lang(text, lang_hint)
    capability, cfg = route(lang)
    if not usable(cfg, capability):
        raise NoServerVoice(capability)
    voice = voice_for(cfg, capability, lang, role)
    key = clip_key(cfg.provider, cfg.model, voice, lang, text)
    if hit := SpeechClip.objects.filter(key=key).first():
        if default_storage.exists(hit.file):
            return hit, False
        hit.delete()  # its audio was cleared from media storage: make it again
    lock = f"speechclip:{key}"
    # Someone else (a learner or the pre-warm job) is making it right now: wait for theirs.
    if not cache.add(lock, 1, LOCK_S) and (hit := _wait_for(key)):
        return hit, False
    try:
        return _generate(user, cfg, capability, lang, voice, key, text), True
    finally:
        cache.delete(lock)


def _generate(user, cfg: Resolved, capability: str, lang: str, voice: str, key: str, text: str) -> SpeechClip:
    from apps.billing.services import check, lock_user

    with transaction.atomic():  # plan check and charge together (parallel requests can't all pass)
        lock_user(user)
        check(user, "tts_chars_per_day", len(text))
        charge(user, "tts_chars", len(text), cfg.limits.get("tts_chars_per_day", 0))
    try:
        audio, mime = synthesize(replace(cfg, voices={lang: voice}), text, lang)
    except VoiceError:
        charge(user, "tts_chars", -len(text), 0)  # refund: nothing was spoken
        raise
    ext = EXT.get(mime.split(";")[0].strip(), "mp3")
    name = f"speech/{key}.{ext}"
    if default_storage.exists(
        name
    ):  # a leftover file (no row): replace it, so the name stays the content hash
        default_storage.delete(name)
    path = default_storage.save(name, ContentFile(audio))
    try:
        with transaction.atomic():  # a savepoint, so a lost race never breaks a surrounding transaction
            return SpeechClip.objects.create(
                key=key,
                provider=cfg.provider,
                model=cfg.model[:80],
                voice=voice[:80],
                lang=lang,
                chars=len(text),
                file=path,
                mime=MIME[ext],
                duration_ms=_wav_ms(audio),
            )
    except IntegrityError:  # made at the same moment elsewhere: same name, same audio — keep theirs
        return SpeechClip.objects.get(key=key)


MAX_WARM = 80  # clips per pre-warm request (a long lesson or episode)
MAX_WARM_CHARS = 40_000


def warm(user_id: int, items: list) -> None:
    """Background job: make the rest of an episode / lesson so replays and other learners start instantly. Stops at
    the learner's daily budget; failures are skipped (the player generates that line on demand)."""
    from apps.accounts.models import User
    from apps.billing.services import PlanLimit

    user = User.objects.filter(id=user_id, is_active=True).first()
    if not user:
        return
    for it in items[:MAX_WARM]:
        try:
            get_clip(user, it["text"], it.get("lang"), it.get("voice_role") or "narrator")
        except (BudgetExceeded, PlanLimit):
            return
        except NoServerVoice:
            continue
        except VoiceError as e:
            log.info("clip warm skipped one line: %s", e.code)
        except Exception:
            log.exception("clip warm failed")
