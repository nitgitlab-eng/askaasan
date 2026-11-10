"""AI workshops: REST endpoints and the learner-paced engine (services.py), with the fake LLM provider."""

import struct
import zlib
from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import StaffRole, User
from apps.credentials.models import Certificate
from apps.workshops import services
from apps.workshops.content import seed
from apps.workshops.models import (
    Workshop,
    WorkshopEnrollment,
    WorkshopEvent,
    WorkshopRun,
    WorkshopSession,
    WorkshopTurn,
)
from llm.providers import fake_provider

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _seeded(db):
    seed()


def _png() -> bytes:
    """A real (tiny) PNG."""

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    raw = b"\x00\xff\x00\x00"
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _user(auth):
    return User.objects.get(email="kavya@example.com")


def _other():
    c = APIClient()
    res = c.post(
        "/api/users/register/", {"email": "arun@example.com", "password": "Tamil#Learn2026"}, format="json"
    )
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")
    return c


def _public_run(slug="quick-check", **kw):
    return WorkshopRun.objects.create(
        workshop=Workshop.objects.get(slug=slug),
        audience="public",
        starts_at=kw.pop("starts_at", timezone.now()),
        status="live",
        **kw,
    )


def _session(user, slug="quick-check", started=True, **run_kw):
    run = _public_run(slug, **run_kw)
    e = WorkshopEnrollment.objects.create(run=run, user=user)
    s = WorkshopSession.objects.create(enrollment=e, user=user, run=run)
    if started:
        s.prereqs_done = {p["key"]: "x" for p in run.workshop.prerequisites}
        s.save()
        assert services.start(s) is None
    return services.load(s.id)


def _explain(s, stage=None, item=None):
    st = services.state(s, stage)
    services.after_turn(
        s.id,
        "Here's an everyday example. Can you say it back?",
        (
            "explained",
            stage if stage is not None else s.stage_index,
            item if item is not None else st["cursor"],
        ),
    )


# ── Runs, enrolment, join window ─────────────────────────────────────


def test_runs_list_shows_public_and_only_my_test_runs(auth):
    client, _ = auth
    me = _user(auth)
    pub = _public_run()
    staff = User.objects.create_user(email="staff@example.com", password="x", is_staff=True)
    WorkshopRun.objects.create(
        workshop=pub.workshop, audience="test", starts_at=timezone.now(), status="live", created_by=staff
    )
    mine = WorkshopRun.objects.create(
        workshop=pub.workshop, audience="test", starts_at=timezone.now(), status="live", created_by=me
    )
    WorkshopRun.objects.create(
        workshop=pub.workshop, audience="public", starts_at=timezone.now(), status="draft"
    )
    rows = client.get("/api/workshops/runs/").data
    assert {r["id"] for r in rows} == {pub.id, mine.id}
    r = next(r for r in rows if r["id"] == pub.id)
    assert r["workshop"]["slug"] == "quick-check" and r["enrolled"] is False and r["session_id"] is None
    assert set(r["workshop"]) >= {"slug", "title", "summary", "level", "duration_minutes"}


def test_enroll_free_and_paid(auth):
    client, _ = auth
    free = _public_run()
    paid = _public_run(price_paise=9900)
    assert client.post(f"/api/workshops/runs/{free.id}/enroll/").data == {"enrolled": True}
    assert client.post(f"/api/workshops/runs/{free.id}/enroll/").data == {"enrolled": True}  # idempotent
    res = client.post(f"/api/workshops/runs/{paid.id}/enroll/")
    assert res.status_code == 402 and res.data["code"] == "payment_required"
    rows = {r["id"]: r for r in client.get("/api/workshops/runs/").data}
    assert rows[free.id]["enrolled"] and not rows[paid.id]["enrolled"]


def test_session_needs_enrolment(auth):
    client, _ = auth
    run = _public_run()
    res = client.post(f"/api/workshops/runs/{run.id}/session/")
    assert res.status_code == 403 and res.data["code"] == "not_enrolled"


def test_join_window_rules(auth):
    client, _ = auth
    now = timezone.now()
    early = _public_run(starts_at=now + timedelta(minutes=30))  # lobby opens 15 min before
    lobby = _public_run(starts_at=now + timedelta(minutes=10))
    late = _public_run(starts_at=now - timedelta(minutes=20))  # late join closes 15 min after
    test = WorkshopRun.objects.create(
        workshop=early.workshop, audience="test", starts_at=now - timedelta(days=3), created_by=_user(auth)
    )
    for r in (early, lobby, late, test):
        WorkshopEnrollment.objects.create(run=r, user=_user(auth))
    res = client.post(f"/api/workshops/runs/{early.id}/session/")
    assert res.status_code == 409 and res.data["code"] == "too_early"
    res = client.post(f"/api/workshops/runs/{late.id}/session/")
    assert res.status_code == 409 and res.data["code"] == "too_late"
    ok = client.post(f"/api/workshops/runs/{lobby.id}/session/")
    assert ok.status_code == 200 and ok.data["status"] == "prereq"
    assert client.post(f"/api/workshops/runs/{test.id}/session/").status_code == 200  # test runs: any time
    # An existing session can always be resumed, even after the join window closed.
    WorkshopRun.objects.filter(pk=lobby.pk).update(starts_at=now - timedelta(hours=5))
    again = client.post(f"/api/workshops/runs/{lobby.id}/session/")
    assert again.status_code == 200 and again.data["id"] == ok.data["id"]


# ── Prerequisites and start ──────────────────────────────────────────


def test_prerequisites_gate_the_start(auth):
    client, _ = auth
    s = _session(_user(auth), started=False)
    url = f"/api/workshops/sessions/{s.id}"
    body = client.get(f"{url}/").data
    assert body["status"] == "prereq" and body["ready"] is False and body["started_at"] is None
    assert [p["key"] for p in body["prerequisites"]] == ["chat_tool", "ten_minutes"]
    res = client.post(f"{url}/start/", {"proctor_notice": True}, format="json")
    assert res.status_code == 409 and res.data["code"] == "prereqs_incomplete"
    assert client.post(f"{url}/prereq/", {"key": "nope", "done": True}, format="json").status_code == 400
    client.post(f"{url}/prereq/", {"key": "chat_tool", "done": True}, format="json")
    assert client.post(f"{url}/start/", {"proctor_notice": True}, format="json").status_code == 409
    body = client.post(f"{url}/prereq/", {"key": "ten_minutes", "done": True}, format="json").data
    assert body["ready"] is True and all(p["done"] for p in body["prerequisites"])
    assert client.post(f"{url}/start/", {"proctor_notice": False}, format="json").status_code == 400
    body = client.post(f"{url}/start/", {"proctor_notice": True}, format="json").data
    assert body["status"] == "active" and body["proctor_notice_seen"] is True
    s.refresh_from_db()
    assert s.planned_end - s.started_at == timedelta(minutes=10)
    assert s.grace_end - s.planned_end == timedelta(minutes=10)
    assert body["final"]["mcqs"] and "answer" not in body["final"]["mcqs"][0]  # keys never leave the server


def test_sessions_are_owner_only(auth):
    client, _ = auth
    s = _session(_user(auth))
    other = _other()
    base = f"/api/workshops/sessions/{s.id}"
    assert other.get(f"{base}/").status_code == 404
    assert other.get(f"{base}/transcript/").status_code == 404
    assert other.post(f"{base}/prereq/", {"key": "chat_tool", "done": True}, format="json").status_code == 404
    assert other.post(f"{base}/start/", {"proctor_notice": True}, format="json").status_code == 404
    assert other.post(f"{base}/help/", {"error_text": "x"}).status_code == 404
    assert other.post(f"{base}/final/", {"answers": {}, "practical": ""}, format="json").status_code == 404
    assert client.get(f"{base}/").status_code == 200


def test_feature_switch_blocks_workshops(auth):
    from apps.orgs.models import Membership, Organization

    client, _ = auth
    org = Organization.objects.create(name="S", slug="s-ws", kind="school", features={"workshops": False})
    Membership.objects.create(org=org, user=_user(auth), role="learner")
    res = client.get("/api/workshops/runs/")
    assert res.status_code == 403 and res.data["code"] == "feature_off"


# ── Help panel ───────────────────────────────────────────────────────


@pytest.fixture
def captured(monkeypatch):
    seen = []
    orig = fake_provider.FakeProvider.complete

    async def complete(self, req):
        seen.append(req)
        return await orig(self, req)

    monkeypatch.setattr(fake_provider.FakeProvider, "complete", complete)
    return seen


def _media_files():
    root = Path(settings.MEDIA_ROOT)
    return {p for p in root.rglob("*") if p.is_file()} if root.exists() else set()


def test_help_with_screenshot_keeps_only_the_summary(auth, captured):
    from django.core.files.uploadedfile import SimpleUploadedFile

    client, _ = auth
    s = _session(_user(auth))
    before = _media_files()
    img = SimpleUploadedFile("shot.png", _png(), content_type="image/png")
    res = client.post(
        f"/api/workshops/sessions/{s.id}/help/", {"image": img, "note": "my sheet"}, format="multipart"
    )
    assert res.status_code == 200
    assert res.data["reply_md"] and 0 < len(res.data["summary"]) <= 200
    assert captured[-1].messages[0].images and captured[-1].messages[0].images[0].media_type == "image/png"
    ev = WorkshopEvent.objects.get(session=s, type="help_screenshot")
    assert ev.data == {"summary": res.data["summary"]}
    assert not WorkshopTurn.objects.filter(session=s).exists()
    assert _media_files() == before  # nothing written to disk


def test_help_with_error_text(auth, captured):
    client, _ = auth
    s = _session(_user(auth))
    secret_log = "Traceback: ERROR formula parse API_KEY=sk-not-real-123"
    res = client.post(f"/api/workshops/sessions/{s.id}/help/", {"error_text": secret_log})
    assert res.status_code == 200 and res.data["summary"]
    assert "<error_text>" in captured[-1].messages[0].content and not captured[-1].messages[0].images
    ev = WorkshopEvent.objects.get(session=s, type="help_error")
    assert set(ev.data) == {"summary"} and "sk-not-real" not in str(ev.data)
    assert not WorkshopTurn.objects.filter(text__contains="sk-not-real").exists()


def test_help_validation_budget_and_throttle(auth, settings):
    from django.core.files.uploadedfile import SimpleUploadedFile

    client, _ = auth
    s = _session(_user(auth))
    url = f"/api/workshops/sessions/{s.id}/help/"
    assert client.post(url, {}).data["code"] == "nothing_to_check"
    assert client.post(url, {"error_text": "x" * 4001}).data["code"] == "too_long"
    bad = SimpleUploadedFile("x.png", b"<script>alert(1)</script>", content_type="image/png")
    assert client.post(url, {"image": bad}, format="multipart").data["code"] == "bad_image"
    big = SimpleUploadedFile("x.png", b"\x89PNG" + b"\x00" * (4 * 1024 * 1024 + 10), content_type="image/png")
    assert client.post(url, {"image": big}, format="multipart").data["code"] == "image_too_large"
    WorkshopSession.objects.filter(pk=s.pk).update(ai_units=settings.WORKSHOP_SESSION_AI_UNITS)
    res = client.post(url, {"error_text": "oops"})
    assert res.status_code == 429 and res.data == {"code": "budget"}
    WorkshopSession.objects.filter(pk=s.pk).update(ai_units=0)
    settings.WORKSHOP_HELP_PER_HOUR = 1
    from django.core.cache import cache

    cache.clear()
    assert client.post(url, {"error_text": "oops"}).status_code == 200
    limited = client.post(url, {"error_text": "oops"})
    assert limited.status_code == 429 and limited.data["code"] == "rate_limited"


# ── Final, certificate ───────────────────────────────────────────────


def _to_final(s):
    idx = next(i for i, st in enumerate(s.run.workshop.agenda) if st["kind"] == "assessment")
    WorkshopSession.objects.filter(pk=s.pk).update(stage_index=idx)


def _right(w):
    return {str(i): m["answer"] for i, m in enumerate(w.final["mcqs"])}


def test_final_graded_locally_and_pass_issues_certificate_once(auth, captured):
    client, _ = auth
    me = _user(auth)
    s = _session(me)
    w = s.run.workshop
    url = f"/api/workshops/sessions/{s.id}/final/"
    res = client.post(url, {"answers": _right(w), "practical": "x"}, format="json")
    assert res.status_code == 409 and res.data["code"] == "not_at_final"
    _to_final(s)
    res = client.post(
        url,
        {"answers": _right(w), "practical": "I asked about Ohm's law; I'd check the number."},
        format="json",
    )
    assert res.status_code == 200
    assert res.data["passed"] is True and res.data["mcq"] == {"correct": 3, "total": 3}
    assert res.data["score"] == pytest.approx(0.6 * 1 + 0.4 * 0.75)  # fake practical grade = 0.75
    cert = Certificate.objects.get(user=me)
    assert cert.kind == "workshop" and cert.workshop_run_id == s.run_id and cert.issuer_name == "Aasan"
    assert cert.dedupe == f"{me.id}:workshop:{w.id}" and cert.detail["minutes"] == 10
    assert res.data["certificate"]["code"] == cert.code and res.data["certificate"]["url"].endswith(cert.code)
    # Keys never reach the model: no MCQ question or option text appears in any prompt.
    prompts = " ".join(r.system + " ".join(m.content for m in r.messages) for r in captured)
    for m in w.final["mcqs"]:
        assert m["q"] not in prompts and all(o not in prompts for o in m["options"])
    s.refresh_from_db()
    assert s.status == "submitted" and s.passed
    assert (
        client.post(url, {"answers": {}, "practical": ""}, format="json").data["code"] == "no_attempts_left"
    )
    # Passing the same workshop again in another run keeps the one certificate.
    s2 = _session(me)
    _to_final(s2)
    res2 = client.post(
        f"/api/workshops/sessions/{s2.id}/final/", {"answers": _right(w), "practical": "again"}, format="json"
    )
    assert res2.data["certificate"]["code"] == cert.code and Certificate.objects.filter(user=me).count() == 1
    from apps.credentials.pdf import render

    assert render(cert).startswith(b"%PDF")
    pub = APIClient().get(f"/api/credentials/verify/{cert.code}/").data
    assert pub["kind"] == "workshop" and pub["duration_minutes"] == 10


def test_final_three_attempts_best_kept_no_auto_submit(auth):
    client, _ = auth
    s = _session(_user(auth))
    _to_final(s)
    url = f"/api/workshops/sessions/{s.id}/final/"
    wrong = {
        str(i): (m["answer"] + 1) % len(m["options"]) for i, m in enumerate(s.run.workshop.final["mcqs"])
    }
    first = client.post(
        url, {"answers": wrong, "practical": ""}, format="json"
    ).data  # empty practical → 0, no AI
    assert first["passed"] is False and first["score"] == 0 and first["attempts_left"] == 2
    s.refresh_from_db()
    assert s.status != "submitted"  # still free to try again
    one_right = dict(wrong, **{"0": s.run.workshop.final["mcqs"][0]["answer"]})
    client.post(url, {"answers": one_right, "practical": ""}, format="json")
    third = client.post(url, {"answers": wrong, "practical": ""}, format="json").data
    assert third["attempts_left"] == 0 and third["best_score"] == pytest.approx(0.2)
    s.refresh_from_db()
    assert s.status == "submitted" and not s.passed and s.final_score == pytest.approx(0.2)
    assert client.post(url, {"answers": wrong, "practical": ""}, format="json").status_code == 409
    assert not Certificate.objects.exists()


# ── Admin test run ───────────────────────────────────────────────────


def test_admin_test_run_is_staff_only(auth):
    client, _ = auth
    assert client.get("/api/admin/workshops/").status_code == 403
    assert client.post("/api/admin/workshops/quick-check/test-run/").status_code == 403
    me = _user(auth)
    me.is_staff = True
    me.save()
    StaffRole.objects.create(user=me, roles=["superadmin"])
    slugs = {w["slug"] for w in client.get("/api/admin/workshops/").data}
    assert slugs == {"quick-check", "ai-agentic", "prompt-engineering", "ai-in-your-world"}
    res = client.post("/api/admin/workshops/quick-check/test-run/")
    assert res.status_code == 201
    run = WorkshopRun.objects.get(pk=res.data["run_id"])
    assert run.audience == "test" and run.created_by == me
    assert WorkshopSession.objects.get(pk=res.data["session_id"]).user == me
    assert client.post("/api/admin/workshops/nope/test-run/").status_code == 404
    rows = client.get("/api/workshops/runs/").data
    assert any(r["id"] == run.id and r["session_id"] == res.data["session_id"] for r in rows)
    assert all(r["id"] != run.id for r in _other().get("/api/workshops/runs/").data)


# ── Seeded content ───────────────────────────────────────────────────


def test_seeded_workshops_are_complete():
    assert seed() == 4  # idempotent
    assert Workshop.objects.count() == 4
    for w in Workshop.objects.all():
        assert w.prerequisites and w.proctoring == "off"
        assert sum(st["minutes"] for st in w.agenda) == w.duration_minutes
        assert w.agenda[-1]["kind"] == "assessment"
        for st in w.agenda:
            assert st["kind"] in ("teach", "check", "diy", "build", "agent_build", "assessment")
            if st["kind"] == "teach":
                assert len(st["concepts"]) >= 2
            if st["kind"] in ("diy", "agent_build"):
                assert st["steps"]
        for m in w.final["mcqs"]:
            assert 0 <= m["answer"] < len(m["options"])
        assert w.final["practical"]["rubric"]
    assert {w.slug: w.duration_minutes for w in Workshop.objects.all()} == {
        "quick-check": 10,
        "ai-agentic": 120,
        "prompt-engineering": 90,
        "ai-in-your-world": 90,
    }


# ── Engine: learner-paced, concept by concept ────────────────────────


def test_next_requires_start_and_explanation(auth):
    s = _session(_user(auth), started=False)
    assert services.on_next(s.id).error == "not_started"
    s = _session(_user(auth))
    assert services.on_next(s.id).error == "not_explained"


def test_concepts_progress_only_on_next(auth):
    s = _session(_user(auth), slug="prompt-engineering")
    n = len(s.run.workshop.agenda[0]["concepts"])
    _explain(s)
    out = services.on_say(s.id, "It only knows what I tell it, like a new tuition teacher.")
    assert out.progress and out.note and "technical term" in out.note
    s = services.load(s.id)
    st = services.state(s)
    assert st["items"][0]["done"] and st["items"][0]["score"] == 0.9 and not st["items"][0]["skipped"]
    assert st["cursor"] == 0 and s.stage_index == 0  # never auto-advances
    assert WorkshopEvent.objects.filter(session=s, type="concept_done").count() == 1
    out = services.on_next(s.id)
    assert out.note and out.after == ("explained", 0, 1) and "concept 2 of" in out.note
    s = services.load(s.id)
    assert services.state(s)["cursor"] == 1 and s.stage_index == 0
    # The learner may skip a check once a concept was explained: recorded as skipped.
    for i in range(1, n):
        _explain(services.load(s.id), 0, i)
        services.on_next(s.id)
    s = services.load(s.id)
    st0 = services.state(s, 0)
    assert all(it["done"] for it in st0["items"]) and st0["items"][1]["skipped"]
    assert WorkshopEvent.objects.filter(session=s, type="concept_skipped").count() == n - 1
    assert s.stage_index == 1 and WorkshopEvent.objects.filter(session=s, type="stage_start").count() == 2


def test_check_retries_then_moves_on_after_three_tries(auth, monkeypatch):
    s = _session(_user(auth))
    _explain(s)
    monkeypatch.setitem(
        fake_provider.CANNED, "[[TASK:workshop_check]]", {"answered": False, "score": 0, "note": ""}
    )
    out = services.on_say(s.id, "What is a pattern?")
    assert "asked something" in out.note and services.state(services.load(s.id))["items"][0]["tries"] == 0
    monkeypatch.setitem(
        fake_provider.CANNED, "[[TASK:workshop_check]]", {"answered": True, "score": 0.2, "note": "vague"}
    )
    for n in (1, 2):
        out = services.on_say(s.id, "no idea")
        assert "different way" in out.note and not out.progress
        assert services.state(services.load(s.id))["items"][0]["tries"] == n
    out = services.on_say(s.id, "still no idea")
    it = services.state(services.load(s.id))["items"][0]
    assert out.progress and it["done"] and it["tries"] == 3 and "three times" in out.note
    assert services.load(s.id).stage_index == 0


def test_diy_step_done_without_advancing(auth):
    s = _session(_user(auth))
    WorkshopSession.objects.filter(pk=s.pk).update(stage_index=1)  # quick-check: stage 1 is DIY
    s = services.load(s.id)
    assert services.on_step_done(s.id, 3).error == "bad_step"
    assert services.on_step_done(s.id, "x").error == "bad_step"
    out = services.on_step_done(s.id, 0)
    assert out.progress and "what did they see" in out.note
    s = services.load(s.id)
    st = services.state(s)
    assert st["items"][0]["done"] and st["cursor"] == 0 and s.stage_index == 1
    assert WorkshopEvent.objects.filter(session=s, type="diy_step_done").exists()
    assert "saw after the step" in services.on_say(s.id, "It gave me a train example").note
    assert services.on_step_done(s.id, 0).progress and not services.on_step_done(s.id, 0).note  # idempotent
    services.on_next(s.id)
    assert services.load(s.id).stage_index == 2


def test_not_a_diy_stage_rejects_step_done(auth):
    s = _session(_user(auth))
    assert services.on_step_done(s.id, 0).error == "not_diy"


def test_controls_and_language(auth):
    s = _session(_user(auth))
    assert "SLOWER" in services.on_control(s.id, "slower").note
    assert "ANOTHER EXAMPLE" in services.on_control(s.id, "example").note
    out = services.on_control(s.id, "tamil")
    assert out.progress and "Tamil" in out.note
    assert services.load(s.id).stage_state["_lang"] == "ta"
    assert services.on_control(s.id, "dance").error == "bad_control"


def test_prereq_screen_ai_helps_with_setup(auth):
    s = _session(_user(auth), started=False)
    out = services.on_say(s.id, "How do I open ChatGPT?")
    assert "getting ready" in out.note and "<prerequisites>" in out.note and "<learner_said>" in out.note


def test_pace_labels_with_a_frozen_clock(auth, monkeypatch):
    s = _session(_user(auth), slug="prompt-engineering")
    t0 = s.started_at
    assert services.pace(s, t0 + timedelta(minutes=5))["status"] == "on_track"
    behind = services.pace(s, t0 + timedelta(minutes=20))  # first stage is planned for 15 min
    assert behind["status"] == "behind" and behind["minutes_left"] == 70 and "Next" in behind["message"]
    grace = services.pace(s, t0 + timedelta(minutes=91))
    assert (
        grace["status"] == "in_grace"
        and grace["message"] == "Your timeline is over — you're in a grace period."
    )
    assert grace["minutes_left"] == 29
    assert services.pace(s, t0 + timedelta(minutes=125))["status"] == "overtime"
    monkeypatch.setattr(services, "now", lambda: t0 + timedelta(minutes=130))
    p, announce = services.tick(s.id)
    s = services.load(s.id)
    assert p["status"] == "overtime" and announce and s.status == "overtime"
    # Never auto-advances or auto-submits: the learner simply continues.
    assert s.stage_index == 0 and s.final_attempts == 0 and s.ended_at is None
    _explain(s)
    assert services.on_next(s.id).error is None
    assert services.claim_grace(s.id) and not services.claim_grace(s.id)


def test_safety_cap_pauses_ai_but_never_blocks(auth, monkeypatch):
    s = _session(_user(auth))
    assert services.ai_paused(s) is None
    later = s.started_at + timedelta(minutes=31)  # 3 × 10 min, the same day
    monkeypatch.setattr(services, "now", lambda: later)
    if timezone.localdate(later) != timezone.localdate(s.started_at):
        pytest.skip("crosses midnight")
    assert services.spend(s.id, 900) == "cap"
    assert services.on_next(s.id).error is None  # unexplained, but a paused AI must not trap the learner
    # The next day, AI turns resume ("continue tomorrow").
    monkeypatch.setattr(services, "now", lambda: later + timedelta(days=1))
    assert services.spend(s.id, 900) is None


def test_budget_charged_per_call(auth, settings):
    s = _session(_user(auth))
    assert services.spend(s.id, 900) is None
    assert services.load(s.id).ai_units == 1
    assert services.spend(s.id, 4000) is None
    assert services.load(s.id).ai_units == 3  # weighted by max_tokens
    settings.WORKSHOP_SESSION_AI_UNITS = 3
    assert services.spend(s.id, 900) == "budget"
    _explain(s)
    assert services.on_say(s.id, "my answer").paused == "budget"
    assert services.spend(s.id, 1500, exempt=True) is None  # final grading never pauses


def test_attention_respects_proctoring(auth):
    s = _session(_user(auth))
    for k in ("hidden", "visible", "blur"):
        services.on_attention(s.id, k)
    assert not WorkshopEvent.objects.filter(
        session=s, type__in=["tab_hidden", "tab_visible", "blur"]
    ).exists()
    WorkshopRun.objects.filter(pk=s.run_id).update(proctoring="activity")
    services.on_attention(s.id, "hidden")
    services.on_attention(s.id, "visible")
    services.on_attention(s.id, "bogus")
    s = services.load(s.id)
    assert list(
        WorkshopEvent.objects.filter(session=s, type__startswith="tab_").values_list("type", flat=True)
    ) == [
        "tab_hidden",
        "tab_visible",
    ]
    assert s.focus_losses == 1 and s.attention_score is not None
    WorkshopSession.objects.filter(pk=s.pk).update(stage_index=1)  # DIY: paused
    services.on_attention(s.id, "hidden")
    assert WorkshopEvent.objects.filter(session=s, type="tab_hidden").count() == 1


def test_transcript_and_export(auth):
    client, _ = auth
    s = _session(_user(auth))
    services.on_say(s.id, "hello host")
    rows = client.get(f"/api/workshops/sessions/{s.id}/transcript/").data
    assert rows[-1]["role"] == "user" and rows[-1]["text"] == "hello host"
    data = client.get("/api/legal/export/")
    assert (
        b"hello host" in b"".join(data.streaming_content)
        if hasattr(data, "streaming_content")
        else b"hello host" in data.content
    )


def test_session_object_shape(auth):
    client, _ = auth
    s = _session(_user(auth), slug="prompt-engineering")
    body = client.get(f"/api/workshops/sessions/{s.id}/").data
    assert set(body) >= {
        "id", "status", "workshop", "prerequisites", "ready", "started_at", "planned_end", "grace_end",
        "stage_index", "stages", "scores", "final_score", "passed", "certificate", "proctoring",
        "proctor_notice_seen", "final", "attempts_left", "pace", "paused",
    }  # fmt: skip
    assert set(body["workshop"]) >= {
        "slug",
        "title",
        "duration_minutes",
        "grace_minutes",
        "proctoring",
        "pass_mark",
    }
    assert set(body["prerequisites"][0]) == {"key", "label", "how_to_md", "done"}
    st = body["stages"][0]
    assert set(st) >= {"key", "kind", "title", "minutes", "concepts", "steps"}
    assert set(st["concepts"][0]) >= {"text", "done"} and st["steps"] == []
    diy = next(x for x in body["stages"] if x["kind"] == "diy")
    assert diy["steps"] and diy["concepts"] == []
    assert body["final"]["practical"] == {"prompt": s.run.workshop.final["practical"]["prompt"]}
    assert all(set(m) == {"q", "options"} for m in body["final"]["mcqs"])
    assert body["attempts_left"] == 3 and body["paused"] is None and body["certificate"] is None
    assert body["pace"]["status"] == "on_track" and body["pace"]["minutes_left"] == 90
    _to_final(s)
    client.post(
        f"/api/workshops/sessions/{s.id}/final/",
        {"answers": _right(s.run.workshop), "practical": "my prompt"},
        format="json",
    )
    cert = client.get(f"/api/workshops/sessions/{s.id}/").data["certificate"]
    assert set(cert) == {"id", "code", "url", "pdf_url"}
    assert (
        cert["url"].endswith(f"/verify/{cert['code']}")
        and cert["pdf_url"] == f"/api/credentials/{cert['id']}/pdf/"
    )
    assert client.get(cert["pdf_url"]).status_code == 200
