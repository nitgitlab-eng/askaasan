"""Aasan's live voice agent (LiveKit Agents): run with `manage.py run_voice_agent start` (or `dev` locally).

One job per voice call. The agent joins the learner's room and is only the voice:
- listens to the learner's mic (WebRTC, so the browser's echo cancelling removes Aasan's own voice) with Sarvam's
  streaming recogniser, and decides when the turn is over (Silero VAD + the turn-detector model where it knows the
  language, plain end-of-speech for Tamil);
- sends the finished turn to the browser ("aasan.event" final), which asks the screen's own socket for the reply;
- speaks what the browser streams back ("aasan.say", the reply's words as they arrive) with Sarvam's streaming voice;
- stops speaking the moment the learner talks over it, and tells the browser ("interrupted") so the reply is cut too.

Events to the browser, JSON on the "aasan.event" text topic:
  {"type": "interim", "text"}            the learner's words so far (live captions)
  {"type": "final", "text", "speech_final": true}   the learner's turn, to send
  {"type": "speech_started"}             the learner started talking
  {"type": "state", "state"}             listening | thinking | speaking (Aasan)
  {"type": "said", "id"} / {"type": "interrupted", "id"}   a reply finished, or was cut off
  {"type": "error", "code"}              plan_limit | voice_budget_exceeded (the call ends)
The browser calls the "aasan.interrupt" RPC for a deliberate tap.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterable, AsyncIterator

log = logging.getLogger(__name__)

EVENT_TOPIC = "aasan.event"
SAY_TOPIC = "aasan.say"
INTERRUPT_RPC = "aasan.interrupt"
TURN_MODEL_LANGS = {"en"}  # the turn-detector model has no Tamil: Tamil turns end on the pause alone
SILENCE_S = 0.35  # the pause that may end a turn (Silero's default 0.55 s feels slow on a call)


class TurnText:
    """The learner's words for one turn, from the recogniser's interim and final transcripts."""

    def __init__(self) -> None:
        self.finals: list[str] = []
        self.partial = ""

    def add(self, text: str, is_final: bool) -> str:
        text = text.strip()
        if is_final:
            if text:
                self.finals.append(text)
            self.partial = ""
        else:
            self.partial = text
        return self.text()

    def text(self) -> str:
        return " ".join([*self.finals, self.partial]).strip()

    def take(self, fallback: str = "") -> str:
        out = self.text() or fallback.strip()
        self.finals, self.partial = [], ""
        return out


def session_options(lang: str) -> dict:
    """Turn-taking that feels like a phone call: answer soon after a pause, stop the moment the learner talks."""
    return {
        # After the VAD's own silence (SILENCE_S): the turn model may wait longer when the sentence sounds unfinished.
        "endpointing": {"min_delay": 0.2 if lang in TURN_MODEL_LANGS else 0.3, "max_delay": 2.5},
        "interruption": {
            "enabled": True,
            "mode": "vad",  # on this server; "adaptive" needs LiveKit Cloud
            "min_duration": 0.4,
            "min_words": 0,
            "resume_false_interruption": True,  # a cough or a "hmm" pauses Aasan, then it carries on
            "false_interruption_timeout": 1.0,
        },
    }


async def charged(text: AsyncIterable[str], pay, on_limit) -> AsyncIterator[str]:
    """Pass the reply's words on to the voice, charging each piece first; at the daily limit the rest is not said."""
    async for chunk in text:
        if not chunk:
            continue
        err = await pay(len(chunk))
        if err:
            await on_limit(err)
            return
        yield chunk


def _django():
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def prewarm(proc) -> None:
    """Once per worker process: Django, and the models every call needs."""
    _django()
    from livekit.plugins import silero

    proc.userdata["vad"] = silero.VAD.load(min_silence_duration=SILENCE_S)


async def entrypoint(ctx) -> None:
    from asgiref.sync import sync_to_async
    from livekit.agents import Agent, AgentSession, StopResponse, room_io
    from livekit.agents.llm import LLM
    from livekit.plugins import sarvam

    from apps.accounts.models import User

    from . import live

    meta = json.loads(ctx.job.metadata or "{}")
    lang = meta.get("lang") if meta.get("lang") in live.LANGS else "en"
    user = await sync_to_async(User.objects.get)(pk=meta["user_id"])
    cfg = await sync_to_async(live.live_voice)()
    if not cfg:
        log.warning("live voice is not set up: leaving the room")
        return
    await ctx.connect()
    room = ctx.room

    async def emit(event: dict) -> None:
        try:
            await room.local_participant.send_text(json.dumps(event), topic=EVENT_TOPIC)
        except Exception:
            log.debug("event not sent: %s", event.get("type"), exc_info=True)

    def fire(event: dict) -> None:
        asyncio.create_task(emit(event))

    turn = TurnText()

    class Voice(Agent):
        async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
            text = turn.take(new_message.text_content or "")
            if text:
                await emit({"type": "final", "text": text, "speech_final": True})
            raise StopResponse()  # the reply comes from the screen's own socket, through the browser

    from livekit.plugins.turn_detector.multilingual import MultilingualModel

    class NoLLM(LLM):
        """Lets the session run its turn handling; every turn stops in on_user_turn_completed."""

        def chat(self, *args, **kwargs):
            raise RuntimeError("Aasan's voice agent never generates text")

    speaker = (cfg.voices or {}).get(lang) or ""
    from .adapters import sarvam_speaker

    session = AgentSession(
        # flush_signal: when the VAD hears the pause, Sarvam finalises the words now instead of waiting on its own.
        stt=sarvam.STT(language=live.LANGS[lang], model=cfg.stt_model, api_key=cfg.key, flush_signal=True),
        tts=sarvam.TTS(
            target_language_code=live.LANGS[lang],
            model=cfg.tts_model,
            speaker=sarvam_speaker(cfg.tts_model, lang, speaker) or None,
            api_key=cfg.key,
        ),
        vad=ctx.proc.userdata["vad"],
        llm=NoLLM(),
        turn_handling={
            "turn_detection": MultilingualModel() if lang in TURN_MODEL_LANGS else "vad",
            "preemptive_generation": {"enabled": False},
            **session_options(lang),
        },
    )

    @session.on("user_input_transcribed")
    def _heard(ev) -> None:
        fire({"type": "interim", "text": turn.add(ev.transcript, ev.is_final)})

    @session.on("user_state_changed")
    def _user(ev) -> None:
        if ev.new_state == "speaking":
            fire({"type": "speech_started"})

    @session.on("agent_state_changed")
    def _agent(ev) -> None:
        fire({"type": "state", "state": ev.new_state})

    # ── Billing: listening prepaid in blocks of call time; speaking by characters. ──
    started = time.monotonic()
    paid = 0.0
    ended = asyncio.Event()

    async def stop_for(code: str) -> None:
        await emit({"type": "error", "code": code})
        ended.set()

    async def pay_listening() -> None:
        nonlocal paid
        while not ended.is_set():
            if time.monotonic() - started >= live.max_call_seconds():
                await stop_for("session_limit")  # same code as the streamed path's VOICE_STREAM_MAX_MINUTES
                return
            if time.monotonic() - started + live.BLOCK_SECONDS > paid:
                err = await sync_to_async(live.charge_listening)(user, live.BLOCK_SECONDS, cfg.limits)
                if err:
                    await stop_for(err.get("code", "plan_limit"))
                    return
                paid += live.BLOCK_SECONDS
            try:
                await asyncio.wait_for(ended.wait(), timeout=1.0)
            except TimeoutError:
                pass

    async def pay_speaking(chars: int) -> str | None:
        return await sync_to_async(live.charge_speaking)(user, chars, cfg.limits)

    def on_say(reader, participant_identity: str) -> None:
        reply_id = (reader.info.attributes or {}).get("id", "")

        async def speak() -> None:
            handle = session.say(charged(reader, pay_speaking, stop_for), allow_interruptions=True)
            await handle
            await emit({"type": "interrupted" if handle.interrupted else "said", "id": reply_id})

        asyncio.create_task(speak())

    room.register_text_stream_handler(SAY_TOPIC, on_say)

    @room.local_participant.register_rpc_method(INTERRUPT_RPC)
    async def _interrupt(data) -> str:
        await session.interrupt()
        return "ok"

    await session.start(
        agent=Voice(instructions=""),
        room=room,
        room_options=room_io.RoomOptions(close_on_disconnect=True, delete_room_on_close=True),
        record=False,
    )
    billing = asyncio.create_task(pay_listening())

    @room.on("disconnected")
    def _gone(*_):
        ended.set()

    @session.on("close")
    def _closed(*_):  # the learner left (or hung up)
        ended.set()

    await ended.wait()
    billing.cancel()
    # Unused prepaid listening goes back to the learner.
    used = time.monotonic() - started
    await sync_to_async(live.refund_listening)(user, max(0.0, paid - used))
    await sync_to_async(live.call_ended)(user.pk, room.name)
    await session.aclose()
    ctx.shutdown()


def server():
    from django.conf import settings
    from livekit.agents import AgentServer

    srv = AgentServer(setup_fnc=prewarm)
    srv.rtc_session(entrypoint, agent_name=settings.LIVEKIT_AGENT_NAME)
    return srv
