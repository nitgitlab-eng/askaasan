"""Exercise the DB-backed provider path (not LLM_FORCE_PROVIDER): resolve()
reads ProviderConfig, which must happen off the event loop."""

import pytest
from channels.testing import WebsocketCommunicator

from apps.learning.models import Curriculum
from apps.providers.models import ProviderConfig
from config.asgi import application


@pytest.fixture
def db_routed_fake(settings, db):
    settings.LLM_FORCE_PROVIDER = ""
    for cap in ("tutor", "utility"):
        ProviderConfig.objects.create(capability=cap, provider="fake", model="fake")


@pytest.mark.django_db
def test_generation_through_db_config(auth, db_routed_fake):
    client, _ = auth
    cid = client.post("/api/learn/curriculums/", {"goal": "AI basics"}, format="json").data["id"]
    assert Curriculum.objects.get(id=cid).status == "ready"


@pytest.mark.django_db
def test_generation_failure_never_hangs(auth, settings, db):
    settings.LLM_FORCE_PROVIDER = ""
    ProviderConfig.objects.create(capability="tutor", provider="anthropic", model="x")  # no key anywhere
    client, _ = auth
    import os

    os.environ.pop("ANTHROPIC_API_KEY", None)
    cid = client.post("/api/learn/curriculums/", {"goal": "AI basics"}, format="json").data["id"]
    cur = Curriculum.objects.get(id=cid)
    assert cur.status == "failed" and cur.error == "provider_not_configured"


@pytest.mark.django_db(transaction=True)
async def test_mentor_ws_through_db_config(auth, db_routed_fake):
    _, data = auth
    comm = WebsocketCommunicator(
        application,
        "/ws/assistant/",
        headers=[(b"host", b"localhost"), (b"origin", b"http://localhost:5173")],
    )
    assert (await comm.connect())[0]
    await comm.send_json_to({"type": "auth", "token": data["access"]})
    assert (await comm.receive_json_from())["type"] == "ready"
    await comm.send_json_to({"type": "message", "text": "hi"})
    types = []
    while True:
        ev = await comm.receive_json_from(timeout=5)
        types.append(ev["type"])
        if ev["type"] in ("done", "error"):
            break
    assert "error" not in types and "delta" in types
    await comm.disconnect()
