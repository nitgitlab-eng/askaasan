"""Admin console: staff roles per section, the audit log, staff management, users, organisations (incl. suspension),
certificates and templates, refunds, and the dashboard's platform block."""

import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import AdminAuditLog, StaffRole, User
from apps.billing.models import Entitlement, Order, Plan, Refund
from apps.credentials.models import Certificate, CertificateTemplate
from apps.orgs.models import Membership, Organization

pytestmark = pytest.mark.django_db
PW = "Admin#Console2026"


def client_for(email, *, roles=None, staff=False, superuser=False):
    u = User.objects.create_user(email, PW)
    if staff or roles is not None:
        u.is_staff = True
    u.is_superuser = superuser
    u.save()
    if roles is not None:
        StaffRole.objects.create(user=u, roles=roles)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


# ── roles ────────────────────────────────────────────────────────────

SECTIONS = {  # one GET per section → which roles get in (superadmin always does)
    "/api/admin/overview/": {"support", "finance", "content"},
    "/api/admin/providers/": set(),
    "/api/admin/site/": set(),
    "/api/admin/staff/": set(),
    "/api/admin/audit/": set(),
    "/api/admin/payments/orders/": {"finance"},
    "/api/admin/plans/": {"finance"},
    "/api/admin/invoices/": {"finance"},
    "/api/admin/refunds/": {"finance"},
    "/api/admin/family-groups/": {"finance", "support"},
    "/api/admin/gifts/": {"finance"},
    "/api/admin/reports/": {"support"},
    "/api/admin/catalog/": {"content"},
    "/api/admin/workshops/runs/": {"content"},
    "/api/admin/workshops/orgs/": {"support"},
    "/api/admin/features/": {"content"},
    "/api/admin/users/": {"support", "finance"},
    "/api/admin/orgs/": {"support", "finance"},
    "/api/admin/certificates/": {"content", "support"},
    "/api/admin/certificate-templates/": {"content"},
}


@pytest.mark.parametrize("role", ["superadmin", "support", "finance", "content"])
def test_role_matrix(role):
    c, _ = client_for(f"{role}@aasan.in", roles=[role])
    for url, allowed in SECTIONS.items():
        code = c.get(url).status_code
        want = role == "superadmin" or role in allowed
        assert (code == 200) == want, (role, url, code)
        assert code in (200, 403), (url, code)


def test_staff_without_role_row_get_no_access_and_learners_never_get_in():
    bare, _ = client_for(
        "old@aasan.in", staff=True
    )  # is_staff set some other way (e.g. Django admin): fail closed
    assert bare.get("/api/admin/staff/").status_code == 403
    assert bare.get("/api/users/me/").data["staff_roles"] == []
    learner, _ = client_for("kid@aasan.in")
    assert learner.get("/api/admin/overview/").status_code == 403
    assert learner.get("/api/users/me/").data["staff_roles"] == []


def test_migration_keeps_existing_role_less_staff_as_superadmins():
    import importlib

    from django.apps import apps

    _, legacy = client_for("legacy@aasan.in", staff=True)
    _, scoped = client_for("scoped@aasan.in", roles=["support"])
    importlib.import_module("apps.accounts.migrations.0013_staff_roles_backfill").backfill(apps, None)
    assert StaffRole.objects.get(user=legacy).roles == ["superadmin"]
    assert StaffRole.objects.get(user=scoped).roles == ["support"]


def test_unlisted_admin_path_is_superadmin_only():
    from apps.accounts.staff import may_enter

    _, u = client_for("f@aasan.in", roles=["finance"])
    assert not may_enter(u, "/api/admin/brand-new-thing/")
    _, s = client_for("s@aasan.in", roles=["superadmin"])
    assert may_enter(s, "/api/admin/brand-new-thing/")


# ── audit log ────────────────────────────────────────────────────────


def test_admin_changes_are_audited_with_secrets_masked():
    c, u = client_for("boss@aasan.in", roles=["superadmin"])
    r = c.patch(
        "/api/admin/payments/config/", {"key_id": "rzp_test_K1", "key_secret": "supersecret99"}, format="json"
    )
    assert r.status_code == 200
    log = AdminAuditLog.objects.get()
    assert (log.actor, log.method, log.section, log.status) == (u, "PATCH", "payments", 200)
    assert log.data == {"key_id": "•••", "key_secret": "•••"}
    assert "supersecret99" not in json.dumps(log.data)
    c.get("/api/admin/payments/orders/")
    assert AdminAuditLog.objects.count() == 1  # reads aren't logged
    rows = c.get("/api/admin/audit/?q=payments").data
    assert rows["count"] == 1 and rows["results"][0]["actor"] == "boss@aasan.in"


def test_refused_requests_are_not_audited():
    c, _ = client_for("fin@aasan.in", roles=["finance"])
    assert c.patch("/api/admin/site/", {"legal_name": "x"}, format="json").status_code == 403
    assert not AdminAuditLog.objects.exists()


def test_audit_csv_export_neutralises_formulas():
    c, _ = client_for("boss@aasan.in", roles=["superadmin"])
    c.post("/api/admin/staff/", {"email": "=HYPERLINK(1)", "roles": []}, format="json")
    r = c.get("/api/admin/audit/?export=csv")
    assert r["Content-Type"].startswith("text/csv")
    assert "'=HYPERLINK" in r.content.decode() or "=HYPERLINK" not in r.content.decode()


# ── staff management ────────────────────────────────────────────────


def test_superadmin_sets_and_removes_roles():
    c, me = client_for("boss@aasan.in", roles=["superadmin"])
    _, u = client_for("meena@aasan.in")
    r = c.post(
        "/api/admin/staff/", {"email": "meena@aasan.in", "roles": ["support", "finance"]}, format="json"
    )
    assert r.status_code == 200 and r.data["roles"] == ["finance", "support"]
    u.refresh_from_db()
    assert u.is_staff
    assert (
        c.post(
            "/api/admin/staff/", {"email": "meena@aasan.in", "roles": ["owner"]}, format="json"
        ).status_code
        == 400
    )
    r = c.post("/api/admin/staff/", {"email": "meena@aasan.in", "roles": []}, format="json")
    u.refresh_from_db()
    assert r.data["roles"] == [] and not u.is_staff and not StaffRole.objects.filter(user=u).exists()


def test_cannot_demote_self_or_the_last_superadmin():
    c, me = client_for("boss@aasan.in", roles=["superadmin"])
    assert c.post("/api/admin/staff/", {"email": me.email, "roles": ["support"]}, format="json").data[
        "code"
    ] == ("cannot_demote_self")
    other, o = client_for("two@aasan.in", roles=["superadmin"])
    assert (
        other.post("/api/admin/staff/", {"email": me.email, "roles": ["support"]}, format="json").status_code
        == 200
    )
    # `o` is now the only superadmin: nobody else can demote them
    c2, _ = client_for("three@aasan.in", roles=["superadmin"])
    c2.post("/api/admin/staff/", {"email": "three@aasan.in", "roles": ["superadmin"]}, format="json")
    StaffRole.objects.filter(user__email="three@aasan.in").update(roles=["support"])
    StaffRole.objects.filter(user=o).update(roles=["superadmin"])
    solo = APIClient()
    solo.force_authenticate(o)
    assert solo.post("/api/admin/staff/", {"email": o.email, "roles": []}, format="json").data["code"] == (
        "cannot_demote_self"
    )


def test_make_admin_command_sets_roles():
    from django.core.management import call_command

    u = User.objects.create_user("new@aasan.in", PW)
    call_command("make_admin", "new@aasan.in", "--role", "finance")
    assert StaffRole.objects.get(user=u).roles == ["finance"]
    call_command("make_admin", "new@aasan.in", "--revoke")
    u.refresh_from_db()
    assert not u.is_staff and not StaffRole.objects.filter(user=u).exists()


# ── users ────────────────────────────────────────────────────────────


def test_user_list_search_filters_and_csv():
    c, _ = client_for("sup@aasan.in", roles=["support"])
    a = User.objects.create_user("arun@school.in", PW)
    User.objects.create_user("bala@school.in", PW, is_active=False)
    r = c.get("/api/admin/users/?q=school")
    assert r.data["count"] == 2 and r.data["totals"]["total"] == 3
    assert [x["email"] for x in c.get("/api/admin/users/?filter=inactive").data["results"]] == [
        "bala@school.in"
    ]
    plan = Plan.objects.create(code="pro", name="Pro", price_paise=19900)
    Entitlement.objects.create(
        user=a,
        plan=plan,
        starts_at=timezone.now(),
        ends_at=timezone.now() + timedelta(days=30),
        source="grant",
    )
    assert [x["email"] for x in c.get("/api/admin/users/?filter=paying").data["results"]] == [
        "arun@school.in"
    ]
    csv = c.get("/api/admin/users/?export=csv")
    assert csv.status_code == 200 and "arun@school.in" in csv.content.decode()
    d = c.get(f"/api/admin/users/{a.id}/").data
    assert d["plans"][0]["plan"] == "Pro" and d["plans"][0]["active"] is True


def test_user_actions_and_their_limits():
    sup, _ = client_for("sup@aasan.in", roles=["support"])
    fin, _ = client_for("fin@aasan.in", roles=["finance"])
    u = User.objects.create_user("arun@school.in", PW)
    url = f"/api/admin/users/{u.id}/action/"
    assert (
        fin.post(url, {"action": "deactivate"}, format="json").status_code == 403
    )  # finance can look, not act
    r = sup.post(url, {"action": "deactivate"}, format="json")
    assert r.status_code == 200 and r.data["active"] is False
    assert sup.post(url, {"action": "reactivate"}, format="json").data["active"] is True
    assert sup.post(url, {"action": "set_creator"}, format="json").data["creator"] is True
    assert sup.post(url, {"action": "nuke"}, format="json").status_code == 400
    _, staffer = client_for("staff2@aasan.in", roles=["content"])
    assert (
        sup.post(
            f"/api/admin/users/{staffer.id}/action/", {"action": "deactivate"}, format="json"
        ).status_code
        == 403
    )


def test_force_logout_revokes_refresh_tokens():
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
    from rest_framework_simplejwt.tokens import RefreshToken

    sup, _ = client_for("sup@aasan.in", roles=["support"])
    u = User.objects.create_user("arun@school.in", PW)
    RefreshToken.for_user(u)
    sup.post(f"/api/admin/users/{u.id}/action/", {"action": "force_logout"}, format="json")
    assert BlacklistedToken.objects.filter(token__user=u).exists()


# ── organisations ────────────────────────────────────────────────────


@pytest.fixture
def school():
    org = Organization.objects.create(name="Vidya School", slug="vidya", kind="school")
    owner = User.objects.create_user("owner@vidya.in", PW)
    Membership.objects.create(org=org, user=owner, role="owner")
    kid = User.objects.create_user("kid@vidya.in", PW)
    Membership.objects.create(org=org, user=kid, role="learner")
    return org, owner, kid


def test_org_list_and_detail(school):
    org, owner, _ = school
    c, _ = client_for("fin@aasan.in", roles=["finance"])
    r = c.get("/api/admin/orgs/?q=vidya")
    assert (
        r.data["count"] == 1 and r.data["results"][0]["members"] == 2 and r.data["by_kind"] == {"school": 1}
    )
    d = c.get(f"/api/admin/orgs/{org.id}/").data
    assert d["members_by_role"] == {"owner": 1, "learner": 1}
    assert d["admins"] == [{"id": owner.id, "email": "owner@vidya.in", "role": "owner"}]
    # Workshops are on by default (never stored) and listed as a platform-admin-only switch.
    assert d["features"]["workshops"] is True and d["features"]["mentor"] is True
    assert d["platform_features"] == ["workshops"] and org.features == {}
    assert c.patch(f"/api/admin/orgs/{org.id}/", {"workshop_seats": 5}, format="json").status_code == 403


def test_org_features_seats_and_suspension(school):
    org, owner, _ = school
    c, _ = client_for("sup@aasan.in", roles=["support"])
    url = f"/api/admin/orgs/{org.id}/"
    d = c.patch(
        url, {"features": {"workshops": True, "roleplay": False}, "workshop_seats": 40}, format="json"
    ).data
    assert (
        d["features"]["workshops"] is True
        and d["features"]["roleplay"] is False
        and d["workshop_seats"] == 40
    )
    d = c.patch(url, {"features": {"workshops": False}}, format="json").data
    org.refresh_from_db()
    assert d["features"]["workshops"] is False and org.features["workshops"] is False  # explicit off wins
    assert c.patch(url, {"features": {"bogus": True}}, format="json").status_code == 400

    oc = APIClient()
    oc.force_authenticate(owner)
    assert oc.get("/api/orgs/vidya/").status_code == 200
    d = c.patch(url, {"suspended": True, "suspended_reason": "Unpaid"}, format="json").data
    assert d["suspended"] is True and d["suspended_reason"] == "Unpaid"
    r = oc.get("/api/orgs/vidya/")
    assert r.status_code == 403 and "org_suspended" in str(r.data)
    c.patch(url, {"suspended": False}, format="json")
    assert oc.get("/api/orgs/vidya/").status_code == 200


# ── certificates + templates ─────────────────────────────────────────


def _cert(user, **kw):
    return Certificate.objects.create(
        user=user,
        kind="course",
        title="Excel basics",
        learner_name="Arun",
        issuer_name="Aasan",
        dedupe=f"x{user.id}",
        **kw,
    )


def test_certificate_list_revoke_and_refresh_name():
    c, _ = client_for("cont@aasan.in", roles=["content"])
    u = User.objects.create_user("arun@school.in", PW)
    cert = _cert(u)
    r = c.get("/api/admin/certificates/?q=arun")
    assert r.data["count"] == 1 and r.data["stats"]["total"] == 1
    u.profile.display_name = "Arun Kumar"
    u.profile.save()
    assert c.post(f"/api/admin/certificates/{cert.id}/refresh-name/").data["learner"] == "Arun Kumar"
    assert c.post(f"/api/admin/certificates/{cert.id}/revoke/").data["revoked"] is True
    assert c.post(f"/api/admin/certificates/{cert.id}/refresh-name/").status_code == 409
    assert c.get("/api/admin/certificates/?status=revoked").data["count"] == 1


def test_platform_template_create_update_validate_and_preview():
    c, _ = client_for("cont@aasan.in", roles=["content"])
    r = c.post(
        "/api/admin/certificate-templates/",
        {
            "kind": "workshop",
            "layout": "modern",
            "colors": {"accent": "#0f766e"},
            "signatory_name": "Dr. Meena",
        },
        format="json",
    )
    assert (
        r.status_code == 201
        and r.data["colors"]["accent"] == "#0f766e"
        and r.data["colors"]["ink"] == "#1f2a44"
    )
    again = c.post(
        "/api/admin/certificate-templates/", {"kind": "workshop", "layout": "minimal"}, format="json"
    )
    assert again.status_code == 200 and again.data["id"] == r.data["id"] and again.data["layout"] == "minimal"
    for bad in (
        {"layout": "fancy"},
        {"colors": {"accent": "red"}},
        {"logo": "https://evil.example/logo.png"},
        {"kind": "diploma"},
    ):
        assert c.post("/api/admin/certificate-templates/", bad, format="json").status_code == 400, bad
    pdf = c.post(
        "/api/admin/certificate-templates/preview/",
        {
            "kind": "workshop",
            "layout": "modern",
            "headline": "Certificate of Excellence",
            "footer_note": "NSDC partner",
        },
        format="json",
    )
    assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf" and pdf.content[:5] == b"%PDF-"
    assert c.delete(f"/api/admin/certificate-templates/{r.data['id']}/").status_code == 204


def test_template_resolution_prefers_the_most_specific(school):
    from apps.credentials.templates import resolve

    org, _, kid = school
    cert = _cert(kid, org=org)
    assert resolve(cert) is None
    base = CertificateTemplate.objects.create(layout="classic")
    assert resolve(cert) == base
    plat_kind = CertificateTemplate.objects.create(kind="course", layout="modern")
    assert resolve(cert) == plat_kind
    mine = CertificateTemplate.objects.create(org=org, layout="minimal")
    assert resolve(cert) == mine  # any org template beats platform ones
    mine_kind = CertificateTemplate.objects.create(org=org, kind="course", language="en", layout="modern")
    assert resolve(cert) == mine_kind
    mine_kind.active = False
    mine_kind.save()
    assert resolve(cert) == mine
    from apps.credentials.pdf import render

    assert render(cert)[:5] == b"%PDF-"


def test_org_admins_manage_their_own_templates_only(school):
    org, owner, kid = school
    oc = APIClient()
    oc.force_authenticate(owner)
    r = oc.post(
        "/api/credentials/orgs/vidya/templates/",
        {"layout": "modern", "signatory_name": "Principal"},
        format="json",
    )
    assert r.status_code == 201 and r.data["org_id"] == org.id
    assert (
        oc.post("/api/credentials/orgs/vidya/templates/preview/", {}, format="json").content[:5] == b"%PDF-"
    )
    kc = APIClient()
    kc.force_authenticate(kid)
    assert kc.get("/api/credentials/orgs/vidya/templates/").status_code == 403
    plat = CertificateTemplate.objects.create(layout="classic")
    assert (
        oc.patch(
            f"/api/credentials/orgs/vidya/templates/{plat.id}/", {"layout": "modern"}, format="json"
        ).status_code
        == 404
    )


def test_template_images_survive_the_media_sweep():
    from apps.media.cleanup import referenced_names

    CertificateTemplate.objects.create(
        logo="/api/media/" + "a" * 32 + ".png", signature="/api/media/" + "b" * 32 + ".webp"
    )
    names = referenced_names()
    assert "a" * 32 + ".png" in names and "b" * 32 + ".webp" in names


# ── refunds ──────────────────────────────────────────────────────────


@pytest.fixture
def paid_order(keys):
    u = User.objects.create_user("buyer@x.in", PW)
    plan = Plan.objects.create(code="pro", name="Pro", price_paise=19900, period_days=30)
    o = Order.objects.create(
        user=u,
        plan=plan,
        amount_paise=19900,
        status="paid",
        mode="test",
        rp_order_id="order_1",
        rp_payment_id="pay_1",
    )
    Entitlement.objects.create(
        user=u, plan=plan, order=o, starts_at=timezone.now(), ends_at=timezone.now() + timedelta(days=30)
    )
    return o


def test_refund_partial_then_rest_and_end_access(paid_order, monkeypatch):
    from apps.billing import razorpay as rp

    sent = []
    monkeypatch.setattr(
        rp,
        "create_refund",
        lambda k, pid, amt, notes: (
            sent.append((pid, amt)) or {"id": f"rfnd_{len(sent)}", "status": "pending"}
        ),
    )
    c, _ = client_for("fin@aasan.in", roles=["finance"])
    url = "/api/admin/refunds/"
    assert (
        c.post(url, {"order_id": paid_order.id, "reason": "x"}, format="json").data["code"]
        == "reason_required"
    )
    r = c.post(
        url, {"order_id": paid_order.id, "amount_paise": 5000, "reason": "Duplicate charge"}, format="json"
    )
    assert r.status_code == 201 and r.data["status"] == "pending" and sent == [("pay_1", 5000)]
    over = c.post(url, {"order_id": paid_order.id, "amount_paise": 15000, "reason": "Rest"}, format="json")
    assert over.data == {"code": "bad_amount", "refundable_paise": 14900}
    r = c.post(url, {"order_id": paid_order.id, "reason": "Rest of it", "end_access": True}, format="json")
    assert r.data["amount_paise"] == 14900 and r.data["access_ended"] is True
    assert not Entitlement.objects.filter(order=paid_order, ends_at__gt=timezone.now()).exists()
    assert c.post(url, {"order_id": paid_order.id, "reason": "Again"}, format="json").status_code == 400
    lst = c.get(url).data
    assert lst["count"] == 2 and lst["total_paise"] == 19900
    orders = c.get("/api/admin/payments/orders/").data
    assert orders["orders"][0]["refunded_paise"] == 19900 and orders["pages"] == 1


def test_refund_gateway_failure_is_recorded(paid_order, monkeypatch):
    from apps.billing import razorpay as rp

    def boom(*a):
        raise rp.RazorpayError("api_error", "400: payment not captured")

    monkeypatch.setattr(rp, "create_refund", boom)
    c, _ = client_for("fin@aasan.in", roles=["finance"])
    r = c.post("/api/admin/refunds/", {"order_id": paid_order.id, "reason": "Customer asked"}, format="json")
    assert r.status_code == 502 and r.data["status"] == "failed"
    assert Refund.objects.get().status == "failed"
    # a failed refund doesn't count against what's refundable
    monkeypatch.setattr(rp, "create_refund", lambda *a: {"id": "rfnd_9", "status": "processed"})
    assert (
        c.post("/api/admin/refunds/", {"order_id": paid_order.id, "reason": "Retry"}, format="json").data[
            "amount_paise"
        ]
        == 19900
    )


def test_refund_webhook_settles_status(paid_order):
    from tests.conftest import HOOK

    Refund.objects.create(order=paid_order, amount_paise=19900, reason="r", rp_refund_id="rfnd_7")
    body = json.dumps(
        {"event": "refund.processed", "payload": {"refund": {"entity": {"id": "rfnd_7"}}}}
    ).encode()
    sig = hmac.new(HOOK.encode(), body, hashlib.sha256).hexdigest()
    r = APIClient().post(
        "/api/billing/webhook/", body, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE=sig
    )
    assert r.status_code == 200 and r.data["result"] == "processed"
    assert Refund.objects.get().status == "processed"


def test_only_paid_orders_with_a_payment_can_be_refunded(keys):
    u = User.objects.create_user("buyer@x.in", PW)
    o = Order.objects.create(user=u, amount_paise=100, status="created", mode="test", rp_order_id="order_2")
    c, _ = client_for("fin@aasan.in", roles=["finance"])
    assert (
        c.post("/api/admin/refunds/", {"order_id": o.id, "reason": "nope"}, format="json").status_code == 409
    )


# ── dashboard ────────────────────────────────────────────────────────


def test_overview_has_platform_block(school):
    c, u = client_for("sup@aasan.in", roles=["support"])
    _cert(u)
    p = c.get("/api/admin/overview/").data["platform"]
    assert p["certificates"]["total"] == 1 and p["orgs"]["by_kind"] == {"school": 1}
    assert set(p) == {"workshops", "certificates", "orgs", "subscriptions", "refunds", "family"}


# ── last seen ────────────────────────────────────────────────────────


def test_sign_in_records_last_seen_and_users_header_counts_it():
    u = User.objects.create_user("seen@example.com", PW)
    assert u.last_login is None
    r = APIClient().post("/api/users/login/", {"email": "seen@example.com", "password": PW}, format="json")
    assert r.status_code == 200
    u.refresh_from_db()
    assert u.last_login and timezone.now() - u.last_login < timedelta(minutes=1)

    staff, _ = client_for("boss@example.com", superuser=True, staff=True)
    body = staff.get("/api/admin/users/").json()
    assert body["totals"]["active_7d"] >= 1
    row = next(x for x in body["results"] if x["email"] == "seen@example.com")
    assert row["last_login"]


def test_last_seen_is_written_at_most_hourly():
    from apps.accounts.tokens import issue_tokens

    u = User.objects.create_user("hourly@example.com", PW)
    earlier = timezone.now() - timedelta(minutes=20)
    User.objects.filter(pk=u.pk).update(last_login=earlier)
    issue_tokens(u)
    u.refresh_from_db()
    assert u.last_login == earlier  # still fresh: no write
    User.objects.filter(pk=u.pk).update(last_login=timezone.now() - timedelta(hours=2))
    issue_tokens(u)
    u.refresh_from_db()
    assert timezone.now() - u.last_login < timedelta(minutes=1)
