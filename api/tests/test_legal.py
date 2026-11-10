import json
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.models import Entitlement, Order, Plan
from apps.billing.reminders import send_due
from apps.game.models import Notification
from apps.learning.models import Curriculum, Enrollment
from apps.legal.models import TERMS_VERSION
from apps.mentor.models import Conversation, Message
from apps.orgs.models import Membership, Organization

pytestmark = pytest.mark.django_db
PW = "Legal#2026passwd"


def client_for(email, **kw):
    u = User.objects.create_user(email, PW, **kw)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def test_site_info_public_and_admin_editable():
    assert APIClient().get("/api/legal/site/").data["terms_version"] == TERMS_VERSION
    a, _ = client_for("boss@x.in", is_staff=True)
    r = a.patch(
        "/api/admin/site/",
        {"legal_name": "Aasan Learning Pvt Ltd", "grievance_email": "grievance@aasan.in", "refund_days": 7},
        format="json",
    )
    assert r.status_code == 200 and r.data["legal_name"] == "Aasan Learning Pvt Ltd"
    c, _ = client_for("l@x.in")
    assert c.patch("/api/admin/site/", {"legal_name": "x"}, format="json").status_code == 403


def test_consent_required_until_accepted_and_guardian_for_minor():
    c, u = client_for("kid@x.in")
    assert c.get("/api/users/me/").data["consent"]["required"] is True
    assert (
        c.post("/api/legal/consent/", {"accept": True, "age_band": "minor"}, format="json").status_code == 400
    )
    r = c.post(
        "/api/legal/consent/",
        {"accept": True, "age_band": "minor", "guardian_email": "Amma@Home.in"},
        format="json",
    )
    assert r.status_code == 200
    u.refresh_from_db()
    assert u.terms_version == TERMS_VERSION and u.guardian_email == "amma@home.in"
    assert any("amma@home.in" in m.to for m in mail.outbox)
    assert c.get("/api/users/me/").data["consent"]["required"] is False


def test_signup_can_record_consent():
    r = APIClient().post(
        "/api/users/register/",
        {"email": "new@x.in", "password": PW, "accept_terms": True, "age_band": "adult"},
        format="json",
    )
    assert r.status_code == 201
    assert User.objects.get(email="new@x.in").terms_version == TERMS_VERSION


def test_export_contains_my_data_not_secrets_or_others():
    c, u = client_for("me@x.in")
    from rest_framework_simplejwt.tokens import RefreshToken

    RefreshToken.for_user(u)  # creates an OutstandingToken row
    other, ou = client_for("other@x.in")
    conv = Conversation.objects.create(user=u, title="mine")
    Message.objects.create(conversation=conv, role="user", content="what is a prompt?")
    Message.objects.create(
        conversation=Conversation.objects.create(user=ou, title="theirs"), role="user", content="SECRET-OTHER"
    )
    r = c.get("/api/legal/export/")
    assert r.status_code == 200 and "attachment" in r["Content-Disposition"]
    body = r.content.decode()
    data = json.loads(body)
    assert "what is a prompt?" in body and "SECRET-OTHER" not in body
    assert "password" not in json.dumps(data["accounts.User"])
    assert "mentor.Conversation" in data
    assert not any(k.startswith("token_blacklist") or k == "accounts.OneTimeToken" for k in data)


def test_delete_requires_confirm_and_password():
    c, u = client_for("me@x.in")
    assert (
        c.post("/api/legal/delete-account/", {"password": PW}, format="json").data["code"]
        == "confirm_required"
    )
    assert (
        c.post(
            "/api/legal/delete-account/", {"confirm": "DELETE", "password": "nope"}, format="json"
        ).status_code
        == 403
    )
    assert (
        c.post("/api/legal/delete-account/", {"confirm": "delete", "password": PW}, format="json").status_code
        == 200
    )
    assert not User.objects.filter(email="me@x.in").exists()


def test_delete_keeps_shared_courses_and_payments_but_not_private_data():
    c, u = client_for("teacher@x.in")
    _, learner = client_for("student@x.in")
    shared = Curriculum.objects.create(owner=u, goal="shared course", status="ready")
    private = Curriculum.objects.create(owner=u, goal="private course", status="ready")
    Enrollment.objects.create(user=learner, curriculum=shared)
    plan = Plan.objects.get(code="plus_month")
    order = Order.objects.create(user=u, plan=plan, amount_paise=14900, rp_order_id="order_x", status="paid")
    assert (
        c.post("/api/legal/delete-account/", {"confirm": "DELETE", "password": PW}, format="json").status_code
        == 200
    )
    shared.refresh_from_db()
    assert shared.owner.email == "archive@aasan.invalid"
    assert Enrollment.objects.filter(user=learner, curriculum=shared).exists()
    assert not Curriculum.objects.filter(pk=private.pk).exists()
    order.refresh_from_db()
    assert order.user is None and order.amount_paise == 14900


def test_sole_owner_must_hand_over_org_first():
    c, u = client_for("owner@x.in")
    _, m = client_for("member@x.in")
    org = Organization.objects.create(name="S", slug="s", created_by=u)
    Membership.objects.create(org=org, user=u, role="owner")
    Membership.objects.create(org=org, user=m, role="learner")
    r = c.post("/api/legal/delete-account/", {"confirm": "DELETE", "password": PW}, format="json")
    assert r.status_code == 409 and r.data["orgs"][0]["slug"] == "s"


def test_plan_reminders_once_and_only_for_latest_window():
    _, u = client_for("p@x.in")
    plan = Plan.objects.get(code="plus_month")
    now = timezone.now()
    Entitlement.objects.create(
        user=u, plan=plan, starts_at=now - timedelta(days=28), ends_at=now + timedelta(days=2)
    )
    assert send_due(now) == {"soon": 1, "ended": 0}
    assert send_due(now) == {"soon": 0, "ended": 0}
    assert Notification.objects.filter(user=u, kind="plan").count() == 1
    # renewed early: a later window exists, so no "ended" nag when the first one lapses
    Entitlement.objects.create(
        user=u, plan=plan, starts_at=now + timedelta(days=2), ends_at=now + timedelta(days=32)
    )
    assert send_due(now + timedelta(days=3)) == {"soon": 0, "ended": 0}
    assert send_due(now + timedelta(days=33)) == {"soon": 0, "ended": 1}
