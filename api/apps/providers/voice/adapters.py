"""Server-side speech adapters. Each takes the resolved config (with the
decrypted key) and returns plain data; HTTP errors become VoiceError."""

import base64
import io
import math
import struct

import httpx

TIMEOUT = httpx.Timeout(30.0, connect=10.0)
LANG_CODE = {"en": "en-IN", "ta": "ta-IN"}
DEEPGRAM_LANG = {"en": "en-IN", "ta": "ta"}


class VoiceError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


def _raise_for(resp: httpx.Response, provider: str):
    if resp.status_code in (401, 403):
        raise VoiceError("invalid_key", f"{provider} rejected the key ({resp.status_code})")
    if resp.status_code == 429:
        raise VoiceError("rate_limited", f"{provider} rate limit")
    if resp.status_code >= 400:
        raise VoiceError("provider_error", f"{provider} {resp.status_code}: {resp.text[:200]}")


# ── Speech-to-text ─────────────────────────────────────────────────────


def transcribe(cfg, audio: bytes, mime: str, lang_hint: str | None) -> str:
    p = cfg.provider
    if p == "fake":
        return "test transcript"
    if p == "openai":
        import openai

        client = openai.OpenAI(api_key=cfg.key, timeout=30)
        try:
            out = client.audio.transcriptions.create(
                model=cfg.model, file=("speech.webm", audio, mime), language=lang_hint or None
            )
        except openai.AuthenticationError as e:
            raise VoiceError("invalid_key", str(e)) from e
        except openai.APIError as e:
            raise VoiceError("provider_error", str(e)) from e
        return out.text.strip()
    if p == "sarvam":
        resp = httpx.post(
            "https://api.sarvam.ai/speech-to-text",
            headers={"api-subscription-key": cfg.key},
            files={"file": ("speech.webm", audio, mime)},
            data={"model": cfg.model, "language_code": LANG_CODE.get(lang_hint or "", "unknown")},
            timeout=TIMEOUT,
        )
        _raise_for(resp, "sarvam")
        return (resp.json().get("transcript") or "").strip()
    if p == "google":
        lang = LANG_CODE.get(lang_hint or "en", "en-IN")
        alt = [c for c in LANG_CODE.values() if c != lang]
        body = {
            "config": {
                "encoding": "WEBM_OPUS",
                "sampleRateHertz": 48000,
                "languageCode": lang,
                "alternativeLanguageCodes": alt,
                "model": cfg.model or "latest_long",
                "enableAutomaticPunctuation": True,
            },
            "audio": {"content": base64.b64encode(audio).decode()},
        }
        resp = httpx.post(
            "https://speech.googleapis.com/v1/speech:recognize",
            headers={"X-Goog-Api-Key": cfg.key},
            json=body,
            timeout=TIMEOUT,
        )
        _raise_for(resp, "google")
        results = resp.json().get("results", [])
        return " ".join(r["alternatives"][0]["transcript"] for r in results if r.get("alternatives")).strip()
    if p == "deepgram":
        # Pre-recorded /v1/listen: raw browser audio (webm/opus) in, one transcript out. Nova-3 knows en-IN and ta.
        resp = httpx.post(
            "https://api.deepgram.com/v1/listen",
            headers={"Authorization": f"Token {cfg.key}", "Content-Type": mime or "audio/webm"},
            params={
                "model": cfg.model or "nova-3",
                "smart_format": "true",
                "language": DEEPGRAM_LANG.get(lang_hint or "en", "en-IN"),
            },
            content=audio,
            timeout=TIMEOUT,
        )
        _raise_for(resp, "deepgram")
        channels = (resp.json().get("results") or {}).get("channels") or [{}]
        alts = channels[0].get("alternatives") or [{}]
        return (alts[0].get("transcript") or "").strip()
    raise VoiceError("unsupported", f"no server STT for provider {p}")


# ── Text-to-speech ─────────────────────────────────────────────────────


def synthesize(cfg, text: str, lang: str) -> tuple[bytes, str]:
    """Returns (audio bytes, mime type)."""
    p = cfg.provider
    voice = (cfg.voices or {}).get(lang) or ""
    if p == "fake":
        return _beep_wav(), "audio/wav"
    if p == "openai":
        import openai

        client = openai.OpenAI(api_key=cfg.key, timeout=30)
        try:
            resp = client.audio.speech.create(
                model=cfg.model, voice=voice or "coral", input=text, response_format="mp3"
            )
        except openai.AuthenticationError as e:
            raise VoiceError("invalid_key", str(e)) from e
        except openai.APIError as e:
            raise VoiceError("provider_error", str(e)) from e
        return resp.content, "audio/mpeg"
    if p == "sarvam":
        model = cfg.model or "bulbul:v4-flash"
        body = {"text": text, "target_language_code": LANG_CODE.get(lang, "en-IN"), "model": model}
        if speaker := sarvam_speaker(model, lang, voice):  # none: Sarvam uses the model's own default
            body["speaker"] = speaker
        resp = httpx.post(
            "https://api.sarvam.ai/text-to-speech",
            headers={"api-subscription-key": cfg.key},
            json=body,
            timeout=TIMEOUT,
        )
        _raise_for(resp, "sarvam")
        audios = resp.json().get("audios") or []
        if not audios:
            raise VoiceError("provider_error", "sarvam returned no audio")
        return base64.b64decode(audios[0]), "audio/wav"
    if p == "google":
        voice_cfg = {"languageCode": LANG_CODE.get(lang, "en-IN")}
        if voice:
            voice_cfg["name"] = voice
        resp = httpx.post(
            "https://texttospeech.googleapis.com/v1/text:synthesize",
            headers={"X-Goog-Api-Key": cfg.key},
            json={"input": {"text": text}, "voice": voice_cfg, "audioConfig": {"audioEncoding": "MP3"}},
            timeout=TIMEOUT,
        )
        _raise_for(resp, "google")
        return base64.b64decode(resp.json()["audioContent"]), "audio/mpeg"
    if p == "deepgram":
        if lang != "en":  # Aura voices are English only: never read Tamil with an English voice
            raise VoiceError("unsupported_language", "deepgram has no voice for this language")
        resp = httpx.post(
            "https://api.deepgram.com/v1/speak",
            headers={"Authorization": f"Token {cfg.key}", "Content-Type": "application/json"},
            params={"model": voice or "aura-2-thalia-en", "encoding": "mp3"},
            json={"text": text},
            timeout=TIMEOUT,
        )
        _raise_for(resp, "deepgram")
        return resp.content, "audio/mpeg"
    raise VoiceError("unsupported", f"no server TTS for provider {p}")


def sarvam_speaker(model: str, lang: str, saved: str) -> str:
    """A speaker this Bulbul model accepts: the saved one if it fits the model, else the model's default for the
    language. (A v2 name such as "anushka" is rejected by v3/v4-flash, and vice versa.)"""
    from apps.providers.catalog import SARVAM_VOICES

    voices = SARVAM_VOICES.get(model)
    if not voices:  # a newer model we don't know yet: trust the admin's choice, or let Sarvam use its default
        return saved
    known = {v for names in voices.values() for v in names}
    fits = saved in known or (model.startswith("bulbul:v4") and saved.count("_") >= 2 and saved.islower())
    if saved and fits:
        return saved
    return (voices.get(lang) or voices["en"])[0]


def _beep_wav(seconds: float = 0.3, freq: int = 660, rate: int = 16000) -> bytes:
    n = int(seconds * rate)
    frames = b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(n)
    )
    buf = io.BytesIO()
    buf.write(b"RIFF" + struct.pack("<I", 36 + len(frames)) + b"WAVEfmt ")
    buf.write(struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16))
    buf.write(b"data" + struct.pack("<I", len(frames)) + frames)
    return buf.getvalue()
