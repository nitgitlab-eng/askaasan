"""Hardening pass (agent HDE): plan limits (H2 H48), voice input (H6), stale subscription webhooks (H15), guest links
(H47, S6), secrets encryption (H91 H92), AI budget weighting (H5), seat credit (S21), STT charging (S12).
Dummy users only; voice and LLM providers are the offline fakes."""

from datetime import timedelta

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.models import Entitlement, Order, OrgSubscription, Plan, Subscription
from apps.billing.services import extend_org, limit_of
from apps.orgs.models import Organization
from apps.providers.models import ProviderConfig, UsageCounter

pytestmark = pytest.mark.django_db
PW = "Harden#Billing2026"


def client_for(email, **kw):
    u = User.objects.create_user(email, PW, **kw)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def free_limits(limits):
    Plan.objects.update_or_create(code="free", defaults={"name": "Free", "price_paise": 0, "limits": limits})


@pytest.fixture
def tts(monkeypatch):
    import apps.providers.voice_api as v

    ProviderConfig.objects.create(
        capability="tts", provider="fake", model="x", limits={"tts_chars_per_day": 100000}
    )
    monkeypatch.setattr(v, "needs_key", lambda *a: False)
    return v


# ── H2: plan limit on text-to-speech ─────────────────────────────────


def test_tts_chars_plan_limit_returns_402(tts):
    free_limits({"tts_chars_per_day": 100})
    c, u = client_for("speak@x.in")
    r = c.post("/api/voice/speak/", {"text": "a" * 150}, format="json")
    assert r.status_code == 402 and r.data["code"] == "plan_limit" and r.data["limit"] == "tts_chars_per_day"
    assert not UsageCounter.objects.filter(user=u, metric="tts_chars").exists()
    assert c.post("/api/voice/speak/", {"text": "a" * 60}, format="json").status_code == 200
    assert c.post("/api/voice/speak/", {"text": "a" * 60}, format="json").status_code == 402  # 60 + 60 > 100
    staff, _ = client_for("ops@x.in", is_staff=True)
    assert staff.post("/api/voice/speak/", {"text": "a" * 150}, format="json").status_code == 200


# ── H6: non-string text is a 400, not a 500 ──────────────────────────


@pytest.mark.parametrize("text", [123, ["a"], {"x": 1}, None])
def test_speak_rejects_non_string_text(tts, text):
    c, _ = client_for("speak@x.in")
    r = c.post("/api/voice/speak/", {"text": text}, format="json")
    assert r.status_code == 400 and r.data["code"] == "empty"


# ── H48: a key dropped from the free plan falls back to the default ──


def test_missing_free_plan_key_falls_back_but_explicit_null_is_unlimited():
    _, u = client_for("free@x.in")
    free_limits({})
    assert limit_of(u, "mentor_messages_per_day") == 30
    free_limits({"mentor_messages_per_day": None})
    assert limit_of(u, "mentor_messages_per_day") is None


# ── H15: out-of-order subscription webhooks ──────────────────────────


def _sub(paid_count=2):
    _, u = client_for("sub@x.in")
    plan = Plan.objects.create(code="pro_h", name="Pro", price_paise=19900, period_days=30, limits={})
    return Subscription.objects.create(
        user=u,
        plan=plan,
        rp_subscription_id="sub_H15",
        status="active",
        amount_paise=19900,
        paid_count=paid_count,
    )


def test_stale_pending_webhook_is_ignored():
    from apps.billing.subscriptions import handle_event

    sub = _sub(paid_count=2)
    ent = {"id": "sub_H15", "status": "pending", "paid_count": 1}
    assert handle_event("subscription.pending", {"subscription": {"entity": ent}}) == "stale"
    sub.refresh_from_db()
    assert sub.status == "active" and sub.grace_until is None and sub.paid_count == 2
    assert not Entitlement.objects.filter(user=sub.user, source="grace").exists()


def test_stale_event_does_not_roll_status_back_but_current_one_does():
    from apps.billing.subscriptions import handle_event

    sub = _sub(paid_count=3)
    handle_event(
        "subscription.cancelled",
        {"subscription": {"entity": {"id": "sub_H15", "status": "cancelled", "paid_count": 1}}},
    )
    sub.refresh_from_db()
    assert sub.status == "active"
    handle_event(
        "subscription.pending",
        {"subscription": {"entity": {"id": "sub_H15", "status": "pending", "paid_count": 3}}},
    )
    sub.refresh_from_db()
    assert sub.status == "pending" and sub.grace_until is not None


# ── H47: guest resume / email-link honour the link state ─────────────


def _course_link(owner_client, owner, **extra):
    from apps.learning.models import Curriculum, Section, Subsection

    cur = Curriculum.objects.create(
        owner=owner, kind="authored", goal="C", title="C", status="ready", published_at=timezone.now()
    )
    s = Section.objects.create(curriculum=cur, order=1, title="S")
    Subsection.objects.create(section=s, order=1, title="L1", lesson_status="ready")
    r = owner_client.post(
        "/api/guests/links/",
        {"label": "Open day", "target_kind": "course", "course_id": cur.id, "collect_email": True, **extra},
        format="json",
    )
    assert r.status_code == 201, r.data
    return r.data["slug"]


@pytest.mark.parametrize("state", ["inactive", "expired"])
def test_resume_and_email_link_refused_on_unusable_link(state):
    from django.core import signing

    from apps.guests.models import GuestLink, GuestVisitor
    from apps.guests.services import MAGIC_SALT

    oc, owner = client_for("author@x.in", is_creator=True)
    slug = _course_link(oc, owner)
    g = APIClient()
    r = g.post(f"/api/guests/public/{slug}/start/", {"name": "Priya", "email": "p@x.in"}, format="json")
    assert r.status_code == 201
    g.credentials(HTTP_X_GUEST_TOKEN=r.data["token"])
    link = GuestLink.objects.get(slug=slug)

    def magic():
        v = GuestVisitor.objects.get(link=link)
        return signing.dumps({"l": link.id, "v": v.id, "n": v.magic_version}, salt=MAGIC_SALT)

    ok = APIClient().post(f"/api/guests/public/{slug}/resume/", {"magic": magic()}, format="json")
    assert ok.status_code == 200  # control: a usable link resumes
    g.credentials(HTTP_X_GUEST_TOKEN=ok.data["token"])
    if state == "inactive":
        link.active = False
    else:
        link.expires_at = timezone.now() - timedelta(minutes=1)
    link.save()
    res = APIClient().post(f"/api/guests/public/{slug}/resume/", {"magic": magic()}, format="json")
    assert res.status_code == 410 and res.data["code"] == f"link_{state}" and "token" not in res.data
    em = g.post(f"/api/guests/public/{slug}/email-link/", {}, format="json")
    assert em.status_code == 410 and em.data["code"] == f"link_{state}"


# ── S6: one free owner can't take most of the free guest-AI pool ─────


def test_free_owner_capped_to_small_share_of_pool(settings):
    from apps.guests.models import GuestAIUsage, GuestLink
    from apps.guests.services import charge_ai

    settings.GUEST_AI_GLOBAL_DAY, settings.GUEST_AI_PER_OWNER_DAY = 1000, 400
    settings.GUEST_AI_PER_LINK_DAY, settings.GUEST_AI_PER_IP_DAY = 1000, 1000
    settings.GUEST_AI_FREE_OWNER_SHARE = 2  # 20 units of 1000
    _, owner = client_for("free.owner@x.in", is_creator=True, email_verified=True)
    link = GuestLink(id=10**6, owner=owner)
    req = RequestFactory().post("/", REMOTE_ADDR="203.0.113.7")
    assert sum(charge_ai(link, req) for _ in range(30)) == 20
    assert GuestAIUsage.objects.get(key=f"owner:{owner.id}").units == 20
    _, staff = client_for("paid.owner@x.in", is_creator=True, is_staff=True)  # paid tier: only the 400 cap
    assert sum(charge_ai(GuestLink(id=10**6 + 1, owner=staff), req) for _ in range(30)) == 30


# ── H91 / H92: stored-secret encryption ──────────────────────────────


def test_encrypt_requires_secrets_key_even_in_debug(settings):
    from apps.providers import crypto

    settings.AASAN_SECRETS_KEY, settings.DEBUG = "", True
    settings.SECRET_KEY = "dev-insecure-change-me-0123456789abcdef0123456789"
    with pytest.raises(ImproperlyConfigured):
        crypto.encrypt("x")
    settings.DEBUG = False
    with pytest.raises(ImproperlyConfigured):
        crypto.encrypt("x")


def test_dev_rows_made_with_secret_key_still_decrypt_in_debug(settings):
    from apps.providers import crypto

    settings.DEBUG, settings.SECRET_KEY = True, "dev-only-secret-" + "x" * 40
    old = crypto._key(settings.SECRET_KEY).encrypt(b"sk-old").decode()
    settings.AASAN_SECRETS_KEY = "A" * 50
    assert crypto.decrypt(old) == "sk-old"
    settings.DEBUG = False  # production never accepts SECRET_KEY-encrypted rows
    with pytest.raises(ImproperlyConfigured):
        crypto.decrypt(old)


def test_key_rotation_with_old_keys(settings):
    from apps.providers import crypto

    settings.DEBUG, settings.AASAN_SECRETS_KEY_OLD = False, ""
    settings.AASAN_SECRETS_KEY = "key-A-" + "a" * 50
    token = crypto.encrypt("sk-live-123")
    settings.AASAN_SECRETS_KEY = "key-B-" + "b" * 50
    with pytest.raises(ImproperlyConfigured):
        crypto.decrypt(token)
    settings.AASAN_SECRETS_KEY_OLD = "unrelated, key-A-" + "a" * 50
    assert crypto.decrypt(token) == "sk-live-123"
    rotated = crypto.rotate(token)
    settings.AASAN_SECRETS_KEY_OLD = ""
    assert crypto.decrypt(rotated) == "sk-live-123"  # now readable with key B alone


# ── H5: AI budget weighted by max_tokens ─────────────────────────────


def test_ai_charge_weighted_by_max_tokens():
    from apps.providers.services import BudgetExceeded, ai_units, charge

    assert [ai_units(n) for n in (None, 0, 1500, 2000, 2001, 5000)] == [1, 1, 1, 1, 2, 3]
    _, u = client_for("ai@x.in")
    charge(u, "ai_grades", 1, 10)  # old signature: one unit
    charge(u, "ai_grades", 1, 10, max_tokens=5000)
    assert UsageCounter.objects.get(user=u, metric="ai_grades").amount == 4
    charge(u, "ai_grades", 1, 10, max_tokens=8000)  # 4 more units: 8 <= 10
    with pytest.raises(BudgetExceeded):
        charge(u, "ai_grades", 1, 10, max_tokens=8000)  # 12 > 10
    charge(u, "ai_grades", -1, 0, max_tokens=8000)  # refund with the same arguments
    assert UsageCounter.objects.get(user=u, metric="ai_grades").amount == 4  # the 8000 call refunded


# ── S21: replaced seat subscriptions are credited at what was paid ───


def _seat_order(org, plan, seats, amount, list_paise):
    _, buyer = client_for(f"buyer{amount}@x.in")
    return Order.objects.create(
        user=buyer,
        org=org,
        plan=plan,
        seats=seats,
        amount_paise=amount,
        list_paise=list_paise,
        rp_order_id=f"order_s21_{amount}",
        status="paid",
    )


@pytest.mark.parametrize("paid,expected_extra_days", [(0, 0), (500000, 30), (1000000, 60)])
def test_seat_switch_credit_follows_amount_paid(paid, expected_extra_days):
    org = Organization.objects.create(name="Acme", slug="acme-s21", kind="school")
    p = Plan.objects.create(code="seat_s21", name="Seat", price_paise=10000, period_days=30, limits={})
    old = extend_org(org, p, 100, order=_seat_order(org, p, 100, paid, 1000000))
    old.starts_at, old.ends_at = timezone.now() - timedelta(days=15), timezone.now() + timedelta(days=15)
    old.save()
    # half of 100 seats x 30 days is left: at full price that buys 60 extra days of 25 seats
    new = extend_org(org, p, 25)
    got = (new.ends_at - new.starts_at) - timedelta(days=30)
    assert abs(got - timedelta(days=expected_extra_days)) < timedelta(minutes=1)
    assert OrgSubscription.objects.filter(org=org, ends_at__gt=timezone.now()).count() == 1


def test_orderless_seat_grant_gives_no_credit():
    org = Organization.objects.create(name="Acme", slug="acme-s21b", kind="school")
    p = Plan.objects.create(code="seat_s21b", name="Seat", price_paise=10000, period_days=30, limits={})
    extend_org(org, p, 100)
    new = extend_org(org, p, 1)
    assert abs((new.ends_at - new.starts_at) - timedelta(days=30)) < timedelta(minutes=1)


# ── S12: STT charged at a conservative bitrate floor ─────────────────


def test_stt_charged_at_conservative_bitrate(monkeypatch, settings):
    import apps.providers.voice_api as v

    settings.STT_CHARGE_BYTES_PER_SEC = 750  # the strict floor an owner can opt into
    ProviderConfig.objects.create(
        capability="stt", provider="fake", model="x", limits={"stt_seconds_per_day": 100000}
    )
    monkeypatch.setattr(v, "needs_key", lambda *a: False)
    free_limits({"voice_minutes_per_day": 10})
    c, u = client_for("stt@x.in")
    clip = SimpleUploadedFile("a.webm", b"0" * 75_000, "audio/webm")  # 100 s at 6 kbps (~19 s at 32 kbps)
    assert (
        c.post("/api/voice/transcribe/", {"audio": clip, "seconds": "1"}, format="multipart").status_code
        == 200
    )
    assert UsageCounter.objects.get(user=u, metric="stt_seconds").amount == pytest.approx(100)
    big = SimpleUploadedFile("b.webm", b"0" * 450_000, "audio/webm")  # 600 s more: over the free 10 min
    r = c.post("/api/voice/transcribe/", {"audio": big}, format="multipart")
    assert r.status_code == 402 and r.data["code"] == "plan_limit"
    settings.STT_CHARGE_BYTES_PER_SEC = 4000  # configurable
    small = SimpleUploadedFile("c.webm", b"0" * 40_000, "audio/webm")
    assert c.post("/api/voice/transcribe/", {"audio": small}, format="multipart").status_code == 200
    assert UsageCounter.objects.get(user=u, metric="stt_seconds").amount == pytest.approx(110)


# ── H108 (handoff): unparsable client IPs share one bucket ───────────


def test_ip_bucket_collapses_unparsable_values():
    from apps.guests.services import ip_bucket

    assert ip_bucket("not-an-ip") == ip_bucket("also-bad") == "invalid"
    assert ip_bucket("") == ip_bucket(None) == "unknown"
    assert ip_bucket("203.0.113.7") == "203.0.113.7"
