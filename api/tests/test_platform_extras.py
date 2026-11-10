"""Notifications/unsubscribe, study reminders, calendar feed, AI usage ledger, admin overview/system check/prices,
SMTP config, hybrid note search, FSRS cards, and the showcase course."""

from datetime import timedelta

import pytest
from django.core import mail, signing
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.notify import send_optional, unsubscribe_url
from apps.game.models import Notification
from apps.providers.models import LLMUsage

pytestmark = pytest.mark.django_db
PW = "Extras#2026pass"


def client_for(email, **kw):
    u = User.objects.create_user(email, PW, **kw)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


# ── notifications ─────────────────────────────────────────────────────


def test_optional_mail_respects_prefs_and_unsubscribes_in_one_click():
    c, u = client_for("a@x.in")
    assert send_optional(u, "email_plan", "Plan", "ends soon")
    assert "unsubscribe?t=" in mail.outbox[-1].body
    token = unsubscribe_url(u, "email_plan").split("t=")[1]
    assert APIClient().post("/api/users/unsubscribe/", {"t": token}, format="json").data == {
        "ok": True,
        "category": "email_plan",
    }
    assert not send_optional(User.objects.get(pk=u.pk), "email_plan", "Plan", "ends soon")
    assert APIClient().post("/api/users/unsubscribe/", {"t": "forged"}, format="json").status_code == 400
    forged = signing.dumps({"u": u.id, "c": "email_plan"}, salt="wrong-salt")
    assert APIClient().post("/api/users/unsubscribe/", {"t": forged}, format="json").status_code == 400
    c.force_authenticate(User.objects.get(pk=u.pk))  # the test client holds a cached user object
    assert c.get("/api/users/me/").data["preferences"]["notifications"]["email_plan"] is False


def test_kili_nudges_can_be_switched_off():
    from apps.game.services import nudges

    c, u = client_for("n@x.in")
    c.patch("/api/users/preferences/", {"notifications": {"kili_nudges": False}}, format="json")
    u.refresh_from_db()
    assert nudges(u) == []


def test_study_reminder_once_at_chosen_time_and_not_if_studied():
    from apps.accounts.study_reminders import send_due

    c, u = client_for("s@x.in")
    now = timezone.localtime().replace(hour=19, minute=5)
    c.patch(
        "/api/users/preferences/",
        {"learning": {"reminder_times": ["19:00"], "study_days": [now.weekday()]}},
        format="json",
    )
    assert send_due(now) == 1
    assert send_due(now) == 0  # once per day
    assert Notification.objects.filter(user=u, kind="study_reminder").count() == 1
    assert send_due(now.replace(hour=9)) == 0  # wrong time


# ── calendar feed ─────────────────────────────────────────────────────


def test_calendar_feed_private_revocable_and_escaped():
    from apps.learning.models import Curriculum
    from apps.orgs.models import Assignment, Membership, Organization

    c, u = client_for("cal@x.in")
    org = Organization.objects.create(name="S", slug="s")
    Membership.objects.create(org=org, user=u, role="learner")
    cur = Curriculum.objects.create(owner=u, goal="g", title="Evil\r\nATTENDEE:mailto:x@y.z", status="ready")
    Assignment.objects.create(org=org, curriculum=cur, due_at=timezone.now() + timedelta(days=2))
    url = c.get("/api/game/calendar-feed/").data["url"]
    path = url.split("://", 1)[1].split("/", 1)[1]
    r = APIClient().get("/" + path)
    body = r.content.decode()
    assert r.status_code == 200 and "BEGIN:VCALENDAR" in body and "Due: Evil" in body
    assert "\r\nATTENDEE" not in body  # user text can't inject calendar fields
    c.post("/api/game/calendar-feed/")  # rotate
    assert APIClient().get("/" + path).status_code == 404
    assert APIClient().get("/api/game/calendar/garbage.ics").status_code == 404


# ── AI usage ledger + admin dashboard ─────────────────────────────────


def test_usage_is_recorded_per_user_and_shown_to_admins_only(auth):
    client, _ = auth
    client.post("/api/learn/curriculums/", {"goal": "Learn prompting", "level": "beginner"}, format="json")
    assert LLMUsage.objects.filter(task="author").exists()
    learner, _ = client_for("l@x.in")
    assert learner.get("/api/admin/overview/").status_code == 403
    admin, _ = client_for("boss@x.in", is_staff=True)
    d = admin.get("/api/admin/overview/?days=30").data
    assert d["ai"]["calls"] >= 1 and d["users"]["total"] >= 2 and len(d["users"]["series"]) == 30
    prices = admin.get("/api/admin/model-prices/").data
    assert any(p["model"] == "claude-sonnet-5-5" for p in prices)
    admin.put(
        "/api/admin/model-prices/",
        {"provider": "anthropic", "model": "claude-sonnet-5-5", "input_per_m": "250", "output_per_m": "1250"},
        format="json",
    )
    assert any(p["input_per_m"] == 250 for p in admin.get("/api/admin/model-prices/").data)


def test_system_check_lists_everything():
    admin, _ = client_for("boss@x.in", is_staff=True)
    d = admin.get("/api/admin/system-check/").data
    keys = {i["key"] for i in d["items"]}
    assert {
        "tutor",
        "vision",
        "image",
        "razorpay",
        "smtp",
        "site",
        "jobs",
        "media",
        "db",
        "debug",
        "secret",
        "demo",
        "admins",
        "monitoring",
    } <= keys
    assert sum(d["summary"].values()) == len(d["items"])


def test_system_check_flags_test_accounts_and_counts_roles():
    from apps.accounts.models import StaffRole

    admin, _ = client_for("boss@x.in", is_staff=True)
    _, fin = client_for("fin@x.in", is_staff=True)
    StaffRole.objects.update_or_create(user=fin, defaults={"roles": ["finance"]})
    User.objects.create_user("superadmin@validate.aasan.local", "Val#Pass2026x")
    items = {i["key"]: i for i in admin.get("/api/admin/system-check/").data["items"]}
    assert items["demo"]["status"] in ("warn", "info") and "validate.aasan.local" in items["demo"]["detail"]
    assert items["admins"]["status"] == "ok" and items["admins"]["detail"].startswith(
        "2 staff accounts, 1 superadmin."
    )


# ── SMTP from the admin console ───────────────────────────────────────


def test_smtp_config_masks_password_and_backend_uses_it(settings):
    from apps.legal.mail import ConfigurableEmailBackend
    from apps.legal.models import MailConfig

    admin, _ = client_for("boss@x.in", is_staff=True)
    r = admin.patch(
        "/api/admin/mail/",
        {
            "host": "smtp.example.in",
            "port": 587,
            "security": "tls",
            "username": "u",
            "password": "s3cret-pass",
            "from_email": "no-reply@example.in",
        },
        format="json",
    )
    assert r.data["ready"] and r.data["password"] == "••••" and "s3cret" not in str(r.data)
    assert MailConfig.objects.get(pk=1).password() == "s3cret-pass"
    sent = []

    class FakeConn:
        def send_messages(self, msgs):
            sent.extend(msgs)
            return len(msgs)

    import apps.legal.mail as m

    orig = m._smtp_connection
    m._smtp_connection = lambda cfg, fail_silently=False: FakeConn()
    try:
        from django.core.mail import EmailMessage

        ConfigurableEmailBackend().send_messages([EmailMessage("hi", "body", None, ["x@y.in"])])
    finally:
        m._smtp_connection = orig
    assert sent and sent[0].from_email == "Aasan <no-reply@example.in>"
    learner, _ = client_for("l2@x.in")
    assert learner.get("/api/admin/mail/").status_code == 403


# ── hybrid note search ────────────────────────────────────────────────


def test_hybrid_search_ranks_semantic_and_keyword_matches():
    from apps.docs.embeddings import embed
    from apps.docs.models import Chunk, Document
    from apps.docs.search import top_chunks

    _, u = client_for("d@x.in")
    doc = Document.objects.create(owner=u, title="Notes", filename="n.txt", kind="txt")
    texts = [
        "Photosynthesis makes food in leaves using sunlight.",
        "Cricket scores and batting averages.",
        "Rivers of Tamil Nadu: Kaveri, Vaigai.",
    ]
    vecs = embed(texts)
    for i, t in enumerate(texts):
        Chunk.objects.create(document=doc, index=i, text=t, embedding=vecs[i])
    assert top_chunks(doc, "Kaveri river", k=1)[0].index == 2


# ── showcase ──────────────────────────────────────────────────────────


def test_showcase_has_every_activity_type(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    from apps.learning.models import Activity
    from apps.learning.showcase import build_showcase

    _, u = client_for("t@x.in", is_creator=True)
    cur = build_showcase(u)
    types = set(Activity.objects.filter(subsection__section__curriculum=cur).values_list("type", flat=True))
    assert types == set(Activity.TYPES)
