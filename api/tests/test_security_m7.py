"""Regression tests for the Milestone 7 security review fixes."""

from types import SimpleNamespace

import pytest
from django.core import mail
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone

from apps.billing.models import Order, Plan, PromoCode
from apps.learning.models import Curriculum
from apps.orgs.models import Membership, Organization
from apps.studio import snapshot
from tests.test_schools import client_for

pytestmark = pytest.mark.django_db

COURSE = "format: aasan-course\nsections:\n  - title: Basics\n    lessons:\n      - title: One\n"


def test_yaml_aliases_are_refused():
    bomb = 'a: &a ["x","x","x","x","x","x","x","x","x","x"]\nb: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a,*a]\n' + COURSE
    with pytest.raises(snapshot.SnapshotError):
        snapshot.load_yaml(bomb)
    assert snapshot.load_yaml(COURSE)["sections"][0]["title"] == "Basics"


def test_structures_never_become_text():
    assert (
        snapshot._txt(["x"] * 10, 50) == ""
        and snapshot._txt({"a": 1}, 50) == ""
        and snapshot._txt(7, 5) == "7"
    )


def test_invoice_markup_is_escaped():
    from apps.billing.invoices import render_pdf

    evil = '<img src="http://127.0.0.1:9/x.png" width="1" height="1"/><b>unbalanced'
    inv = SimpleNamespace(
        seller={"name": "Aasan", "address": "Chennai", "state": "Tamil Nadu", "gstin": ""},
        buyer={"name": evil, "email": "a@b.in", "state": "Tamil Nadu", "gstin": ""},
        number="INV/2026-27/00001",
        issued_at=timezone.now(),
        order=SimpleNamespace(rp_order_id="order_1", rp_payment_id="pay_1", mode="test"),
        lines=[
            {
                "description": evil,
                "sac": "999293",
                "qty": 1,
                "list_paise": 100,
                "discount_paise": 0,
                "total_paise": 100,
            }
        ],
        taxable_paise=85,
        igst_paise=0,
        cgst_paise=8,
        sgst_paise=7,
        total_paise=100,
    )
    assert render_pdf(inv).startswith(
        b"%PDF"
    )  # used to raise on the unbalanced tag (and fetch the image URL)


def test_undo_or_restore_sends_approved_course_back_to_review():
    _, u = client_for("author@x.in")
    cur = Curriculum.objects.create(
        owner=u,
        kind="authored",
        status="ready",
        title="T",
        goal="g",
        catalog_status=Curriculum.CatalogStatus.APPROVED,
    )
    snapshot.apply(cur, snapshot.validate(snapshot.load_yaml(COURSE)), trusted=False)
    cur.refresh_from_db()
    assert cur.catalog_status == Curriculum.CatalogStatus.PENDING


def test_promo_counts_unpaid_checkouts_and_school_seats_need_permission():
    c, u = client_for("promo@x.in")
    PromoCode.objects.create(code="ONCE", kind="percent", value=50, max_uses=1)
    plan = Plan.objects.get(code="plus_month")
    Order.objects.create(
        user=u,
        plan=plan,
        amount_paise=100,
        rp_order_id="order_pending",
        promo=PromoCode.objects.get(code="ONCE"),
    )
    assert (
        c.post("/api/billing/quote/", {"plan": "plus_month", "promo": "ONCE"}, format="json").data["code"]
        == "promo_invalid"
    )
    PromoCode.objects.create(code="ALLFREE", kind="percent", value=100, per_user=0)
    org = Organization.objects.create(name="S", slug="s", kind="school")
    Membership.objects.create(org=org, user=u, role="owner")
    seats = {"plan": "plus_month", "promo": "ALLFREE", "org": "s", "seats": 500}
    assert c.post("/api/billing/quote/", seats, format="json").data["code"] == "promo_invalid"
    PromoCode.objects.filter(code="ALLFREE").update(max_seats=500)
    assert c.post("/api/billing/quote/", seats, format="json").data["total_paise"] == 0


def test_invite_daily_allowance():
    c, u = client_for("inviter@x.in")
    org = Organization.objects.create(name="S", slug="s", kind="school")
    Membership.objects.create(org=org, user=u, role="owner")
    many = [f"p{i}@x.in" for i in range(21)]
    r = c.post("/api/orgs/s/invitations/", {"emails": many}, format="json")
    assert r.status_code == 429 and r.data["verify_email"] and not mail.outbox
    assert c.post("/api/orgs/s/invitations/", {"emails": many[:3]}, format="json").status_code == 201
    assert (
        mail.outbox[0].subject == "You're invited to learn on Aasan"
    )  # org-chosen names stay out of subjects


def test_leaderboard_switch_covers_revision_board_and_hides_learners():
    c, u = client_for("kid@x.in")
    org = Organization.objects.create(name="S", slug="s", kind="school", features={"leaderboard": False})
    Membership.objects.create(org=org, user=u, role="learner")
    assert c.get("/api/study/revision-board/").status_code == 403
    from apps.orgs.extras import hidden_from_boards

    assert u.id in {r["user_id"] for r in hidden_from_boards()}


def test_lecture_files_are_served_with_ranges(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    name = "0" * 32 + ".mp4"
    default_storage.save(f"lectures/1/{name}", ContentFile(b"\x00\x00\x00\x18ftypmp42" + b"x" * 100))
    c, _ = client_for("viewer@x.in")
    r = c.get(f"/api/media/lectures/1/{name}", HTTP_RANGE="bytes=0-3")
    assert r.status_code == 206 and r.content == b"\x00\x00\x00\x18" and r["Content-Range"].endswith("/112")
    assert c.get("/api/media/lectures/1/evil.html").status_code == 404
