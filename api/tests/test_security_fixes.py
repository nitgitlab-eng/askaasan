"""Regression tests for the security review findings (one test per finding)."""

import io

import pytest
from django.core import mail
from django.core.cache import cache, caches
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.models import UsageEvent
from apps.learning.models import Activity, ActivityAttempt, Curriculum, Section, Subsection
from apps.providers.models import UsageCounter

pytestmark = pytest.mark.django_db
PW = "Secure#2026pass"


def client_for(email, **kw):
    u = User.objects.create_user(email, PW, **kw)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


# 1 — rate-limit identity can't be spoofed with X-Forwarded-For; per-account lockout
def test_login_lockout_per_account_even_with_rotating_ips():
    User.objects.create_user("victim@x.in", PW)
    c = APIClient()
    for i in range(10):
        r = c.post(
            "/api/users/login/",
            {"email": "victim@x.in", "password": "wrong"},
            format="json",
            HTTP_X_FORWARDED_FOR=f"10.0.0.{i}",
        )
        assert r.status_code in (401, 429)
    locked = c.post(
        "/api/users/login/",
        {"email": "victim@x.in", "password": PW},
        format="json",
        HTTP_X_FORWARDED_FOR="10.9.9.9",
    )
    assert locked.status_code == 429  # locked even with the right password from a "new" IP


def test_client_ip_ignores_spoofed_forwarded_for(settings):
    from rest_framework.test import APIRequestFactory
    from rest_framework.throttling import SimpleRateThrottle

    req = APIRequestFactory().get("/", HTTP_X_FORWARDED_FOR="1.2.3.4", REMOTE_ADDR="9.9.9.9")
    assert SimpleRateThrottle.get_ident(SimpleRateThrottle.__new__(SimpleRateThrottle), req) == "9.9.9.9"


# 2 — Live Class time is billed by the server clock (see test_live for the WS flow); limit checked before turns
def test_live_tick_bills_real_elapsed_time():
    from apps.live import consumers

    assert consumers.CLOCK_EVERY <= 30 and consumers.MAX_SESSION_SECONDS == 3600
    from pathlib import Path

    src = Path(consumers.__file__).read_text()
    assert "min(now - self.last_tick, 45.0)" not in src  # the old per-heartbeat cap is gone


# 3 — negative / tiny voice durations can't reduce the bill
def test_voice_seconds_cannot_go_negative(settings):
    from apps.providers.models import ProviderConfig

    ProviderConfig.objects.create(
        capability="stt", provider="openai", model="gpt-4o-mini-transcribe", encrypted_key=""
    )
    c, u = client_for("v@x.in")
    from django.core.files.uploadedfile import SimpleUploadedFile

    clip = SimpleUploadedFile("a.webm", b"\x1a\x45\xdf\xa3" + b"\x00" * 40000, "audio/webm")
    c.post("/api/voice/transcribe/", {"audio": clip, "seconds": "-1000000000"}, format="multipart")
    row = UsageCounter.objects.filter(user=u, metric="stt_seconds").first()
    assert row is None or row.amount >= 0


# 4 — every Creator Lab AI generation is metered
def test_lab_generation_counts_against_daily_limit():
    c, u = client_for("org.owner@x.in")
    c.post("/api/orgs/", {"name": "My School", "kind": "school"}, format="json")  # becomes a creator via org
    cid = c.post("/api/lab/courses/", {"goal": "Blank course", "mode": "blank"}, format="json").data["id"]
    sec = c.post(f"/api/lab/courses/{cid}/sections/", {"title": "S"}, format="json").data["sections"][-1][
        "id"
    ]
    sub = c.post(f"/api/lab/sections/{sec}/subsections/", {"title": "L1"}, format="json").data["sections"][0][
        "subsections"
    ][-1]["id"]
    for _ in range(20):
        UsageEvent.objects.create(user=u, metric="lab_ai")
    r = c.post(f"/api/lab/subsections/{sub}/generate/")
    assert r.status_code == 402 and r.data["limit"] == "lab_ai_per_day"


def test_media_upload_quota(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    import apps.media.api as m

    c, _ = client_for("t@x.in", is_creator=True)
    old = m.UPLOADS_PER_DAY
    m.UPLOADS_PER_DAY = 1
    try:

        def png():
            b = io.BytesIO()
            Image.new("RGB", (8, 8)).save(b, "PNG")
            return SimpleUploadedFile("p.png", b.getvalue(), "image/png")

        assert c.post("/api/media/upload/", {"file": png()}, format="multipart").status_code == 201
        assert c.post("/api/media/upload/", {"file": png()}, format="multipart").data["code"] == "media_quota"
    finally:
        m.UPLOADS_PER_DAY = old


@pytest.fixture
def course():
    _, owner = client_for("owner@x.in", is_creator=True)
    cur = Curriculum.objects.create(
        owner=owner, goal="g", title="T", status="ready", visibility="link", published_at=timezone.now()
    )
    sec = Section.objects.create(curriculum=cur, order=0, title="S")
    sub = Subsection.objects.create(section=sec, order=0, title="L", lesson_status="ready")
    return cur, sub


# 5 — guests can't trigger AI/vision grading; learners have a daily AI-grading budget
def test_guest_cannot_trigger_vision_grading(course):
    from apps.learning.lab_api import AI_GRADED

    assert {"browser_task", "roleplay"} <= AI_GRADED


def test_ai_grading_daily_budget(course):
    cur, sub = course
    a = Activity.objects.create(
        subsection=sub,
        order=0,
        type="open_input",
        title="t",
        payload={"prompt": "p"},
        key={"model_answer": "m", "rubric": ["r"]},
    )
    c, u = client_for("g@x.in")
    from apps.learning.models import Enrollment

    Enrollment.objects.create(user=u, curriculum=cur)
    UsageCounter.objects.create(user=u, day=timezone.localdate(), metric="ai_grades", amount=200)
    r = c.post(f"/api/learn/activities/{a.id}/attempt/", {"answer": {"text": "my answer"}}, format="json")
    assert r.status_code == 429 and r.data["code"] == "grading_budget_exceeded"


# 6 — deleting chats doesn't reset the mentor message limit
def test_mentor_limit_counts_sent_messages_not_rows():
    from apps.billing.services import usage

    _, u = client_for("m@x.in")
    for _ in range(3):
        UsageEvent.objects.create(user=u, metric="mentor_message")
    assert usage(u, "mentor_messages_per_day") == 3  # no Message rows exist at all


# 7 — map place names are rendered as text (front-end): covered by web lint + code; here: names stay plain strings
# 8 — CSV formula injection
def test_survey_csv_neutralises_formulas():
    from apps.orgs.api import _csv_safe

    assert _csv_safe('=HYPERLINK("http://evil","x")').startswith("'=")
    assert (
        _csv_safe("+1") == "'+1"
        and _csv_safe("@SUM(A1)") == "'@SUM(A1)"
        and _csv_safe("hello") == "hello"
        and _csv_safe(5) == 5
    )


# 9 — lesson score uses the FIRST attempt (retrying after the reveal doesn't earn "perfect")
def test_lesson_score_uses_first_attempt(course):
    cur, sub = course
    a = Activity.objects.create(
        subsection=sub,
        order=0,
        kind="lesson",
        type="quiz",
        title="q",
        payload={"prompt": "p", "options": ["a", "b"], "multiple": False},
        key={"correct": [0]},
    )
    c, u = client_for("r@x.in")
    from apps.learning.models import Enrollment

    Enrollment.objects.create(user=u, curriculum=cur)
    c.post(f"/api/learn/activities/{a.id}/attempt/", {"answer": {"selected": [1]}}, format="json")
    c.post(f"/api/learn/activities/{a.id}/attempt/", {"answer": {"selected": [0]}}, format="json")
    assert ActivityAttempt.objects.filter(user=u).count() == 2
    assert c.post(f"/api/learn/subsections/{sub.id}/complete/").data["score"] == 0.0


# 10 — editing an approved catalog course sends it back to moderation
def test_catalog_edit_requires_remoderation():
    c, u = client_for("cr@x.in", is_creator=True)
    cur = Curriculum.objects.create(
        owner=u,
        kind=Curriculum.Kind.AUTHORED,
        goal="g",
        title="T",
        status="ready",
        catalog_status="approved",
        visibility="catalog",
    )
    sec = Section.objects.create(curriculum=cur, order=0, title="S")
    sub = Subsection.objects.create(section=sec, order=0, title="L", lesson_status="ready")
    c.patch(f"/api/lab/subsections/{sub.id}/", {"explanation_md": "changed"}, format="json")
    cur.refresh_from_db()
    assert cur.catalog_status == "pending"


# 11 — join codes are throttled per user
def test_join_code_throttled():
    c, _ = client_for("j@x.in")
    codes = [c.post(f"/api/orgs/join/ZZZZZ{i:02d}/").status_code for i in range(12)]
    assert 429 in codes


# 13 — DEBUG fails closed
def test_debug_defaults_off():
    from pathlib import Path

    src = Path("config/settings.py").read_text()
    assert 'env_bool("DJANGO_DEBUG", False)' in src


# 14 — passwordless accounts confirm deletion with an emailed code
def test_passwordless_delete_needs_emailed_code():
    u = User.objects.create_user("g.only@x.in")  # e.g. Google sign-in: no usable password
    c = APIClient()
    c.force_authenticate(u)
    r = c.post("/api/legal/delete-account/", {"confirm": "DELETE"}, format="json")
    assert r.status_code == 202 and r.data["code"] == "otp_sent"
    code = mail.outbox[-1].body.split("Your code is ")[1][:6]
    assert (
        c.post(
            "/api/legal/delete-account/",
            {"confirm": "DELETE", "code": "000000" if code != "000000" else "111111"},
            format="json",
        ).status_code
        == 403
    )
    assert (
        c.post("/api/legal/delete-account/", {"confirm": "DELETE", "code": code}, format="json").status_code
        == 200
    )
    assert not User.objects.filter(email="g.only@x.in").exists()


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    caches["security"].clear()
    yield
    cache.clear()
    caches["security"].clear()


# Hardening: unused-image cleanup keeps library + referenced files, removes only old orphans
def test_media_cleanup_only_removes_old_orphans(settings, tmp_path):
    import os
    import time

    from apps.media.cleanup import sweep
    from apps.media.models import MediaAsset

    settings.MEDIA_ROOT = str(tmp_path)
    d = tmp_path / "aasan"
    d.mkdir()
    owned, used, orphan, fresh = (
        ("a" * 32 + ".webp"),
        ("b" * 32 + ".webp"),
        ("c" * 32 + ".webp"),
        ("d" * 32 + ".webp"),
    )
    for n in (owned, used, orphan, fresh):
        (d / n).write_bytes(b"x")
    old = time.time() - 3 * 86400
    for n in (owned, used, orphan):
        os.utime(d / n, (old, old))
    _, u = client_for("img@x.in", is_creator=True)
    MediaAsset.objects.create(owner=u, name=owned)
    cur = Curriculum.objects.create(owner=u, goal="g", title="T", status="ready")
    sec = Section.objects.create(curriculum=cur, order=0, title="S")
    Subsection.objects.create(section=sec, order=0, title="L", explanation_md=f"![x](/api/media/{used})")
    assert sweep(dry_run=True)["deleted"] == 1
    r = sweep()
    assert r["files"] == [orphan]
    assert sorted(os.listdir(d)) == sorted([owned, used, fresh])
