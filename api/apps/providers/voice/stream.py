"""/ws/voice-stream/ — live conversation listening: the browser streams its mic here, the server streams it on to
Deepgram's live /v1/listen, and sends back compact transcript events. The Deepgram key never leaves the server.

Browser → server:
  {"type": "auth", "token": "<access JWT>"}      first, like the mentor socket
  {"type": "start", "lang": "en" | "ta"}        opens the Deepgram stream
  binary frames                                  PCM16 little-endian, mono, 16 kHz (~100 ms each)
  {"type": "stop"}                               flush and close

Server → browser:
  {"type": "ready"} / {"type": "started"}
  {"type": "speech_started"}
  {"type": "interim", "text"}
  {"type": "final", "text", "speech_final"}
  {"type": "utterance_end"}
  {"type": "error", "code", ...}                 then the socket closes for anything fatal

Listening is charged from the real audio length (bytes / 32000 per second), in small prepaid blocks against both the
plan's voice_minutes_per_day and the Listening provider's stt_seconds_per_day; what was prepaid but not streamed is
refunded when the stream ends."""

import asyncio
import json
import logging
import time
from urllib.parse import urlencode

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from apps.mentor.consumers import SocketAuth, _feature_blocked

from ..services import BudgetExceeded, charge, needs_key, resolve

log = logging.getLogger(__name__)

DEEPGRAM_URL = "wss://api.deepgram.com/v1/listen"
DEEPGRAM_LANG = {"en": "en-IN", "ta": "ta"}  # Nova-3 knows both
BYTES_PER_SEC = 16000 * 2  # 16 kHz, 16-bit, mono
MAX_FRAME_BYTES = 32000  # one second; the browser sends ~100 ms (3200 B)
MAX_TEXT_BYTES = 4096
BLOCK_SECONDS = 5.0  # charged ahead in blocks this long
BURST_SECONDS = 4.0  # audio may run this far ahead of the wall clock (network jitter) before it is refused
KEEPALIVE_AFTER = (
    4.0  # Deepgram closes after 10 s without audio; send KeepAlive when the mic goes quiet this long
)
TICK = 1.0
STARTS_PER_10_MIN = 30  # stream openings per learner (reconnects included)


def deepgram_params(model: str, lang: str) -> dict:
    return {
        "model": model or "nova-3",
        "language": DEEPGRAM_LANG.get(lang, "en-IN"),
        "encoding": "linear16",
        "sample_rate": 16000,
        "channels": 1,
        "interim_results": "true",
        "smart_format": "true",
        "endpointing": 300,
        "utterance_end_ms": 1000,
        "vad_events": "true",
    }


def streaming_available(cfg) -> bool:
    """Live listening needs Deepgram, switched on, with a key (the admin's or DEEPGRAM_API_KEY)."""
    return cfg.provider == "deepgram" and cfg.enabled and bool(cfg.key or not needs_key(cfg.provider, "stt"))


def _max_session_seconds() -> float:
    return max(1.0, float(getattr(settings, "VOICE_STREAM_MAX_MINUTES", 30)) * 60)


def _charge_block(user, seconds: float, daily_limit: float) -> dict | None:
    """Prepay `seconds` of listening: None, or the error to send. Plan check and charge together (user row locked),
    so parallel streams can't all pass the check."""
    from apps.billing.services import PlanLimit, check, lock_user

    with transaction.atomic():
        lock_user(user)
        try:
            check(user, "voice_minutes_per_day", seconds / 60)
        except PlanLimit as e:
            return e.payload()
        try:
            charge(user, "stt_seconds", seconds, daily_limit)
        except BudgetExceeded:
            return {"code": "voice_budget_exceeded"}
    return None


def _refund(user, seconds: float):
    if seconds > 0:
        charge(user, "stt_seconds", -seconds, 0)


def _too_many_starts(user_id) -> bool:
    key = f"voice-stream-starts:{user_id}"
    cache.add(key, 0, 600)
    try:
        n = cache.incr(key)
    except ValueError:
        cache.set(key, 1, 600)
        n = 1
    return n > STARTS_PER_10_MIN


class VoiceStreamConsumer(SocketAuth, AsyncWebsocketConsumer):
    feature = "mentor"

    dg = None
    reader: asyncio.Task | None = None
    ticker: asyncio.Task | None = None
    cfg = None
    closing = False

    async def connect(self):
        self.started_at = 0.0
        self.last_audio = 0.0
        self.audio_seconds = 0.0
        self.charged = 0.0
        await self.accept()

    # SocketAuth speaks JSON; this consumer also takes binary audio.
    async def send_json(self, content):
        await self.send(text_data=json.dumps(content))

    async def fail(self, code: str, close_code: int = 4400, **extra):
        await self.send_json({"type": "error", "code": code, **extra})
        await self.shutdown()
        await self.close(code=close_code)

    async def disconnect(self, code):
        await self.shutdown()

    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data is not None:
            await self.audio(bytes_data)
            return
        if text_data is None or len(text_data) > MAX_TEXT_BYTES:
            await self.fail("bad_message")
            return
        try:
            content = json.loads(text_data)
        except ValueError:
            await self.fail("bad_message")
            return
        if not isinstance(content, dict):
            await self.fail("bad_message")
            return
        kind = content.get("type")
        if kind == "auth":
            if self.user:
                await self.reauth(content.get("token") or "")
                return
            if not await self.authenticate(content.get("token") or ""):
                await self.fail("unauthorized", 4401)
                return
            if code := await _feature_blocked(self.user, self.feature):
                await self.fail(code, 4403)
                return
            await self.send_json({"type": "ready"})
            return
        if not self.user:
            await self.fail("unauthorized", 4401)
            return
        if await self.expired():
            await self.shutdown()
            return
        if kind == "start":
            await self.start(content.get("lang"))
        elif kind == "stop":
            await self.shutdown()
            await self.close(code=1000)

    async def start(self, lang):
        if self.dg or self.closing:
            await self.send_json({"type": "error", "code": "already_started"})
            return
        if not await self.still_allowed():
            return
        if await database_sync_to_async(_too_many_starts)(self.user.pk):
            await self.fail("rate_limited", 4429)
            return
        cfg = await database_sync_to_async(resolve)("stt")
        if not streaming_available(cfg):
            await self.fail("streaming_unavailable")
            return
        self.cfg = cfg
        self.daily_limit = cfg.limits.get("stt_seconds_per_day", 0)
        err = await database_sync_to_async(_charge_block)(self.user, BLOCK_SECONDS, self.daily_limit)
        if err:
            await self.fail(err.pop("code"), 4402, **err)
            return
        self.charged = BLOCK_SECONDS
        from websockets.asyncio.client import connect
        from websockets.exceptions import InvalidStatus, WebSocketException

        url = (
            f"{DEEPGRAM_URL}?{urlencode(deepgram_params(cfg.model, lang if lang in ('en', 'ta') else 'en'))}"
        )
        try:
            self.dg = await connect(
                url,
                additional_headers={"Authorization": f"Token {cfg.key}"},
                open_timeout=8,
                max_size=1 << 20,
                ping_interval=20,
            )
        except InvalidStatus as e:
            code = "invalid_key" if e.response.status_code in (401, 403) else "provider_error"
            log.warning("deepgram live refused the stream: HTTP %s", e.response.status_code)
            await self.fail(code, 4502)
            return
        except (OSError, TimeoutError, WebSocketException) as e:
            log.warning("deepgram live unreachable: %s", type(e).__name__)
            await self.fail("provider_unavailable", 4502)
            return
        self.started_at = self.last_audio = time.monotonic()
        self.reader = asyncio.create_task(self.read_deepgram())
        self.ticker = asyncio.create_task(self.tick())
        await self.send_json({"type": "started"})

    async def audio(self, data: bytes):
        if not self.dg or self.closing:
            return  # before start or after stop: dropped, never charged
        if len(data) > MAX_FRAME_BYTES or len(data) % 2:
            await self.fail("bad_audio")
            return
        now = time.monotonic()
        elapsed = now - self.started_at
        seconds = len(data) / BYTES_PER_SEC
        if self.audio_seconds + seconds > elapsed + BURST_SECONDS:
            await self.fail("rate_limited", 4429)  # faster than a microphone can talk
            return
        if elapsed > _max_session_seconds():
            await self.fail("session_limit", 4408)
            return
        self.audio_seconds += seconds
        while self.audio_seconds > self.charged:
            err = await database_sync_to_async(_charge_block)(self.user, BLOCK_SECONDS, self.daily_limit)
            if err:
                await self.fail(err.pop("code"), 4402, **err)
                return
            self.charged += BLOCK_SECONDS
        self.last_audio = now
        try:
            await self.dg.send(data)
        except Exception:  # noqa: BLE001 - Deepgram went away; the reader reports it
            log.debug("audio frame not forwarded: deepgram closed")

    async def tick(self):
        """KeepAlive while the mic is quiet, the session cap, and the token's expiry."""
        try:
            while not self.closing:
                await asyncio.sleep(TICK)
                now = time.monotonic()
                if now - self.started_at > _max_session_seconds():
                    await self.fail("session_limit", 4408)
                    return
                if time.time() > self.exp:
                    await self.fail("token_expired", 4401)
                    return
                if self.dg and now - self.last_audio >= KEEPALIVE_AFTER:
                    self.last_audio = now
                    await self.dg.send(json.dumps({"type": "KeepAlive"}))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.debug("voice stream ticker stopped", exc_info=True)

    async def read_deepgram(self):
        dg = self.dg
        try:
            async for raw in dg:
                if isinstance(raw, bytes):
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                out = translate(msg)
                if out:
                    await self.send_json(out)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - a dropped upstream connection
            log.info("deepgram live stream ended: %s", type(e).__name__)
        if not self.closing:  # Deepgram closed on its own (network, its own timeout): tell the browser
            await self.fail("stream_closed", 4502)

    async def shutdown(self):
        """Close Deepgram cleanly (CloseStream flushes the last words) and refund unstreamed prepaid seconds. Safe to
        call more than once."""
        if self.closing:
            return
        self.closing = True
        if self.ticker and self.ticker is not asyncio.current_task():
            self.ticker.cancel()
        dg, self.dg = self.dg, None
        if dg:
            try:
                await dg.send(json.dumps({"type": "CloseStream"}))
                # Let the final transcripts arrive before closing (bounded).
                if self.reader and self.reader is not asyncio.current_task():
                    await asyncio.wait_for(asyncio.shield(self.reader), timeout=1.5)
            except Exception:  # noqa: BLE001 - already closed or timed out
                log.debug("deepgram did not flush before close")
            try:
                await dg.close()
            except Exception:  # noqa: BLE001
                log.debug("deepgram close failed")
        if self.reader and self.reader is not asyncio.current_task() and not self.reader.done():
            self.reader.cancel()
        unused = self.charged - self.audio_seconds
        self.charged = self.audio_seconds
        if self.user and unused > 0:
            try:
                await database_sync_to_async(_refund)(self.user, unused)
            except Exception:  # noqa: BLE001
                log.warning("could not refund %.1f s of listening", unused)


def translate(msg: dict) -> dict | None:
    """One Deepgram live message → the compact event the browser gets (None: nothing to tell it)."""
    kind = msg.get("type")
    if kind == "Results":
        alts = (msg.get("channel") or {}).get("alternatives") or [{}]
        text = (alts[0].get("transcript") or "").strip()
        if msg.get("is_final"):
            speech_final = bool(msg.get("speech_final"))
            if text or speech_final:
                return {"type": "final", "text": text, "speech_final": speech_final}
            return None
        return {"type": "interim", "text": text} if text else None
    if kind == "UtteranceEnd":
        # -1: the words were already finalised (speech_final came first), so there is nothing new to end.
        return None if msg.get("last_word_end") == -1 else {"type": "utterance_end"}
    if kind == "SpeechStarted":
        return {"type": "speech_started"}
    return None  # Metadata and anything new
