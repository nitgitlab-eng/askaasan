"""Public workshops (M3): staff scheduling, free and paid seats (Razorpay test doubles), announce, reminders, status
lifecycle, join window and retention."""

import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.models import Invoice, Order
from apps.game.models import Notification
from apps.workshops import public, services, tasks
from apps.workshops.content import seed
from apps.workshops.models import (
    Workshop,
    WorkshopEnrollment,
    WorkshopEvent,
    WorkshopRun,
    WorkshopSession,
    WorkshopTurn,
)

pytestmark = pytest.mark.django_db
SECRET, HOOK = "test_secret_abc123", "whsec_xyz789"
ADMIN = "/api/admin/workshops/runs/"


@pytest.fixture(autouse=True)
def _seeded(db, settings):
    seed()
    settings.ADMINS = [("Ops", "ops@example.com")]


def _client(email, staff=False, verified=True):
    u = User.objects.create_user(email, "Work#2026passwd", is_staff=staff, email_verified=verified)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


@pytest.fixture
def staff():
    return _client("staff@example.com", staff=True)[0]


def _future(**kw):
    return (timezone.now() + timedelta(**(kw or {"days": 2}))).isoformat()


def _run(status="scheduled", starts_in=timedelta(days=2), **kw):
    return WorkshopRun.objects.create(
        workshop=Workshop.objects.get(slug=kw.pop("slug", "quick-check")),
        audience="public",
        starts_at=timezone.now() + starts_in,
        status=status,
        **kw,
    )


def _sign(msg, secret=SECRET):
    return hmac.new(
        secret.encode(), msg if isinstance(msg, bytes) else msg.encode(), hashlib.sha256
    ).hexdigest()


def _verify(c, oid, pid="pay_1"):
    return c.post(
        "/api/billing/verify/",
        {"razorpay_order_id": oid, "razorpay_payment_id": pid, "razorpay_signature": _sign(f"{oid}|{pid}")},
        format="json",
    )


def _webhook(oid, amount, pid="pay_w", event="payment.captured"):
    body = json.dumps(
        {"event": event, "payload": {"payment": {"entity": {"id": pid, "order_id": oid, "amount": amount}}}}
    ).encode()
    return APIClient().post(
        "/api/billing/webhook/",
        body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=_sign(body, HOOK),
    )


# ── Admin auth and validation ────────────────────────────────────────


def test_admin_endpoints_are_staff_only():
    run = _run()
    learner, _ = _client("learner@example.com")
    anon = APIClient()
    for method, url in (
        ("get", ADMIN),
        ("post", ADMIN),
        ("get", f"{ADMIN}{run.id}/"),
        ("patch", f"{ADMIN}{run.id}/"),
        ("post", f"{ADMIN}{run.id}/publish/"),
        ("post", f"{ADMIN}{run.id}/announce/"),
        ("post", f"{ADMIN}{run.id}/cancel/"),
        ("get", f"{ADMIN}{run.id}/stats/"),
    ):
        assert getattr(learner, method)(url, {}, format="json").status_code == 403, url
        assert getattr(anon, method)(url, {}, format="json").status_code == 401, url
    run.refresh_from_db()
    assert run.status == "scheduled" and run.announced_at is None


@pytest.mark.parametrize(
    "patch,code",
    [
        ({"workshop_slug": "nope"}, "bad_workshop"),
        ({"starts_at": "2020-01-01T10:00:00+05:30"}, "bad_starts_at"),
        ({"starts_at": "2099-01-01T10:00:00"}, "bad_starts_at"),  # no zone
        ({"starts_at": "tomorrow"}, "bad_starts_at"),
        ({"capacity": 5001}, "bad_capacity"),
        ({"capacity": -1}, "bad_capacity"),
        ({"price_paise": 50}, "bad_price"),
        ({"price_paise": 10_00_001}, "bad_price"),
        ({"price_paise": "12.5"}, "bad_price"),
        ({"proctoring": "camera"}, "bad_proctoring"),
        ({"late_join_minutes": 61}, "bad_late_join"),
        ({"lobby_opens_minutes": 4}, "bad_lobby_opens"),
    ],
)
def test_create_validation(staff, patch, code):
    body = {"workshop_slug": "quick-check", "starts_at": _future(), **patch}
    res = staff.post(ADMIN, body, format="json")
    assert res.status_code == 400 and res.data["code"] == code
    assert not WorkshopRun.objects.exists()


def test_create_draft_then_publish(staff):
    res = staff.post(
        ADMIN,
        {
            "workshop_slug": "quick-check",
            "starts_at": _future(),
            "capacity": 0,
            "price_paise": 0,
            "proctoring": "activity",
            "late_join_minutes": 10,
            "lobby_opens_minutes": 20,
        },
        format="json",
    )
    assert res.status_code == 201, res.data
    body = res.data
    assert body["status"] == "draft" and body["audience"] == "public" and body["capacity"] == 0
    assert body["seats_left"] is None and body["enrolled"] == 0 and body["announced_at"] is None
    run = WorkshopRun.objects.get(pk=body["id"])
    assert run.capacity is None and run.lobby_opens_minutes == 20

    learner, _ = _client("learner@example.com")
    assert body["id"] not in {r["id"] for r in learner.get("/api/workshops/runs/").data}  # drafts stay hidden
    assert learner.get(f"/api/workshops/runs/{run.id}/").status_code == 404

    assert staff.post(f"{ADMIN}{run.id}/publish/").data["status"] == "scheduled"
    assert staff.post(f"{ADMIN}{run.id}/publish/").status_code == 200  # idempotent
    assert run.id in {r["id"] for r in learner.get("/api/workshops/runs/").data}
    assert [r["id"] for r in staff.get(f"{ADMIN}?status=scheduled").data] == [run.id]
    assert staff.get(f"{ADMIN}?status=draft").data == []


def test_publish_refuses_a_past_start(staff):
    run = _run(status="draft", starts_in=timedelta(minutes=-5))
    assert staff.post(f"{ADMIN}{run.id}/publish/").data["code"] == "starts_in_past"


def test_edit_price_locked_once_enrolled_and_move_notifies(staff):
    run = _run(price_paise=0)
    learner, u = _client("learner@example.com")
    assert learner.post(f"/api/workshops/runs/{run.id}/enroll/").data == {"enrolled": True}
    res = staff.patch(f"{ADMIN}{run.id}/", {"price_paise": 9900}, format="json")
    assert res.status_code == 409 and res.data["code"] == "price_locked"
    assert staff.patch(f"{ADMIN}{run.id}/", {"capacity": 0}, format="json").status_code == 200
    WorkshopEnrollment.objects.filter(run=run).update(reminded_24h=True)
    new = (timezone.now() + timedelta(days=3)).replace(microsecond=0)
    res = staff.patch(f"{ADMIN}{run.id}/", {"starts_at": new.isoformat()}, format="json")
    assert res.status_code == 200
    run.refresh_from_db()
    assert run.starts_at == new
    n = Notification.objects.get(user=u, kind="workshop")
    assert n.title.startswith("New time") and n.link == f"/workshops/{run.id}"
    assert not WorkshopEnrollment.objects.get(run=run).reminded_24h  # reminders go again for the new time
    assert any("New time" in m.subject for m in mail.outbox)


def test_price_editable_before_any_sale(staff):
    run = _run()
    res = staff.patch(f"{ADMIN}{run.id}/", {"price_paise": 19900}, format="json")
    assert res.status_code == 200 and res.data["price_paise"] == 19900


# ── Announce ─────────────────────────────────────────────────────────


def test_announce_batches_once_and_respects_email_prefs(staff, monkeypatch):
    monkeypatch.setattr(tasks, "ANNOUNCE_BATCH", 2)  # 5 users → 3 chained batches
    _client("a@example.com")
    _, b = _client("b@example.com")
    _client("c@example.com", verified=False)
    _, gone = _client("gone@example.com")
    gone.is_active = False
    gone.save()
    prefs = b.preferences
    prefs.data = {**prefs.data, "notifications": {"email_workshops": False}}
    prefs.save()
    draft = _run(status="draft")
    assert staff.post(f"{ADMIN}{draft.id}/announce/").data["code"] == "not_scheduled"

    run = _run()
    res = staff.post(f"{ADMIN}{run.id}/announce/")
    assert res.status_code == 200 and res.data["already_announced"] is False and res.data["announced_at"]
    told = set(Notification.objects.filter(kind="workshop_announce").values_list("user__email", flat=True))
    assert told == {"staff@example.com", "a@example.com", "b@example.com", "c@example.com"}
    emailed = {m.to[0] for m in mail.outbox}
    assert emailed == {"staff@example.com", "a@example.com"}  # b opted out, c unverified, gone inactive
    assert all(f"/workshops/{run.id}" in m.body and "Unsubscribe" in m.body for m in mail.outbox)

    again = staff.post(f"{ADMIN}{run.id}/announce/")
    assert again.status_code == 200 and again.data["already_announced"] is True
    assert Notification.objects.filter(kind="workshop_announce").count() == 4
    # A retried batch skips users it already told.
    assert tasks.announce_run(run.id) == 0


# ── Cancel and stats ─────────────────────────────────────────────────


def test_cancel_notifies_and_flags_paid_seats_for_refund(
    staff, keys, gateway, django_capture_on_commit_callbacks
):
    run = _run(price_paise=49900)
    learner, u = _client("learner@example.com")
    oid = learner.post(f"/api/workshops/runs/{run.id}/checkout/", {}, format="json").data["order_id"]
    assert _verify(learner, oid).status_code == 200
    free_run = _run()
    _, v = _client("free@example.com")
    WorkshopEnrollment.objects.create(run=free_run, user=v)
    mail.outbox.clear()

    with django_capture_on_commit_callbacks(execute=True):
        res = staff.post(f"{ADMIN}{run.id}/cancel/")
    assert res.status_code == 200 and res.data["status"] == "cancelled" and res.data["refunds_due"] == 1
    assert WorkshopEnrollment.objects.get(run=run).refund_due
    staff_mail = [m for m in mail.outbox if "ops@example.com" in m.to]
    assert staff_mail and oid in staff_mail[0].body
    n = Notification.objects.get(user=u, kind="workshop")
    assert n.title.startswith("Cancelled") and "refunded" in n.body
    # Learners keep seeing the cancelled run they held a seat on; enrolment and checkout are closed.
    row = next(r for r in learner.get("/api/workshops/runs/").data if r["id"] == run.id)
    assert row["status"] == "cancelled" and row["my_status"] == "enrolled"
    other, _ = _client("late@example.com")
    assert run.id not in {r["id"] for r in other.get("/api/workshops/runs/").data}
    res = other.post(f"/api/workshops/runs/{run.id}/checkout/", {}, format="json")
    assert res.status_code == 404  # not visible to someone without a seat
    res = learner.post(f"/api/workshops/runs/{run.id}/checkout/", {}, format="json")
    assert res.status_code == 409 and res.data["code"] == "run_cancelled"
    assert staff.post(f"{ADMIN}{run.id}/cancel/").data["refunds_due"] == 0  # idempotent
    assert staff.patch(f"{ADMIN}{run.id}/", {"capacity": 5}, format="json").data["code"] == "not_editable"


def test_stats_are_aggregate_only(staff):
    run = _run(starts_in=timedelta(minutes=-5))
    users = [_client(f"l{i}@example.com")[1] for i in range(3)]
    t0 = timezone.now() - timedelta(minutes=40)
    for i, u in enumerate(users):
        e = WorkshopEnrollment.objects.create(run=run, user=u)
        if i == 2:
            continue  # enrolled, never joined
        s = WorkshopSession.objects.create(enrollment=e, user=u, run=run, started_at=t0)
        if i == 0:
            s.status, s.ended_at, s.final_score, s.passed = "submitted", t0 + timedelta(minutes=30), 0.8, True
            s.save()
        WorkshopEvent.objects.create(session=s, type="help_error", data={"summary": "x"})
    res = staff.get(f"{ADMIN}{run.id}/stats/")
    assert res.status_code == 200
    assert res.data == {
        "id": run.id,
        "status": "live",
        "enrolled": 3,
        "joined": 2,
        "started": 2,
        "finished": 1,
        "passed": 1,
        "avg_score": 0.8,
        "avg_minutes": 30.0,
        "help_requests": 2,
    }
    blob = json.dumps(res.data, default=str)
    assert not any(u.email in blob for u in users)
    listed = next(r for r in staff.get(ADMIN).data if r["id"] == run.id)
    assert listed["enrolled"] == 3 and listed["sessions_started"] == 2 and listed["sessions_passed"] == 1
    # Test runs and unknown ids are not public runs.
    test = WorkshopRun.objects.create(workshop=run.workshop, audience="test", starts_at=timezone.now())
    assert staff.get(f"{ADMIN}{test.id}/stats/").status_code == 404


# ── Free enrolment and the join window ───────────────────────────────


def test_free_enrol_capacity_and_detail():
    run = _run(capacity=1, proctoring="activity")
    a, _ = _client("a@example.com")
    b, _ = _client("b@example.com")
    detail = a.get(f"/api/workshops/runs/{run.id}/").data
    assert detail["my_status"] == "none" and detail["seats_left"] == 1 and detail["price_paise"] == 0
    agenda = detail["agenda"]
    assert agenda and set(agenda[0]) == {
        "title",
        "kind",
        "minutes",
    }  # outline only: no material or answer keys
    assert "final" not in detail and detail["prerequisites"] and "tab_visibility" in detail["tracked"]
    assert {"lobby_opens_at", "join_opens_at", "join_closes_at", "ends_at"} <= set(detail)
    assert a.post(f"/api/workshops/runs/{run.id}/enroll/").data == {"enrolled": True}
    res = b.post(f"/api/workshops/runs/{run.id}/enroll/")
    assert res.status_code == 409 and res.data["code"] == "run_full"
    row = next(r for r in a.get("/api/workshops/runs/").data if r["id"] == run.id)
    assert row["my_status"] == "enrolled" and row["seats_left"] == 0


def test_enrolment_closes_with_the_join_window(keys, gateway):
    run = _run(starts_in=timedelta(minutes=-16))  # late join is 15 min
    paid = _run(starts_in=timedelta(minutes=-16), price_paise=9900)
    c, _ = _client("a@example.com")
    assert c.post(f"/api/workshops/runs/{run.id}/enroll/").data["code"] == "too_late"
    assert c.post(f"/api/workshops/runs/{paid.id}/checkout/", {}, format="json").data["code"] == "too_late"
    assert not gateway[0]["orders"]


# ── Paid seats ───────────────────────────────────────────────────────


def test_paid_checkout_grants_on_verify_only_once(keys, gateway):
    run = _run(price_paise=49900)
    c, u = _client("a@example.com")
    assert c.post(f"/api/workshops/runs/{run.id}/enroll/").status_code == 402
    res = c.post(
        f"/api/workshops/runs/{run.id}/checkout/", {"amount": 100, "price_paise": 100}, format="json"
    )
    assert res.status_code == 201, res.data
    assert set(res.data) == {
        "order_id",
        "amount",
        "currency",
        "key_id",
        "name",
        "description",
        "mode",
        "prefill",
    }
    assert res.data["amount"] == 49900 and gateway[0]["orders"][-1]["amount"] == 49900  # the server's price
    assert res.data["description"].startswith("Workshop: ")
    oid = res.data["order_id"]
    assert not WorkshopEnrollment.objects.filter(user=u).exists()  # nothing before a verified capture

    bad = c.post(
        "/api/billing/verify/",
        {"razorpay_order_id": oid, "razorpay_payment_id": "pay_1", "razorpay_signature": _sign("x", "wrong")},
        format="json",
    )
    assert bad.status_code == 400 and not WorkshopEnrollment.objects.filter(user=u).exists()

    ok = _verify(c, oid)
    assert ok.status_code == 200 and ok.data["workshop_run"] == run.id and ok.data["plan"] is None
    assert _verify(c, oid).status_code == 200  # a second callback is a no-op
    assert _webhook(oid, 49900).status_code == 200
    e = WorkshopEnrollment.objects.get(user=u, run=run)
    order = Order.objects.get(rp_order_id=oid)
    assert e.order == order and order.status == "paid" and order.plan is None
    inv = Invoice.objects.get(order=order)
    assert (
        inv.lines[0]["description"].startswith(f"Workshop: {run.workshop.title}, ")
        and inv.total_paise == 49900
    )
    assert any("payment received" in m.subject.lower() for m in mail.outbox)
    hist = c.get("/api/billing/history/").data[0]
    assert hist["plan"].startswith("Workshop: ") and hist["workshop_run"] == run.id
    assert c.get("/api/admin/payments/orders/").status_code == 403
    again = c.post(f"/api/workshops/runs/{run.id}/checkout/", {}, format="json")
    assert again.status_code == 409 and again.data["code"] == "already_enrolled"


def test_paid_seat_granted_by_webhook_alone(keys, gateway):
    run = _run(price_paise=9900)
    c, u = _client("a@example.com")
    oid = c.post(f"/api/workshops/runs/{run.id}/checkout/", {}, format="json").data["order_id"]
    assert _webhook(oid, 100).status_code == 200  # wrong amount: ignored
    assert not WorkshopEnrollment.objects.filter(user=u).exists()
    assert _webhook(oid, 9900, event="order.paid").status_code == 200
    assert _webhook(oid, 9900, pid="pay_other").status_code == 200
    assert WorkshopEnrollment.objects.filter(user=u, run=run).count() == 1


def test_capacity_rechecked_at_grant(keys, gateway, django_capture_on_commit_callbacks):
    run = _run(price_paise=9900, capacity=1)
    a, ua = _client("a@example.com")
    oid = a.post(f"/api/workshops/runs/{run.id}/checkout/", {}, format="json").data["order_id"]
    _, ub = _client("b@example.com")
    WorkshopEnrollment.objects.create(run=run, user=ub)  # the last seat went while a was paying
    with django_capture_on_commit_callbacks(execute=True):
        res = _verify(a, oid)
    assert res.status_code == 409 and res.data["code"] == "run_full"
    order = Order.objects.get(rp_order_id=oid)
    assert order.status == "paid" and order.error == "run_full"
    assert not WorkshopEnrollment.objects.filter(user=ua).exists()
    assert not Invoice.objects.filter(order=order).exists()
    assert any("ops@example.com" in m.to and oid in m.body for m in mail.outbox)
    with django_capture_on_commit_callbacks(execute=True):
        assert _verify(a, oid).data["code"] == "run_full"  # stable on retry
    assert Notification.objects.filter(user=ua, kind="workshop").count() == 1  # told once: refund coming
    assert sum("ops@example.com" in m.to for m in mail.outbox) == 1  # staff alerted once
    full = a.post(f"/api/workshops/runs/{run.id}/checkout/", {}, format="json")
    assert full.status_code == 409 and full.data["code"] == "run_full"


def test_checkout_refusals(keys, gateway):
    c, _ = _client("a@example.com")
    free = _run()
    assert c.post(f"/api/workshops/runs/{free.id}/checkout/", {}, format="json").data["code"] == "not_paid"
    paid = _run(price_paise=9900)
    res = c.post(f"/api/workshops/runs/{paid.id}/checkout/", {"promo": "HALF"}, format="json")
    assert res.status_code == 400 and res.data["code"] == "promo_invalid"
    draft = _run(status="draft", price_paise=9900)
    assert c.post(f"/api/workshops/runs/{draft.id}/checkout/", {}, format="json").status_code == 404
    assert not gateway[0]["orders"]


def test_pending_payment_shows_as_paid_pending(keys, gateway):
    run = _run(price_paise=9900)
    c, _ = _client("a@example.com")
    oid = c.post(f"/api/workshops/runs/{run.id}/checkout/", {}, format="json").data["order_id"]
    row = next(r for r in c.get("/api/workshops/runs/").data if r["id"] == run.id)
    assert row["my_status"] == "none"  # an opened checkout alone is not a payment
    gateway[1]["status"] = "created"
    assert _verify(c, oid).data["code"] == "payment_not_captured"
    row = next(r for r in c.get("/api/workshops/runs/").data if r["id"] == run.id)
    assert row["my_status"] == "paid_pending"


# ── Reminders, status, retention ─────────────────────────────────────


def test_reminders_go_once_each(monkeypatch):
    t0 = timezone.now().replace(microsecond=0)
    run = _run(starts_in=timedelta(days=2))
    run.starts_at = t0 + timedelta(hours=30)
    run.save()
    _, u = _client("a@example.com")
    WorkshopEnrollment.objects.create(run=run, user=u)
    clock = {"t": t0}
    monkeypatch.setattr(services, "now", lambda: clock["t"])

    assert tasks.send_reminders() == {"24h": 0, "15m": 0}
    clock["t"] = t0 + timedelta(hours=7)  # 23 h before
    assert tasks.send_reminders() == {"24h": 1, "15m": 0}
    assert tasks.send_reminders() == {"24h": 0, "15m": 0}
    clock["t"] = run.starts_at - timedelta(minutes=10)
    assert tasks.send_reminders() == {"24h": 0, "15m": 1}
    assert tasks.send_reminders() == {"24h": 0, "15m": 0}
    titles = list(Notification.objects.filter(user=u, kind="workshop").values_list("title", flat=True))
    assert len(titles) == 2 and any(t.startswith("Starting soon") for t in titles)
    # Enrolled 10 minutes before: only the 15-minute one.
    _, v = _client("b@example.com")
    WorkshopEnrollment.objects.create(run=run, user=v)
    assert tasks.send_reminders() == {"24h": 0, "15m": 1}
    # Cancelled runs get none.
    _, w = _client("c@example.com")
    WorkshopEnrollment.objects.create(run=run, user=w)
    WorkshopRun.objects.filter(pk=run.pk).update(status="cancelled")
    assert tasks.send_reminders() == {"24h": 0, "15m": 0}


def test_status_transitions_computed_and_synced(monkeypatch):
    run = _run(starts_in=timedelta(hours=1))
    w = run.workshop
    assert run.effective_status(timezone.now()) == "scheduled"
    at_start = run.starts_at + timedelta(seconds=1)
    assert run.effective_status(at_start) == "live"
    end = run.starts_at + timedelta(minutes=w.duration_minutes + w.grace_minutes, hours=12)
    assert run.ends_at == end and run.effective_status(end) == "ended"
    draft = _run(status="draft", starts_in=timedelta(hours=-1))
    assert draft.effective_status(timezone.now()) == "draft"

    monkeypatch.setattr(services, "now", lambda: at_start)
    assert tasks.sync_run_status() == {"live": 1, "ended": 0}
    run.refresh_from_db()
    assert run.status == "live"
    monkeypatch.setattr(services, "now", lambda: end)
    assert tasks.sync_run_status() == {"live": 0, "ended": 1}
    run.refresh_from_db()
    assert run.status == "ended"
    draft.refresh_from_db()
    assert draft.status == "draft"


def test_session_continues_after_the_run_ends():
    run = _run(starts_in=timedelta(minutes=-5))
    c, u = _client("a@example.com")
    c.post(f"/api/workshops/runs/{run.id}/enroll/")
    s = c.post(f"/api/workshops/runs/{run.id}/session/").data
    WorkshopRun.objects.filter(pk=run.pk).update(status="ended")
    assert c.post(f"/api/workshops/runs/{run.id}/session/").data["id"] == s["id"]
    assert c.get(f"/api/workshops/sessions/{s['id']}/").status_code == 200


def test_retention_cleanup_keeps_90_days():
    run = _run(starts_in=timedelta(minutes=-5))
    _, u = _client("a@example.com")
    e = WorkshopEnrollment.objects.create(run=run, user=u)
    s = WorkshopSession.objects.create(enrollment=e, user=u, run=run)
    old_ev = WorkshopEvent.objects.create(session=s, type="answer")
    new_ev = WorkshopEvent.objects.create(session=s, type="answer")
    old_turn = WorkshopTurn.objects.create(session=s, role="user", text="hi")
    WorkshopTurn.objects.create(session=s, role="user", text="hello")
    long_ago = timezone.now() - timedelta(days=91)
    WorkshopEvent.objects.filter(pk=old_ev.pk).update(created_at=long_ago)
    WorkshopTurn.objects.filter(pk=old_turn.pk).update(created_at=long_ago)
    assert tasks.clean_old_activity() == {"events": 1, "turns": 1}
    assert list(WorkshopEvent.objects.values_list("pk", flat=True)) == [new_ev.pk]
    assert WorkshopTurn.objects.count() == 1 and WorkshopSession.objects.filter(pk=s.pk).exists()


def test_timing_helper_matches_run():
    run = _run()
    t = public.timing(run)
    assert t["lobby_opens_at"] == run.starts_at - timedelta(minutes=15)
    assert t["join_closes_at"] == run.starts_at + timedelta(minutes=15)
