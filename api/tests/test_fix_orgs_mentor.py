"""Fix pass (agent D): mentor socket — bad ids answered with an error (R42), no quota used when nothing is answered (R50),
refusal fallback in the learner's language (R51), document access re-checked on every turn (S32)."""

import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator

from apps.accounts.models import User
from apps.billing.models import UsageEvent
from apps.docs.models import Chunk, Document
from apps.orgs.models import Membership, Organization, OrgDocument
from config.asgi import application
from llm.base import StreamEvent

pytestmark = pytest.mark.django_db(transaction=True)


async def _ready(token):
    comm = WebsocketCommunicator(
        application,
        "/ws/assistant/",
        headers=[(b"host", b"localhost"), (b"origin", b"http://localhost:5173")],
    )
    assert (await comm.connect())[0]
    await comm.send_json_to({"type": "auth", "token": token})
    while (await comm.receive_json_from())["type"] != "ready":
        pass
    return comm


async def _until(comm, *types):
    while True:
        ev = await comm.receive_json_from(timeout=5)
        if ev["type"] in types:
            return ev


def _used(email):
    return UsageEvent.objects.filter(user__email=email, metric="mentor_message").count()


async def test_bad_ids_get_an_error_and_use_no_quota(auth):
    _, data = auth
    comm = await _ready(data["access"])
    for bad in (
        {"conversation_id": "abc"},
        {"document_id": "1; drop"},
        {"conversation_id": 999999},
        {"document_id": 999999},
    ):
        await comm.send_json_to({"type": "message", "text": "hello", **bad})
        ev = await _until(comm, "error")
        assert ev["code"] == "not_found"
    assert await database_sync_to_async(_used)("kavya@example.com") == 0
    await comm.send_json_to({"type": "message", "text": "hello"})
    await _until(comm, "done")
    assert await database_sync_to_async(_used)("kavya@example.com") == 1  # a real reply is counted
    await comm.disconnect()


async def test_refusal_fallback_follows_learner_language(auth, monkeypatch):
    from apps.mentor import consumers

    class Refuser:
        async def stream(self, req):
            yield StreamEvent(done=True, stop_reason="refusal")

    monkeypatch.setattr(consumers, "resolve", lambda cap: (Refuser(), "m"))
    _, data = auth
    comm = await _ready(data["access"])
    await comm.send_json_to({"type": "message", "text": "something off-topic"})
    await _until(comm, "done")
    from apps.mentor.models import Message

    msg = await database_sync_to_async(lambda: Message.objects.filter(role="assistant").last().content)()
    assert msg == consumers.REFUSAL["en"]  # English learner, not the Tamil text
    await comm.disconnect()


def _kb_doc(learner_email):
    owner = User.objects.create_user("own@kb.in", "Kb#2026passwd")
    org = Organization.objects.create(name="KB Co", slug="kbco", kind="company")
    Membership.objects.create(org=org, user=owner, role="owner")
    Membership.objects.create(org=org, user=User.objects.get(email=learner_email), role="learner")
    doc = Document.objects.create(owner=owner, title="Handbook", filename="h.txt", kind="txt")
    Chunk.objects.create(
        document=doc, index=0, text="Leave policy: every employee gets 12 casual leaves a year."
    )
    od = OrgDocument.objects.create(
        org=org, document=doc, source="kb", status="ready", learners_can_read=True, shared_by=owner
    )
    return doc.id, od.id


async def test_document_access_rechecked_every_turn(auth):
    _, data = auth
    doc_id, od_id = await database_sync_to_async(_kb_doc)("kavya@example.com")
    comm = await _ready(data["access"])
    await comm.send_json_to({"type": "message", "text": "leave policy?", "document_id": doc_id})
    conv_id = (await _until(comm, "start"))["conversation_id"]
    await _until(comm, "done")
    await database_sync_to_async(OrgDocument.objects.filter(pk=od_id).update)(
        learners_can_read=False
    )  # admin: staff-only
    await comm.send_json_to({"type": "message", "text": "casual leaves?", "conversation_id": conv_id})
    assert (await _until(comm, "error", "start"))["type"] == "error"
    await comm.disconnect()
