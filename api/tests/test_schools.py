"""Milestone 5: surveys v2, org extras (brand, features, fields, setup, campaigns, referrals, shared notes),
billing (promo, redeem, seats, GST invoices), guardian view."""

import io
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.models import Invoice, OrgSubscription, Plan, PromoCode, RedeemCode
from apps.billing.services import current_plan
from apps.orgs.models import Campaign, Membership, Organization, ReferralUse, Survey, SurveyResponse
from tests.test_billing import sign

pytestmark = pytest.mark.django_db
PW = "Schools#2026pass"


def client_for(email, staff=False, **kw):
    u = User.objects.create_user(email, PW, is_staff=staff, **kw)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


@pytest.fixture
def school():
    admin, au = client_for("admin@school.in")
    org = Organization.objects.create(name="Vidya School", slug="vidya", kind="school")
    Membership.objects.create(org=org, user=au, role="owner")
    kid, ku = client_for("kid@school.in")
    Membership.objects.create(org=org, user=ku, role="learner")
    return org, (admin, au), (kid, ku)


# ── Surveys v2 ───────────────────────────────────────────────────────

QS = [
    {"id": "q1", "type": "rating", "text": "Lessons useful?", "required": True},
    {"id": "q2", "type": "multi", "text": "What helped?", "options": ["Videos", "Quizzes", "Kili"]},
    {
        "id": "q3",
        "type": "matrix",
        "text": "Rate",
        "rows": ["Pace", "Difficulty"],
        "options": ["Low", "OK", "High"],
    },
    {
        "id": "q4",
        "type": "scale",
        "text": "Confidence",
        "min": 1,
        "max": 7,
        "min_label": "low",
        "max_label": "high",
    },
    {"id": "q5", "type": "text", "text": "Anything else?"},
]


def test_survey_builder_types_required_drafts_and_results(school):
    org, (admin, _), (kid, ku) = school
    assert (
        admin.post(
            "/api/orgs/vidya/surveys/",
            {"title": "Bad", "questions": [{"type": "matrix", "text": "x", "options": ["a", "b"]}]},
            format="json",
        ).status_code
        == 400
    )
    s = admin.post(
        "/api/orgs/vidya/surveys/",
        {"title": "Term feedback", "questions": QS, "anonymous": False},
        format="json",
    ).data
    admin.patch(f"/api/orgs/vidya/surveys/{s['id']}/", {"status": "open"}, format="json")
    # save-and-resume
    d = kid.put(
        f"/api/orgs/surveys/{s['id']}/draft/", {"answers": {"q2": ["Kili", "Videos"]}}, format="json"
    ).data
    assert d["answers"]["q2"] == ["Videos", "Kili"]  # normalised to option order
    mine = kid.get("/api/orgs/me/surveys/").data[0]
    assert mine["draft"] == {"q2": ["Videos", "Kili"]}
    r = kid.post(f"/api/orgs/surveys/{s['id']}/respond/", {"answers": {"q2": ["Kili"]}}, format="json")
    assert r.status_code == 400 and r.data == {"code": "required", "question": "q1"}
    assert (
        kid.post(
            f"/api/orgs/surveys/{s['id']}/respond/",
            {"answers": {"q1": 4, "q3": {"Pace": "Nope"}}},
            format="json",
        ).data["code"]
        == "invalid_answer"
    )
    assert (
        kid.post(f"/api/orgs/surveys/{s['id']}/respond/", {"answers": {"q1": 9}}, format="json").data["code"]
        == "invalid_answer"
    )
    ok = kid.post(
        f"/api/orgs/surveys/{s['id']}/respond/",
        {
            "answers": {
                "q1": 4,
                "q2": ["Kili"],
                "q3": {"Pace": "OK", "Difficulty": "High"},
                "q4": 6,
                "q5": "=cmd()",
            }
        },
        format="json",
    )
    assert ok.status_code == 201 and not kid.get("/api/orgs/me/surveys/").data[0]["draft"]
    assert (
        kid.post(f"/api/orgs/surveys/{s['id']}/respond/", {"answers": {"q1": 5}}, format="json").status_code
        == 409
    )
    res = admin.get(f"/api/orgs/vidya/surveys/{s['id']}/results/").data["results"]
    by = {q["id"]: q for q in res}
    assert by["q2"]["options"][2] == {"option": "Kili", "count": 1}
    assert by["q3"]["rows"][1]["options"][2]["count"] == 1 and by["q4"]["avg"] == 6 and by["q4"]["max"] == 7
    # Excel export flattens multi/matrix answers and keeps "=cmd()" as text
    from openpyxl import load_workbook

    wb = load_workbook(
        io.BytesIO(admin.get(f"/api/studio/exports/orgs/vidya/surveys/{s['id']}.xlsx").content)
    )
    raw = [[c.value for c in row] for row in wb["Raw answers"].iter_rows()]
    assert "Pace: OK; Difficulty: High" in raw[1] and "=cmd()" in raw[1]
    # clone
    c2 = admin.post(f"/api/orgs/vidya/surveys/{s['id']}/clone/").data
    assert c2["title"].endswith("(copy)") and c2["status"] == "draft" and c2["responses"] == 0


def test_question_bank_draw_is_stable_per_respondent(school):
    org, (admin, _), (kid, _) = school
    bank = admin.post(
        "/api/orgs/vidya/question-banks/",
        {
            "name": "Pool",
            "questions": [{"id": f"b{i}", "type": "rating", "text": f"Item {i}"} for i in range(6)],
        },
        format="json",
    ).data
    s = admin.post(
        "/api/orgs/vidya/surveys/",
        {
            "title": "Pulse",
            "questions": [{"id": "q1", "type": "text", "text": "Hi"}],
            "draw": {"bank": bank["id"], "n": 2},
        },
        format="json",
    ).data
    admin.patch(f"/api/orgs/vidya/surveys/{s['id']}/", {"status": "open"}, format="json")
    first = [q["id"] for q in kid.get("/api/orgs/me/surveys/").data[0]["questions"]]
    assert len(first) == 3 and first == [
        q["id"] for q in kid.get("/api/orgs/me/surveys/").data[0]["questions"]
    ]
    drawn = first[1]
    kid.post(f"/api/orgs/surveys/{s['id']}/respond/", {"answers": {drawn: 5}}, format="json")
    res = admin.get(f"/api/orgs/vidya/surveys/{s['id']}/results/").data["results"]
    assert any(q["id"] == drawn and q["avg"] == 5 for q in res)
    other_org = Organization.objects.create(name="Other", slug="other")
    from apps.orgs.models import QuestionBank

    foreign = QuestionBank.objects.create(org=other_org, name="x", questions=[])
    assert (
        admin.post(
            "/api/orgs/vidya/surveys/",
            {
                "title": "x",
                "questions": [{"type": "text", "text": "a"}],
                "draw": {"bank": foreign.id, "n": 1},
            },
            format="json",
        ).status_code
        == 400
    )


def test_public_survey_no_login_resume_and_once(school):
    org, (admin, _), _ = school
    s = admin.post(
        "/api/orgs/vidya/surveys/",
        {
            "title": "Parents",
            "questions": [{"id": "q1", "type": "nps", "text": "Recommend?", "required": True}],
            "public": True,
        },
        format="json",
    ).data
    token = Survey.objects.get(id=s["id"]).public_token
    anon = APIClient()
    assert (
        anon.get(f"/api/orgs/public-surveys/{token}/?r=abcdefabcdefabcdef").status_code == 404
    )  # not open yet
    admin.patch(f"/api/orgs/vidya/surveys/{s['id']}/", {"status": "open"}, format="json")
    assert anon.get(f"/api/orgs/public-surveys/{token}/").status_code == 400  # resume key required
    r = "a1b2c3d4e5f6a7b8c9d0"
    g = anon.get(f"/api/orgs/public-surveys/{token}/?r={r}").data
    assert g["title"] == "Parents" and g["org"] == "Vidya School"
    anon.put(f"/api/orgs/public-surveys/{token}/", {"resume": r, "answers": {"q1": 8}}, format="json")
    assert anon.get(f"/api/orgs/public-surveys/{token}/?r={r}").data["draft"] == {"q1": 8}
    assert (
        anon.post(
            f"/api/orgs/public-surveys/{token}/", {"resume": r, "answers": {"q1": 9}}, format="json"
        ).status_code
        == 201
    )
    assert (
        anon.post(
            f"/api/orgs/public-surveys/{token}/", {"resume": r, "answers": {"q1": 9}}, format="json"
        ).status_code
        == 409
    )
    assert SurveyResponse.objects.get(survey_id=s["id"]).user is None
    admin.patch(f"/api/orgs/vidya/surveys/{s['id']}/", {"public": False}, format="json")
    assert anon.get(f"/api/orgs/public-surveys/{token}/?r={r}").status_code == 404


def test_ai_survey_writer_drops_invalid_questions(school):
    _, (admin, _), (kid, _) = school
    d = admin.post(
        "/api/orgs/vidya/surveys/ai-draft/", {"prompt": "Feedback on our AI club"}, format="json"
    ).data
    assert d["title"] and [q["type"] for q in d["questions"]] == [
        "rating",
        "matrix",
        "text",
    ]  # broken 1-option choice dropped
    assert (
        kid.post(
            "/api/orgs/vidya/surveys/ai-draft/", {"prompt": "Feedback on our AI club"}, format="json"
        ).status_code
        == 403
    )


# ── Org extras ───────────────────────────────────────────────────────


def test_brand_fields_features_and_setup(school, settings):
    org, (admin, au), (kid, ku) = school
    assert (
        admin.patch(
            "/api/orgs/vidya/settings/", {"logo_url": "https://tracker.example/logo.png"}, format="json"
        ).status_code
        == 400
    )
    r = admin.patch(
        "/api/orgs/vidya/settings/",
        {
            "display_name": "Vidya",
            "brand_color": "#123abc",
            "logo_url": f"{settings.MEDIA_URL}uploads/1/logo.png",
            "member_fields": [
                {"key": "roll_no", "label": "Roll no", "type": "text"},
                {"key": "section", "label": "Section", "type": "select", "options": ["A", "B"]},
            ],
            "features": {"leaderboard": False},
        },
        format="json",
    )
    assert r.status_code == 200 and r.data["features"]["leaderboard"] is False and r.data["name"] == "Vidya"
    assert (
        kid.patch("/api/orgs/vidya/settings/", {"display_name": "hacked"}, format="json").status_code == 403
    )
    brand = kid.get("/api/orgs/me/brand/").data
    assert brand["primary"]["brand_color"] == "#123abc" and brand["disabled"] == ["leaderboard"]
    assert kid.get("/api/game/leaderboard/").data["code"] == "feature_off"
    assert admin.get("/api/game/leaderboard/").status_code == 200  # owners aren't restricted
    m = Membership.objects.get(user=ku)
    assert (
        admin.patch(
            f"/api/orgs/vidya/members/{m.id}/fields/", {"fields": {"section": "C"}}, format="json"
        ).data["code"]
        == "bad_option"
    )
    admin.patch(
        f"/api/orgs/vidya/members/{m.id}/fields/",
        {"fields": {"roll_no": "12", "section": "B"}},
        format="json",
    )
    assert [x["fields"] for x in admin.get("/api/orgs/vidya/members/?field=section:B").data] == [
        {"roll_no": "12", "section": "B"}
    ]
    steps = {s["key"]: s for s in admin.get("/api/orgs/vidya/setup/").data["steps"]}
    assert steps["brand"]["done"] and steps["fields"]["done"] and not steps["assign"]["done"]
    admin.patch("/api/orgs/vidya/setup/", {"skip": "assign"}, format="json")
    assert {s["key"]: s for s in admin.get("/api/orgs/vidya/setup/").data["steps"]}["assign"]["skipped"]
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(admin.get("/api/studio/exports/orgs/vidya/analytics.xlsx").content))
    head = [c.value for c in wb["Members"][1]]
    assert "Roll no" in head and "Section" in head


def test_campaign_quota_expiry_and_csv_invites(school, mailoutbox):
    org, (admin, _), _ = school
    c = admin.post("/api/orgs/vidya/campaigns/", {"name": "Open day", "quota": 1}, format="json").data
    token = Campaign.objects.get(id=c["id"]).token
    a, _ = client_for("a@x.in")
    b, _ = client_for("b@x.in")
    assert a.get(f"/api/orgs/campaign/{token}/").data["open"] is True
    assert a.post(f"/api/orgs/campaign/{token}/").status_code == 201
    assert b.post(f"/api/orgs/campaign/{token}/").data["code"] == "campaign_closed"  # quota 1
    c2 = admin.post(
        "/api/orgs/vidya/campaigns/",
        {"name": "Late", "quota": 10, "expires_at": (timezone.now() - timedelta(days=1)).isoformat()},
        format="json",
    ).data
    assert b.post(f"/api/orgs/campaign/{Campaign.objects.get(id=c2['id']).token}/").status_code == 410
    r = admin.post(
        f"/api/orgs/vidya/campaigns/{c['id']}/emails/",
        {"csv": "name,email\nAnu,anu@x.in\nRavi,RAVI@x.in\nkid,kid@school.in\nbad,nope"},
        format="json",
    ).data
    assert r == {"invited": 2, "skipped": 1, "emailed": True, "links": []} and len(mailoutbox) == 2


def test_referral_join_and_payout_ledger(school):
    org, (admin, au), _ = school
    ref = admin.post(
        "/api/orgs/vidya/referrals/",
        {"code": "anu100", "reward": "₹100 per student", "reward_paise": 10000},
        format="json",
    ).data
    assert ref["code"] == "ANU100"
    newbie, nu = client_for("new@x.in")
    assert newbie.post("/api/orgs/referral/anu100/").status_code == 201
    assert newbie.post("/api/orgs/referral/ANU100/").status_code == 200  # rejoin doesn't double count
    use = ReferralUse.objects.get(user=nu)
    assert use.amount_paise == 10000
    assert (
        admin.patch(
            f"/api/orgs/vidya/referral-ledger/{use.id}/", {"status": "paid"}, format="json"
        ).status_code
        == 400
    )  # approve first
    admin.patch(f"/api/orgs/vidya/referral-ledger/{use.id}/", {"status": "approved"}, format="json")
    assert admin.get("/api/orgs/vidya/referrals/").data[0]["owed_paise"] == 10000
    admin.patch(f"/api/orgs/vidya/referral-ledger/{use.id}/", {"status": "paid"}, format="json")
    assert admin.get("/api/orgs/vidya/referrals/").data[0]["paid_paise"] == 10000


def test_shared_notes_library(school):
    from apps.docs.models import Document
    from apps.orgs.extras import viewable_documents

    org, (admin, au), (kid, ku) = school
    doc = Document.objects.create(owner=au, title="Physics notes")
    mine_only = Document.objects.create(owner=au, title="Private")
    stranger_doc = Document.objects.create(owner=User.objects.create_user("s@x.in", PW), title="Theirs")
    assert (
        admin.post("/api/orgs/vidya/documents/", {"document_id": stranger_doc.id}, format="json").status_code
        == 404
    )
    admin.post("/api/orgs/vidya/documents/", {"document_id": doc.id}, format="json")
    assert [d["title"] for d in kid.get("/api/orgs/me/documents/").data] == ["Physics notes"]
    assert set(viewable_documents(ku)) == {doc} and mine_only not in viewable_documents(ku)


# ── Billing ──────────────────────────────────────────────────────────


def test_promo_quote_rules(keys):
    c, u = client_for("p@x.in")
    PromoCode.objects.create(code="DIWALI50", kind="percent", value=50)
    PromoCode.objects.create(
        code="OLD", kind="percent", value=10, expires_at=timezone.now() - timedelta(days=1)
    )
    PromoCode.objects.create(code="YEARONLY", kind="fixed", value=5000, plans=["plus_year"])
    plan = Plan.objects.get(code="plus_month")
    q = c.post("/api/billing/quote/", {"plan": "plus_month", "promo": "diwali50"}, format="json").data
    assert (
        q["discount_paise"] == plan.price_paise // 2
        and q["total_paise"] == plan.price_paise - plan.price_paise // 2
    )
    assert (
        c.post("/api/billing/quote/", {"plan": "plus_month", "promo": "OLD"}, format="json").data["code"]
        == "promo_invalid"
    )  # every failure looks the same (no probing)
    assert (
        c.post("/api/billing/quote/", {"plan": "plus_month", "promo": "YEARONLY"}, format="json").data["code"]
        == "promo_invalid"
    )
    assert (
        c.post("/api/billing/quote/", {"plan": "plus_month", "promo": "NOPE"}, format="json").data["code"]
        == "promo_invalid"
    )


def test_free_via_100_percent_promo_and_per_user_cap(keys):
    c, u = client_for("free@x.in")
    PromoCode.objects.create(code="SCHOLAR", kind="percent", value=100, max_uses=5)
    r = c.post("/api/billing/checkout/", {"plan": "plus_month", "promo": "SCHOLAR"}, format="json")
    assert r.status_code == 201 and r.data["free"] and current_plan(u).code == "plus_month"
    assert not Invoice.objects.exists()  # ₹0 sale → no tax invoice
    assert PromoCode.objects.get(code="SCHOLAR").uses == 1
    assert (
        c.post("/api/billing/quote/", {"plan": "plus_month", "promo": "SCHOLAR"}, format="json").data["code"]
        == "promo_invalid"
    )


def test_paid_promo_order_issues_gst_invoice(keys, gateway):
    from apps.legal.models import SiteInfo

    SiteInfo.objects.update_or_create(
        pk=1,
        defaults={"legal_name": "Aasan Learning Pvt Ltd", "gstin": "33ABCDE1234F1Z5", "state": "Tamil Nadu"},
    )
    calls, _ = gateway
    PromoCode.objects.create(code="TEN", kind="percent", value=10)
    c, u = client_for("buyer@x.in")
    plan = Plan.objects.get(code="plus_month")
    r = c.post(
        "/api/billing/checkout/",
        {"plan": "plus_month", "promo": "TEN", "buyer_state": "Karnataka", "buyer_gstin": "29ABCDE1234F1Z5"},
        format="json",
    )
    total = plan.price_paise - plan.price_paise // 10
    assert r.status_code == 201 and calls["orders"][-1]["amount"] == total
    oid, pid = r.data["order_id"], "pay_77"
    v = c.post(
        "/api/billing/verify/",
        {"razorpay_order_id": oid, "razorpay_payment_id": pid, "razorpay_signature": sign(f"{oid}|{pid}")},
        format="json",
    )
    assert v.status_code == 200
    inv = Invoice.objects.get(order__rp_order_id=oid)
    assert (
        inv.igst_paise > 0 and inv.cgst_paise == 0 and inv.taxable_paise + inv.igst_paise == total
    )  # inter-state → IGST
    assert inv.number.endswith("/00001") and inv.lines[0]["discount_paise"] == plan.price_paise // 10
    pdf = c.get(f"/api/billing/invoices/{inv.number.replace('/', '_')}.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    other, _ = client_for("other@x.in")
    assert other.get(f"/api/billing/invoices/{inv.number.replace('/', '_')}.pdf").status_code == 404
    assert (
        c.post("/api/billing/checkout/", {"plan": "plus_month", "buyer_gstin": "BAD"}, format="json").data[
            "code"
        ]
        == "bad_gst_details"
    )
    from apps.billing.invoices import split_gst

    same = split_gst(11800, intra_state=True)
    assert same == {"taxable_paise": 10000, "cgst_paise": 900, "sgst_paise": 900, "igst_paise": 0}


def test_org_seat_purchase_assigns_seats(keys, gateway, school):
    org, (admin, au), (kid, ku) = school
    late, lu = client_for("late@x.in")
    r = admin.post(
        "/api/billing/checkout/", {"plan": "plus_month", "org": "vidya", "seats": 1}, format="json"
    )
    assert (
        kid.post(
            "/api/billing/checkout/", {"plan": "plus_month", "org": "vidya", "seats": 1}, format="json"
        ).status_code
        == 403
    )
    oid, pid = r.data["order_id"], "pay_org"
    admin.post(
        "/api/billing/verify/",
        {"razorpay_order_id": oid, "razorpay_payment_id": pid, "razorpay_signature": sign(f"{oid}|{pid}")},
        format="json",
    )
    sub = OrgSubscription.objects.get(org=org)
    assert sub.seats == 1 and Membership.objects.get(user=ku).seat and current_plan(ku).code == "plus_month"
    Membership.objects.create(org=org, user=lu, role="learner")
    assert current_plan(lu).code == "free"  # no free seat left
    st = admin.get("/api/billing/orgs/vidya/").data
    assert st["seats_total"] == 1 and st["seats_used"] == 1 and st["orders"][0]["invoice"]
    m_late = Membership.objects.get(user=lu)
    assert (
        admin.post(
            "/api/billing/orgs/vidya/", {"membership_id": m_late.id, "seat": True}, format="json"
        ).data["code"]
        == "no_free_seats"
    )
    admin.post(
        "/api/billing/orgs/vidya/",
        {"membership_id": Membership.objects.get(user=ku).id, "seat": False},
        format="json",
    )
    admin.post("/api/billing/orgs/vidya/", {"membership_id": m_late.id, "seat": True}, format="json")
    assert current_plan(lu).code == "plus_month" and current_plan(ku).code == "free"


def test_redeem_codes_batch_redeem_and_bruteforce_guard(school):
    org, (admin, _), (kid, ku) = school
    staff, _ = client_for("ops@aasan.in", staff=True)
    assert (
        staff.post(
            "/api/admin/redeem-codes/",
            {"plan": "plus_month", "days": 60, "count": 3, "batch": "Vidya term 1", "org": "vidya"},
            format="json",
        ).data["created"]
        == 3
    )
    codes = list(RedeemCode.objects.values_list("code", flat=True))
    assert len(admin.get("/api/billing/orgs/vidya/redeem-codes/").data) == 3
    assert admin.get("/api/billing/orgs/vidya/redeem-codes/?export=csv")["Content-Type"].startswith(
        "text/csv"
    )
    newbie, nu = client_for("n@x.in")
    r = newbie.post("/api/billing/redeem/", {"code": codes[0].replace("-", "").lower()}, format="json").data
    assert (
        r["plan"]
        and r["org"] == "vidya"
        and current_plan(nu).code == "plus_month"
        and Membership.objects.filter(user=nu, org=org).exists()
    )
    assert newbie.post("/api/billing/redeem/", {"code": codes[0]}, format="json").data["code"] == "code_used"
    guess, _ = client_for("guess@x.in")
    for _ in range(10):
        guess.post("/api/billing/redeem/", {"code": "AAAA-BBBB-CCCC"}, format="json")
    assert guess.post("/api/billing/redeem/", {"code": codes[1]}, format="json").status_code == 429
    assert kid.get("/api/admin/redeem-codes/").status_code == 403


def test_admin_promos_crud(school):
    staff, _ = client_for("ops2@aasan.in", staff=True)
    p = staff.post(
        "/api/admin/promos/",
        {"code": "school-2026", "kind": "percent", "value": 20, "plans": ["plus_year"]},
        format="json",
    )
    assert p.status_code == 201 and p.data["code"] == "SCHOOL-2026"
    assert (
        staff.post(
            "/api/admin/promos/", {"code": "X1X", "kind": "percent", "value": 150}, format="json"
        ).status_code
        == 400
    )
    assert (
        staff.post(
            "/api/admin/promos/",
            {"code": "X2X", "kind": "fixed", "value": 100, "plans": ["nope"]},
            format="json",
        ).status_code
        == 400
    )
    assert staff.delete(f"/api/admin/promos/{p.data['id']}/").status_code == 204


# ── Guardian view ────────────────────────────────────────────────────


def test_guardian_link_digest_and_revoke(mailoutbox):
    from apps.accounts.guardian import send_weekly
    from apps.game.services import award

    adult, _ = client_for("adult@x.in", age_band="adult")
    assert adult.get("/api/users/guardian/").data == {"applies": False}
    kid, ku = client_for("teen@x.in", age_band="minor", guardian_email="amma@x.in")
    award(ku, "lesson_complete", ref="1")
    assert kid.get("/api/users/guardian/").data["email"] == "amma@x.in"
    assert kid.post("/api/users/guardian/", {"action": "send"}, format="json").status_code == 200
    assert len(mailoutbox) == 1 and "/guardian/" in mailoutbox[0].body and mailoutbox[0].to == ["amma@x.in"]
    assert (
        kid.post("/api/users/guardian/", {"action": "send"}, format="json").status_code == 429
    )  # once an hour
    token = mailoutbox[0].body.split("/guardian/")[1].split()[0]
    anon = APIClient()
    v = anon.get(f"/api/guardian/{token}/").data
    assert v["streak"] == 1 and "lessons" in v and "answers" not in str(v)
    assert (
        anon.post(f"/api/guardian/{token}/stop/").data["ok"]
        and not User.objects.get(id=ku.id).guardian_digest
    )
    kid.post("/api/users/guardian/", {"action": "revoke"}, format="json")
    assert anon.get(f"/api/guardian/{token}/").status_code == 404
    kid.patch("/api/users/guardian/", {"digest": True}, format="json")
    sunday = timezone.now() + timedelta(days=(6 - timezone.localdate().weekday()) % 7)
    assert send_weekly(sunday) == 1 and send_weekly(sunday) == 0  # once per week
    assert send_weekly(sunday - timedelta(days=1)) == 0  # only Sundays
