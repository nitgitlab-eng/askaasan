"""Live conversation listening (ws/voice-stream/): the browser's mic is streamed through the server to Deepgram live.
No real Deepgram: a local fake Deepgram WebSocket server (websockets.serve) stands in for wss://api.deepgram.com."""

import asyncio
import json
from urllib.parse import parse_qs, urlparse

import pytest
from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from websockets.asyncio.server import serve

from apps.providers.models import ProviderConfig, UsageCounter
from apps.providers.voice import stream
from config.asgi import application

pytestmark = pytest.mark.django_db(transaction=True)

KEY = "dg-live-secret-key-1234"
FRAME = b"\x01\x00" * 1600  # 100 ms of 16 kHz PCM16


class FakeDeepgram:
    """Records what it was sent; answers each audio frame from a script of Deepgram messages."""

    def __init__(self, script=None, status=None):
        self.script = list(script or [])
        self.status = status
        self.headers, self.query, self.frames, self.texts = None, {}, [], []
        self.closed = asyncio.Event()

    async def handler(self, ws):
        self.headers = ws.request.headers
        self.query = {k: v[0] for k, v in parse_qs(urlparse(ws.request.path).query).items()}
        try:
            async for msg in ws:
                if isinstance(msg, bytes):
                    self.frames.append(msg)
                    if self.script:
                        await ws.send(json.dumps(self.script.pop(0)))
                else:
                    self.texts.append(json.loads(msg))
                    if json.loads(msg).get("type") == "CloseStream":
                        await ws.send(json.dumps({"type": "Metadata", "duration": 1.0}))
                        break
        finally:
            self.closed.set()

    def process_request(self, connection, request):
        if self.status:
            return connection.respond(self.status, "nope\n")
        return None


@pytest.fixture
async def deepgram(monkeypatch):
    servers = []

    async def start(script=None, status=None):
        fake = FakeDeepgram(script, status)
        server = await serve(fake.handler, "127.0.0.1", 0, process_request=fake.process_request)
        servers.append(server)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr(stream, "DEEPGRAM_URL", f"ws://127.0.0.1:{port}/v1/listen")
        return fake

    yield start
    for s in servers:
        s.close()
        await s.wait_closed()


@sync_to_async
def use_deepgram(key=KEY, limits=None, provider="deepgram"):
    row = ProviderConfig(capability="stt", provider=provider, model="nova-3", limits=limits or {})
    row.set_key(key)
    row.save()


@sync_to_async
def seconds_charged():
    row = UsageCounter.objects.filter(metric="stt_seconds").first()
    return row.amount if row else 0.0


async def connect(token):
    comm = WebsocketCommunicator(
        application,
        "/ws/voice-stream/",
        headers=[(b"host", b"localhost"), (b"origin", b"http://localhost:5173")],
    )
    ok, _ = await comm.connect()
    assert ok
    await comm.send_json_to({"type": "auth", "token": token})
    return comm


async def started(token, lang="en"):
    comm = await connect(token)
    assert (await comm.receive_json_from())["type"] == "ready"
    await comm.send_json_to({"type": "start", "lang": lang})
    assert (await comm.receive_json_from(timeout=5))["type"] == "started"
    return comm


def results(text, is_final=False, speech_final=False):
    return {
        "type": "Results",
        "is_final": is_final,
        "speech_final": speech_final,
        "channel": {"alternatives": [{"transcript": text, "confidence": 0.9}]},
    }


async def test_streams_audio_to_deepgram_and_maps_its_messages(auth, deepgram):
    _, data = auth
    await use_deepgram()
    fake = await deepgram(
        [
            {"type": "SpeechStarted", "channel": [0, 1], "timestamp": 0.2},
            results("what is"),
            results("what is a prompt", is_final=True),
            results("", is_final=True, speech_final=True),
            {"type": "UtteranceEnd", "channel": [0, 1], "last_word_end": 1.9},
            {"type": "UtteranceEnd", "channel": [0, 1], "last_word_end": -1},  # ignored
        ]
    )
    comm = await started(data["access"])
    events = []
    for _ in range(6):
        await comm.send_to(bytes_data=FRAME)
    for _ in range(5):
        events.append(await comm.receive_json_from(timeout=5))
    assert events == [
        {"type": "speech_started"},
        {"type": "interim", "text": "what is"},
        {"type": "final", "text": "what is a prompt", "speech_final": False},
        {"type": "final", "text": "", "speech_final": True},
        {"type": "utterance_end"},
    ]
    assert await comm.receive_nothing(timeout=0.3)
    assert fake.frames[:6] == [FRAME] * 6  # forwarded untouched
    q = fake.query
    assert q["model"] == "nova-3" and q["language"] == "en-IN"
    assert (q["encoding"], q["sample_rate"], q["channels"]) == ("linear16", "16000", "1")
    assert q["interim_results"] == "true" and q["smart_format"] == "true" and q["vad_events"] == "true"
    assert (q["endpointing"], q["utterance_end_ms"]) == ("300", "1000")
    assert fake.headers["Authorization"] == f"Token {KEY}"  # the key goes to Deepgram only
    assert KEY not in json.dumps(events)

    await comm.send_json_to({"type": "stop"})
    await asyncio.wait_for(fake.closed.wait(), 3)
    assert {"type": "CloseStream"} in fake.texts
    assert (await comm.receive_output(timeout=3))["type"] == "websocket.close"
    # 0.6 s streamed: a 5 s block was prepaid, and the unused rest refunded on close.
    assert await seconds_charged() == pytest.approx(0.6, abs=0.01)
    await comm.disconnect()


async def test_tamil_uses_nova3_tamil(auth, deepgram):
    _, data = auth
    await use_deepgram()
    fake = await deepgram()
    comm = await started(data["access"], lang="ta")
    assert fake.query["language"] == "ta" and fake.query["model"] == "nova-3"
    await comm.disconnect()


async def test_keepalive_when_the_mic_goes_quiet(auth, deepgram, monkeypatch):
    _, data = auth
    monkeypatch.setattr(stream, "TICK", 0.05)
    monkeypatch.setattr(stream, "KEEPALIVE_AFTER", 0.1)
    await use_deepgram()
    fake = await deepgram()
    comm = await started(data["access"])
    await asyncio.sleep(0.4)
    assert {"type": "KeepAlive"} in fake.texts
    await comm.disconnect()


async def test_bad_token_is_refused(deepgram):
    await use_deepgram()
    fake = await deepgram()
    comm = await connect("not-a-token")
    ev = await comm.receive_json_from()
    assert ev == {"type": "error", "code": "unauthorized"}
    assert (await comm.receive_output())["type"] == "websocket.close"
    assert fake.headers is None  # Deepgram was never opened


async def test_start_before_auth_is_refused(deepgram):
    comm = WebsocketCommunicator(
        application,
        "/ws/voice-stream/",
        headers=[(b"host", b"localhost"), (b"origin", b"http://localhost:5173")],
    )
    await comm.connect()
    await comm.send_json_to({"type": "start", "lang": "en"})
    assert (await comm.receive_json_from())["code"] == "unauthorized"


async def test_foreign_origin_is_refused():
    comm = WebsocketCommunicator(
        application,
        "/ws/voice-stream/",
        headers=[(b"host", b"localhost"), (b"origin", b"https://evil.example")],
    )
    ok, _ = await comm.connect()
    assert not ok


async def test_no_deepgram_configured_is_a_clean_error(auth):
    _, data = auth
    comm = await connect(data["access"])
    assert (await comm.receive_json_from())["type"] == "ready"
    await comm.send_json_to({"type": "start", "lang": "en"})
    assert (await comm.receive_json_from())["code"] == "streaming_unavailable"


async def test_deepgram_without_a_key_is_a_clean_error(auth, monkeypatch):
    _, data = auth
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    await use_deepgram(key="")
    comm = await connect(data["access"])
    await comm.receive_json_from()
    await comm.send_json_to({"type": "start", "lang": "en"})
    assert (await comm.receive_json_from())["code"] == "streaming_unavailable"
    assert await seconds_charged() == 0


async def test_rejected_key_is_reported_without_the_key(auth, deepgram):
    _, data = auth
    await use_deepgram()
    await deepgram(status=401)
    comm = await connect(data["access"])
    await comm.receive_json_from()
    await comm.send_json_to({"type": "start", "lang": "en"})
    ev = await comm.receive_json_from(timeout=5)
    assert ev == {"type": "error", "code": "invalid_key"}
    await asyncio.sleep(0.1)
    assert await seconds_charged() == 0  # the prepaid block came back


async def test_provider_budget_stops_the_stream(auth, deepgram, monkeypatch):
    _, data = auth
    monkeypatch.setattr(stream, "BLOCK_SECONDS", 1.0)
    monkeypatch.setattr(stream, "BURST_SECONDS", 10.0)
    await use_deepgram(limits={"stt_seconds_per_day": 1.5})
    fake = await deepgram()
    comm = await started(data["access"])
    for _ in range(10):  # 1.0 s: inside the first block
        await comm.send_to(bytes_data=FRAME)
    await comm.send_to(bytes_data=FRAME)  # needs a second block: 2 s > 1.5 s
    ev = await comm.receive_json_from(timeout=5)
    assert ev["code"] == "voice_budget_exceeded"
    assert (await comm.receive_output(timeout=3))["type"] == "websocket.close"
    assert len(fake.frames) == 10  # the over-limit frame never reached Deepgram
    assert await seconds_charged() <= 1.5


async def test_plan_voice_minutes_stop_the_stream(auth, deepgram):
    _, data = auth
    await use_deepgram()

    @sync_to_async
    def used_up():
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.get(email="kavya@example.com")
        UsageCounter.objects.create(
            user=user, metric="stt_seconds", amount=10 * 60
        )  # the free plan's 10 minutes

    await used_up()
    fake = await deepgram()
    comm = await connect(data["access"])
    await comm.receive_json_from()
    await comm.send_json_to({"type": "start", "lang": "en"})
    ev = await comm.receive_json_from(timeout=5)
    assert ev["code"] == "plan_limit" and ev["limit"] == "voice_minutes_per_day"
    assert fake.headers is None


async def test_audio_faster_than_real_time_is_refused(auth, deepgram, monkeypatch):
    _, data = auth
    monkeypatch.setattr(stream, "BURST_SECONDS", 0.5)
    await use_deepgram()
    await deepgram()
    comm = await started(data["access"])
    for _ in range(8):
        await comm.send_to(bytes_data=FRAME)
    assert (await comm.receive_json_from(timeout=5))["code"] == "rate_limited"


async def test_oversized_frame_is_refused(auth, deepgram):
    _, data = auth
    await use_deepgram()
    await deepgram()
    comm = await started(data["access"])
    await comm.send_to(bytes_data=b"\x00" * (stream.MAX_FRAME_BYTES + 2))
    assert (await comm.receive_json_from(timeout=5))["code"] == "bad_audio"


async def test_session_length_is_capped(auth, deepgram, settings, monkeypatch):
    _, data = auth
    settings.VOICE_STREAM_MAX_MINUTES = 0.0001  # the floor is 1 s
    monkeypatch.setattr(stream, "TICK", 0.1)
    await use_deepgram()
    fake = await deepgram()
    comm = await started(data["access"])
    ev = await comm.receive_json_from(timeout=5)
    assert ev["code"] == "session_limit"
    await asyncio.wait_for(fake.closed.wait(), 3)


async def test_second_start_on_one_socket_is_refused(auth, deepgram):
    _, data = auth
    await use_deepgram()
    await deepgram()
    comm = await started(data["access"])
    await comm.send_json_to({"type": "start", "lang": "en"})
    assert (await comm.receive_json_from())["code"] == "already_started"
    await comm.disconnect()


def test_voice_config_reports_streaming(auth, monkeypatch):
    client, _ = auth
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    assert client.get("/api/voice/config/").data["stt"]["streaming"] is False
    row = ProviderConfig(capability="stt", provider="deepgram", model="nova-3")
    row.save()
    assert client.get("/api/voice/config/").data["stt"]["streaming"] is False  # no key yet
    row.set_key(KEY)
    row.save()
    body = client.get("/api/voice/config/").data
    assert body["stt"] == {"engine": "server", "provider": "deepgram", "streaming": True}
    assert KEY not in json.dumps(body)


def test_translate_ignores_metadata_and_empty_interims():
    assert stream.translate({"type": "Metadata"}) is None
    assert stream.translate(results("")) is None
    assert stream.translate(results("", is_final=True)) is None
