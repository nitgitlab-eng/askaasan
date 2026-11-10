"""Family plan: invites (hashed, email-bound, no enumeration), token/code accept, capacity, one family per person, org
seat and price precedence, remove/leave, renewal + grace + refund propagation to members, owner-only reminders, admin
lists, roles and the plan editor. Razorpay is always the conftest fake (`keys`/`gateway`/`sub_gateway`)."""

import hashlib
import hmac
import json
import re
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import StaffRole, User
from apps.billing import family as fam
from apps.billing.models import (
    Entitlement,
    FamilyGroup,
    FamilyInvite,
    FamilyMember,
    Order,
    OrgSubscription,
    Plan,
    Subscription,
)
from apps.billing.services import active_entitlement, current_plan, limit_of, paid_until
from apps.game.models import Notification
from apps.orgs.models import Membership, Organization

pytestmark = pytest.mark.django_db
SECRET, HOOK = "test_secret_abc123", "whsec_xyz789"
PW = "Family#Plan2026"


def client_for(email, *, verified=True, roles=None):
    u = User.objects.create_user(email, PW)
    u.email_verified = verified
    if roles is not None:
        u.is_staff = True
    u.save()
    if roles is not None:
        StaffRole.objects.create(user=u, roles=roles)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def sign(msg, secret=SECRET):
    return hmac.new(
        secret.encode(), msg if isinstance(msg, bytes) else msg.encode(), hashlib.sha256
    ).hexdigest()


@pytest.fixture
def fplan():
    return Plan.objects.create(
        code="family_month",
        name="Family Plus",
        price_paise=29900,
        period_days=30,
        family=True,
        max_members=3,
        limits={"ai_courses_per_month": 40, "mentor_messages_per_day": None},
        sort=5,
    )


def pay(c, plan="family_month", pid="pay_1"):
    r = c.post("/api/billing/checkout/", {"plan": plan}, format="json")
    assert r.status_code == 201, r.data
    oid = r.data["order_id"]
    r = c.post(
        "/api/billing/verify/",
        {"razorpay_order_id": oid, "razorpay_payment_id": pid, "razorpay_signature": sign(f"{oid}|{pid}")},
        format="json",
    )
    assert r.status_code == 200, r.data
    return oid


@pytest.fixture
def owner(keys, gateway, fplan):
    c, u = client_for("amma@home.in")
    pay(c)
    return c, u


def invite(c, email):
    mail.outbox.clear()
    r = c.post("/api/billing/family/invite/", {"email": email}, format="json")
    assert r.status_code == 201, r.data
    body = mail.outbox[-1].body
    token = re.search(r"/family/([A-Za-z0-9_-]+)", body).group(1)
    code = re.search(r"code ([A-Z0-9]{6})", body).group(1)
    return r, token, code


def join(owner_client, email, **kw):
    _, token, _ = invite(owner_client, email)
    c, u = client_for(email, **kw)
    r = c.post("/api/billing/family/accept/", {"token": token}, format="json")
    return c, u, r


# ── invites ─────────────────────────────────────────────────────────


def test_invite_stores_only_hashes_and_never_reveals_accounts(owner):
    c, _ = owner
    User.objects.create_user("exists@home.in", PW)
    r1, token, code = invite(c, "exists@home.in")
    r2, _, _ = invite(c, "nobody@home.in")
    assert set(r1.data) == set(r2.data) and r1.data["emailed"] is True
    assert mail.outbox[-1].subject == "You're invited to share an Aasan family plan"
    inv = FamilyInvite.objects.get(email="exists@home.in")
    assert inv.token_hash == fam.hash_secret(token) and inv.code_hash == fam.hash_secret(code)
    assert token not in json.dumps(list(FamilyInvite.objects.values()), default=str)
    assert len(token) >= 32 and inv.expires_at - timezone.now() > timedelta(days=6)


def test_invite_returns_link_when_mail_is_not_ready(owner, monkeypatch):
    c, _ = owner
    monkeypatch.setattr("apps.legal.mail.mail_ready", lambda: False)
    r = c.post("/api/billing/family/invite/", {"email": "appa@home.in"}, format="json")
    assert r.status_code == 201 and r.data["emailed"] is False
    link = r.data["links"][0]
    assert link["email"] == "appa@home.in" and "/family/" in link["link"] and len(link["code"]) == 6


def test_invite_needs_a_family_plan_and_a_valid_email(keys, gateway, fplan):
    c, _ = client_for("solo@home.in")
    assert c.post("/api/billing/family/invite/", {"email": "a@b.in"}, format="json").data["code"] == (
        "no_family_plan"
    )
    pay(c)
    assert c.post("/api/billing/family/invite/", {"email": "nope"}, format="json").data["code"] == "bad_email"
    assert c.post("/api/billing/family/invite/", {"email": "solo@home.in"}, format="json").data["code"] == (
        "invite_self"
    )


def test_invite_daily_group_cap(owner, fplan):
    c, u = owner
    fplan.max_members = 20
    fplan.save()
    group = fam.ensure_group(u)
    for i in range(fam_cap := 20):
        FamilyInvite.objects.create(
            group=group,
            email=f"x{i}@home.in",
            token_hash=f"t{i}",
            code_hash="c",
            expires_at=timezone.now() - timedelta(seconds=1),  # expired: no seat held, still counts per day
        )
    assert fam_cap == 20
    r = c.post("/api/billing/family/invite/", {"email": "late@home.in"}, format="json")
    assert r.status_code == 429 and r.data["code"] == "invite_limit"


def test_resend_replaces_the_earlier_invite_and_owner_can_revoke(owner):
    c, _ = owner
    _, old_token, _ = invite(c, "appa@home.in")
    r, new_token, _ = invite(c, "appa@home.in")
    assert FamilyInvite.objects.filter(email="appa@home.in", revoked_at__isnull=True).count() == 1
    m, _ = client_for("appa@home.in")
    assert m.post("/api/billing/family/accept/", {"token": old_token}, format="json").status_code == 404
    assert c.delete(f"/api/billing/family/invites/{r.data['invite']['id']}/").status_code == 204
    assert m.post("/api/billing/family/accept/", {"token": new_token}, format="json").status_code == 404


# ── accepting ───────────────────────────────────────────────────────


def test_accept_by_token_mirrors_the_owners_plan(owner, fplan):
    c, u = owner
    m, mu, r = join(c, "appa@home.in")
    assert r.status_code == 200 and r.data["role"] == "member" and r.data["owner_name"] == "amma"
    assert "email" not in r.data["members"][0]  # members don't see each other's addresses
    ent = active_entitlement(mu)
    own = Entitlement.objects.get(user=u, plan=fplan)
    assert ent.source == "family" and ent.derived_from == own and ent.ends_at == own.ends_at
    assert current_plan(mu).code == "family_month" and limit_of(mu, "ai_courses_per_month") == 40
    assert paid_until(mu) == own.ends_at
    overview = m.get("/api/billing/").data
    assert overview["family"]["role"] == "member" and overview["plan"]["code"] == "family_month"
    owner_view = c.get("/api/billing/family/").data
    assert owner_view["role"] == "owner" and {x["email"] for x in owner_view["members"]} == {
        "amma@home.in",
        "appa@home.in",
    }


def test_accept_by_code_only_for_the_invited_email(owner):
    c, _ = owner
    _, _, code = invite(c, "appa@home.in")
    other, _ = client_for("thief@home.in")
    assert other.post("/api/billing/family/accept/", {"code": code}, format="json").status_code == 404
    m, mu = client_for("appa@home.in")
    r = m.post("/api/billing/family/accept/", {"code": code.lower()}, format="json")
    assert r.status_code == 200 and current_plan(mu).code == "family_month"


def test_preview_and_wrong_account(owner):
    c, _ = owner
    _, token, _ = invite(c, "appa@home.in")
    other, _ = client_for("thief@home.in")
    p = other.get(f"/api/billing/family/invites/{token}/").data
    assert p["owner_name"] == "amma" and p["plan"] == "Family Plus" and p["for_you"] is False
    assert p["email_hint"] == "ap…@home.in"
    r = other.post("/api/billing/family/accept/", {"token": token}, format="json")
    assert r.status_code == 403 and r.data["code"] == "invite_not_for_you"
    assert other.get("/api/billing/family/invites/nope/").status_code == 404


def test_unverified_email_must_verify_first(owner):
    c, _ = owner
    _, _, r = join(c, "appa@home.in", verified=False)
    assert r.status_code == 403 and r.data["code"] == "verify_email_first"


def test_accept_failures_are_limited(owner):
    other, _ = client_for("guess@home.in")
    for _ in range(10):
        assert other.post("/api/billing/family/accept/", {"code": "ABCDEF"}, format="json").status_code == 404
    assert other.post("/api/billing/family/accept/", {"code": "ABCDEF"}, format="json").status_code == 429


def test_expired_invite(owner):
    c, _ = owner
    _, token, _ = invite(c, "appa@home.in")
    FamilyInvite.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    m, _ = client_for("appa@home.in")
    r = m.post("/api/billing/family/accept/", {"token": token}, format="json")
    assert r.status_code == 410 and r.data["code"] == "invite_expired"


def test_capacity_counts_the_owner_and_pending_invites(owner):
    c, _ = owner  # max_members=3: owner + 2
    invite(c, "one@home.in")
    invite(c, "two@home.in")
    r = c.post("/api/billing/family/invite/", {"email": "three@home.in"}, format="json")
    assert r.status_code == 409 and r.data["code"] == "family_full"
    assert c.get("/api/billing/family/").data["seats_left"] == 0


def test_family_full_on_accept_when_plan_shrinks(owner, fplan):
    c, _ = owner
    _, token, _ = invite(c, "one@home.in")
    join(c, "two@home.in")
    fplan.max_members = 2
    fplan.save()
    m, _ = client_for("one@home.in")
    assert (
        m.post("/api/billing/family/accept/", {"token": token}, format="json").data["code"] == "family_full"
    )


def test_one_family_per_person(owner, keys, gateway, fplan):
    c, _ = owner
    _, mu, _ = join(c, "appa@home.in")
    c2, _ = client_for("other@home.in")
    pay(c2, pid="pay_2")
    _, token, _ = invite(c2, "appa@home.in")
    m = APIClient()
    m.force_authenticate(mu)
    assert m.post("/api/billing/family/accept/", {"token": token}, format="json").data["code"] == (
        "family_already"
    )
    # the member can't start their own family while in this one
    assert fam.FamilyMember.objects.filter(user=mu, left_at__isnull=True).count() == 1


def test_org_seat_on_a_same_or_better_plan_refuses_join(owner):
    c, _ = owner
    org = Organization.objects.create(name="Vidya School", slug="vidya", kind="school")
    seat_user = User.objects.create_user("kid@home.in", PW, email_verified=True)
    Membership.objects.create(org=org, user=seat_user, role="learner", seat=True)
    now = timezone.now()
    OrgSubscription.objects.create(
        org=org,
        plan=Plan.objects.get(code="family_month"),
        seats=5,
        starts_at=now,
        ends_at=now + timedelta(days=30),
    )
    _, token, _ = invite(c, "kid@home.in")
    k = APIClient()
    k.force_authenticate(seat_user)
    assert (
        k.post("/api/billing/family/accept/", {"token": token}, format="json").data["code"] == "seat_covered"
    )


def test_highest_priced_plan_wins_when_windows_overlap(owner, keys, gateway):
    c, _ = owner
    m, mu = client_for("appa@home.in")
    pay(m, plan="plus_year", pid="pay_own")  # ₹1,499 a year beats ₹299 a month
    _, token, _ = invite(c, "appa@home.in")
    assert m.post("/api/billing/family/accept/", {"token": token}, format="json").status_code == 200
    assert current_plan(mu).code == "plus_year"
    m2, mu2 = client_for("kid@home.in")
    pay(m2, plan="plus_month", pid="pay_kid")  # ₹149 loses to the family plan
    _, token2, _ = invite(c, "kid@home.in")
    m2.post("/api/billing/family/accept/", {"token": token2}, format="json")
    assert active_entitlement(mu2).source == "family" and current_plan(mu2).code == "family_month"
    # own time isn't pushed behind the family share
    own = Entitlement.objects.get(user=mu2, source="payment")
    assert own.starts_at < timezone.now() + timedelta(minutes=1)


# ── leaving ─────────────────────────────────────────────────────────


def test_owner_removes_a_member_and_they_are_told(owner, django_capture_on_commit_callbacks):
    c, _ = owner
    _, mu, _ = join(c, "appa@home.in")
    mid = FamilyMember.objects.get(user=mu).id
    with django_capture_on_commit_callbacks(execute=True):
        r = c.post(f"/api/billing/family/members/{mid}/remove/")
    assert r.status_code == 200 and len(r.data["members"]) == 1
    assert current_plan(mu).code == "free" and paid_until(mu) is None
    assert Notification.objects.filter(user=mu, title="Your family plan access has ended").exists()
    assert FamilyMember.objects.get(pk=mid).removed_by.email == "amma@home.in"


def test_member_leaves_and_can_be_invited_again(owner):
    c, _ = owner
    m, mu, _ = join(c, "appa@home.in")
    assert m.post("/api/billing/family/leave/").data["role"] is None
    assert current_plan(mu).code == "free"
    _, token, _ = invite(c, "appa@home.in")
    assert m.post("/api/billing/family/accept/", {"token": token}, format="json").status_code == 200
    assert current_plan(mu).code == "family_month"
    assert Entitlement.objects.filter(user=mu, source="family").count() == 1  # the old mirror is reused


def test_owner_cannot_remove_self_and_leaving_disbands(owner):
    c, u = owner
    _, mu, _ = join(c, "appa@home.in")
    mine = FamilyMember.objects.get(user=u, left_at__isnull=True)
    assert c.post(f"/api/billing/family/members/{mine.id}/remove/").status_code == 400
    invite(c, "kid@home.in")
    c.post("/api/billing/family/leave/")
    assert not FamilyMember.objects.filter(left_at__isnull=True).exists()
    assert current_plan(mu).code == "free" and current_plan(u).code == "family_month"
    assert not fam.pending_invites(FamilyGroup.objects.get(owner=u)).exists()


# ── propagation of the owner's access ───────────────────────────────


def test_owner_renewal_reaches_members(owner, keys, gateway):
    c, u = owner
    _, mu, _ = join(c, "appa@home.in")
    pay(c, pid="pay_renew")  # stacks after the first month
    assert Entitlement.objects.filter(user=mu, source="family").count() == 2
    assert paid_until(mu) == paid_until(u)


def test_manual_grant_and_redeem_reach_members(owner, fplan):
    from apps.billing.services import manual_grant

    c, u = owner
    _, mu, _ = join(c, "appa@home.in")
    manual_grant(u, fplan, 10, None, "goodwill")
    assert paid_until(mu) == paid_until(u)


def hook(event, sub_id, pay=None, sub_status="active"):
    payload = {
        "subscription": {
            "entity": {
                "id": sub_id,
                "status": sub_status,
                "current_start": 1_800_000_000,
                "current_end": 1_802_592_000,
                "charge_at": 1_802_592_000,
                "paid_count": 1,
            }
        }
    }
    if pay:
        payload["payment"] = {"entity": pay}
    body = json.dumps({"event": event, "payload": payload}).encode()
    return APIClient().post(
        "/api/billing/webhook/",
        body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=sign(body, HOOK),
    )


def test_auto_renew_charge_and_grace_propagate(keys, sub_gateway, fplan):
    fplan.rp_plan_id, fplan.auto_renew = "plan_TESTfamily1", True
    fplan.save()
    c, u = client_for("amma@home.in")
    sid = c.post("/api/billing/subscribe/", {"plan": "family_month"}, format="json").data["subscription_id"]
    charge = {"id": "pay_s1", "status": "captured", "amount": 29900, "order_id": "order_s1", "method": "upi"}
    assert hook("subscription.charged", sid, charge).status_code == 200
    _, mu, r = join(c, "appa@home.in")
    assert r.status_code == 200 and paid_until(mu) == paid_until(u)
    hook("subscription.halted", sid, sub_status="halted")  # grace window: mirrored too
    grace = Entitlement.objects.get(user=u, source="grace")
    assert Entitlement.objects.get(user=mu, derived_from=grace).ends_at == grace.ends_at
    sub = Subscription.objects.get()
    sub.paid_count = 1
    sub.save()
    charge2 = {**charge, "id": "pay_s2", "order_id": "order_s2"}
    body_paid = {**charge2}
    assert hook("subscription.charged", sid, body_paid).status_code == 200
    grace.refresh_from_db()
    mirror = Entitlement.objects.get(user=mu, derived_from=grace)
    assert (mirror.starts_at, mirror.ends_at) == (grace.starts_at, grace.ends_at)  # ended with the owner's
    assert grace.ends_at == grace.starts_at  # (it was stacked after the paid month, so it never starts)
    assert paid_until(mu) == paid_until(u)


def test_refund_with_end_access_reaches_members(owner, monkeypatch, django_capture_on_commit_callbacks):
    from apps.billing import razorpay as rp

    c, u = owner
    _, mu, _ = join(c, "appa@home.in")
    monkeypatch.setattr(rp, "create_refund", lambda *a: {"id": "rfnd_1", "status": "processed"})
    fin, _ = client_for("fin@aasan.in", roles=["finance"])
    order = Order.objects.get(user=u)
    r = fin.post(
        "/api/admin/refunds/", {"order_id": order.id, "reason": "Asked", "end_access": True}, format="json"
    )
    assert r.status_code == 201 and r.data["access_ended"] is True
    assert current_plan(u).code == "free" and current_plan(mu).code == "free"


def test_reminders_go_to_the_owner_only(owner):
    from apps.billing.reminders import send_due

    c, u = owner
    _, mu, _ = join(c, "appa@home.in")
    soon = timezone.now() + timedelta(days=2)
    Entitlement.objects.filter(user=u).update(ends_at=soon)
    fam.resync_owner(u)
    assert Entitlement.objects.get(user=mu).ends_at == soon
    assert send_due()["soon"] == 1
    assert Notification.objects.filter(user=u, kind="plan").exists()
    assert not Notification.objects.filter(user=mu, kind="plan").exists()


# ── admin ───────────────────────────────────────────────────────────


def test_admin_family_groups_list_and_csv(owner):
    c, _ = owner
    join(c, "appa@home.in")
    sup, _ = client_for("sup@aasan.in", roles=["support"])
    r = sup.get("/api/admin/family-groups/?q=appa")
    assert r.status_code == 200 and r.data["count"] == 1 and r.data["groups"] == 1 and r.data["members"] == 2
    row = r.data["results"][0]
    assert row["owner"] == "amma@home.in" and row["members"] == ["appa@home.in"] and row["members_count"] == 2
    assert row["plan"] == "Family Plus" and row["max_members"] == 3
    csv = sup.get("/api/admin/family-groups/?export=csv")
    assert csv["Content-Type"].startswith("text/csv") and b"amma@home.in" in csv.content
    content, _ = client_for("con@aasan.in", roles=["content"])
    assert content.get("/api/admin/family-groups/").status_code == 403
    assert sup.get("/api/admin/gifts/").status_code == 403


def test_plan_editor_family_fields():
    fin, _ = client_for("fin@aasan.in", roles=["finance"])
    base = {"code": "fam", "name": "Family", "price_paise": 29900, "period_days": 30, "limits": {}}
    r = fin.post("/api/admin/plans/", {**base, "family": True, "max_members": 25}, format="json")
    assert r.status_code == 400 and "max_members" in r.data
    r = fin.post("/api/admin/plans/", {**base, "price_paise": 0, "family": True}, format="json")
    assert r.status_code == 400 and "family" in r.data
    r = fin.post("/api/admin/plans/", {**base, "family": True, "max_members": 6}, format="json")
    assert r.status_code == 201 and r.data["family"] is True and r.data["max_members"] == 6
    free = Plan.objects.get(code="free")
    assert fin.patch(f"/api/admin/plans/{free.id}/", {"family": True}, format="json").status_code == 400


def test_overview_counts_family(owner):
    c, _ = owner
    join(c, "appa@home.in")
    sup, _ = client_for("boss@aasan.in", roles=["superadmin"])
    fam_block = sup.get("/api/admin/overview/").data["platform"]["family"]
    assert fam_block == {"groups": 1, "members": 1, "mrr_paise": 0}  # test-mode money stays out of MRR
    Order.objects.update(mode="live")
    assert sup.get("/api/admin/overview/").data["platform"]["family"]["mrr_paise"] == 29900
