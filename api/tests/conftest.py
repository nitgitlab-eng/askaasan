import pytest
from django.core.cache import cache, caches
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def _offline_llm(settings, monkeypatch):
    settings.LLM_FORCE_PROVIDER = "fake"
    settings.LEARNING_JOBS_INLINE = True
    settings.PASSWORD_BREACH_CHECK = (
        False  # never call the breach API from tests (test_password_breach.py mocks it)
    )
    settings.HEALTH_CACHE_SECONDS = 0
    settings.ADMIN_REAUTH_MINUTES = (
        0  # most tests force_authenticate (no token); test_admin_reauth.py turns it on
    )
    cache.clear()  # reset auth throttle counters between tests
    caches["security"].clear()  # and lockouts, OTP tries and mail caps (apps/accounts/counters.py)
    # Never let a developer's real gateway keys (loaded from api/.env) reach the suite: tests that need payments set
    # their own test doubles, and nothing may call Razorpay for real.
    for name in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _staff_get_a_role(monkeypatch):
    """`create_user(..., is_staff=True)` stands for staff granted the normal way (make_admin or the admin console),
    which also saves a superadmin role row. Staff without a row have no admin access (apps/accounts/staff.py)."""
    from apps.accounts.models import StaffRole, UserManager

    create_user = UserManager.create_user

    def with_role(self, email, password=None, **extra):
        user = create_user(self, email, password, **extra)
        if user.is_staff and not user.is_superuser:
            StaffRole.objects.get_or_create(user=user, defaults={"roles": ["superadmin"]})
        return user

    monkeypatch.setattr(UserManager, "create_user", with_role)


@pytest.fixture
def media_features(db):
    """Lesson podcast, explainer and Listen switched on (they are off by default)."""
    from apps.providers.models import PlatformSettings

    PlatformSettings.objects.update_or_create(
        pk=1, defaults={"podcast_enabled": True, "explainer_enabled": True, "listen_enabled": True}
    )


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def auth(client, db):
    res = client.post(
        "/api/users/register/", {"email": "kavya@example.com", "password": "Tamil#Learn2026"}, format="json"
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")
    return client, res.data


# ── Razorpay test doubles (billing + schools tests) ──
SECRET, HOOK = "test_secret_abc123", "whsec_xyz789"


@pytest.fixture
def keys():
    from apps.billing.models import PaymentConfig

    PaymentConfig.objects.create(
        pk=1,
        key_id="rzp_test_ABC123",
        encrypted_secret=_crypto().encrypt(SECRET),
        encrypted_webhook_secret=_crypto().encrypt(HOOK),
    )


@pytest.fixture
def gateway(monkeypatch):
    calls = {"orders": [], "captured": []}
    state = {"status": "captured", "amount": None}

    def create_order(keys, amount, currency, receipt, notes):
        assert keys.key_id == "rzp_test_ABC123" and keys.secret == SECRET
        oid = f"order_{len(calls['orders']) + 1}"
        calls["orders"].append({"id": oid, "amount": amount, "notes": notes})
        state["amount"] = amount
        return {"id": oid, "amount": amount}

    def fetch_payment(keys, pid):
        return {
            "id": pid,
            "order_id": calls["orders"][-1]["id"],
            "amount": state["amount"],
            "status": state["status"],
        }

    monkeypatch.setattr(_rp(), "create_order", create_order)
    monkeypatch.setattr(_rp(), "fetch_payment", fetch_payment)
    monkeypatch.setattr(_rp(), "capture_payment", lambda k, pid, a, c: calls["captured"].append(pid) or {})
    return calls, state


@pytest.fixture
def sub_gateway(monkeypatch, gateway):
    """Razorpay Subscriptions double (on top of `gateway`): create / fetch / cancel / resume + the payment it returns."""
    calls = {"created": [], "cancelled": [], "resumed": []}
    state = {
        "status": "active",
        "payment": {
            "status": "captured",
            "amount": 14900,
            "method": "card",
            "card": {"network": "Visa", "last4": "4242"},
        },
    }

    def create_subscription(keys, plan_id, total_count, notes):
        assert keys.key_id == "rzp_test_ABC123" and keys.secret == SECRET
        sid = f"sub_{len(calls['created']) + 1}"
        calls["created"].append({"id": sid, "plan_id": plan_id, "total_count": total_count, "notes": notes})
        return {"id": sid, "status": "created"}

    def fetch_subscription(keys, sid):
        return {
            "id": sid,
            "status": state["status"],
            "current_start": 1_800_000_000,
            "current_end": 1_802_592_000,
            "charge_at": 1_802_592_000,
            "paid_count": 1,
        }

    def cancel_subscription(keys, sid, at_cycle_end):
        calls["cancelled"].append((sid, at_cycle_end))
        return {"id": sid, "status": "active" if at_cycle_end else "cancelled"}

    def resume_subscription(keys, sid):
        calls["resumed"].append(sid)
        return {"id": sid, "status": "active"}

    def fetch_payment(keys, pid):
        return {"id": pid, "order_id": f"order_for_{pid}", **state["payment"]}

    for name, fn in (
        ("create_subscription", create_subscription),
        ("fetch_subscription", fetch_subscription),
        ("cancel_subscription", cancel_subscription),
        ("resume_subscription", resume_subscription),
        ("fetch_payment", fetch_payment),
    ):
        monkeypatch.setattr(_rp(), name, fn)
    return calls, state


def _crypto():
    from apps.providers import crypto

    return crypto


def _rp():
    from apps.billing import razorpay

    return razorpay
