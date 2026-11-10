"""Public workshops (M3): run timing and status, enrolment rules, the paid-seat grant on capture, notifications to
learners and staff, and the aggregate-only stats a public run shows staff (never per-learner data)."""

import logging

from django.conf import settings
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.utils import timezone

from . import services
from .models import WorkshopEnrollment, WorkshopEvent, WorkshopRun, WorkshopSession

log = logging.getLogger(__name__)

Status = WorkshopRun.Status
PRICE_MIN, PRICE_MAX = 100, 10_00_000  # paise: ₹1 (the gateway minimum) to ₹10,000
CAPACITY_MAX = 5000
EMAIL_CATEGORY = "email_workshops"
HELP_EVENTS = ("help_screenshot", "help_error")


def run_link(run) -> str:
    return f"/workshops/{run.id}"


def when(run) -> str:
    return f"{timezone.localtime(run.starts_at):%a %d %b, %I:%M %p} IST"


def timing(run) -> dict:
    """Everything the lobby and the list need to count down. A session (with the prerequisite prep) can be opened from
    the lobby opening, so join_opens_at == lobby_opens_at; late join closes at join_closes_at."""
    opens, closes = run.join_window()
    return {"lobby_opens_at": opens, "join_opens_at": opens, "join_closes_at": closes, "ends_at": run.ends_at}


def enrol_refusal(run, user, at=None) -> str | None:
    """Why `user` can't take a seat on `run` now (checked again under the run's row lock), or None."""
    at = at or services.now()
    st = run.effective_status(at)
    if st == Status.CANCELLED:
        return "run_cancelled"
    if st in (Status.ENDED, Status.DRAFT):
        return "run_closed"
    if run.audience != WorkshopRun.Audience.TEST and at > run.join_window()[1]:
        return "too_late"  # enrolment closes with the join window
    if WorkshopEnrollment.objects.filter(run=run, user=user).exists():
        return "already_enrolled"
    if run.capacity and run.enrollments.count() >= run.capacity:
        return "run_full"
    return None


# ── Paid seats: called by billing.grant_for_order on a verified capture ──


def grant_seat(order):
    """The order is locked and just marked paid. → the WorkshopEnrollment, or None when the seat can't be given (the
    run filled up, closed or was cancelled while the learner paid, or they already hold a seat): then the order stays
    paid, `order.error` says why and staff get an email to refund it by hand."""
    run = (
        WorkshopRun.objects.select_for_update(of=("self",))
        .select_related("workshop")
        .get(pk=order.workshop_run_id)
    )
    refused = "account_deleted" if not order.user_id else enrol_refusal(run, order.user)
    if refused:
        order.error = refused
        order.save(update_fields=["error"])
        transaction.on_commit(lambda: _alert_refund([order], run, f"seat not granted ({refused})"))
        if order.user_id:
            transaction.on_commit(
                lambda: tell(
                    order.user,
                    f"We couldn't confirm your seat for {run.workshop.title}",
                    "Your payment was received, but the workshop had no seat left for you. We'll refund it in full.",
                    run,
                )
            )
        return None
    return WorkshopEnrollment.objects.create(run=run, user=order.user, order=order)


def _alert_refund(orders, run, why: str):
    lines = "\n".join(
        f"- {o.rp_order_id} (payment {o.rp_payment_id or 'n/a'}, ₹{o.amount_paise / 100:,.2f})"
        for o in orders
    )
    log.warning("workshop run %s: refund needed for %d order(s): %s", run.id, len(orders), why)
    from django.core.mail import mail_admins

    try:
        mail_admins(
            f"Refund needed: workshop {run.workshop.title}",
            f"Run #{run.id} ({when(run)}): {why}.\nRefund these from the Razorpay dashboard:\n{lines}",
            fail_silently=True,
        )
    except Exception:
        log.exception("workshop refund alert failed")


def send_receipt(order, enrollment):
    from django.core.mail import send_mail

    run = enrollment.run
    try:
        send_mail(
            f"Aasan payment received: {run.workshop.title}",
            f"Thank you! We received ₹{order.amount_paise / 100:,.2f} for {order.label}.\n"
            f"Your seat is confirmed. The workshop starts {when(run)}: "
            f"{settings.FRONTEND_URL}{run_link(run)}\n"
            f"Payment ID: {order.rp_payment_id}\nOrder ID: {order.rp_order_id}"
            + ("\n\n(This was a TEST MODE payment: no real money moved.)" if order.mode == "test" else ""),
            None,
            [order.user.email],
            fail_silently=True,
        )
    except Exception:  # never let email break a payment
        log.exception("workshop receipt email failed")


# ── Notifications ────────────────────────────────────────────────────


def tell(user, title: str, body: str, run, email: bool = True) -> None:
    """In-app always; email only when the learner's preferences allow it (with one-click unsubscribe)."""
    from apps.game.services import notify

    notify(user, "workshop", title, body, run_link(run))
    from apps.accounts.push import send as push

    push(user, "workshops", title, body, run_link(run))
    if email:
        send_email(user, title, body, run)


def send_email(user, title: str, body: str, run) -> bool:
    from apps.accounts.notify import send_optional

    if not user.email_verified:
        return False
    try:
        return send_optional(
            user, EMAIL_CATEGORY, title, f"{body}\n\nDetails: {settings.FRONTEND_URL}{run_link(run)}"
        )
    except Exception:
        log.exception("workshop email to user %s failed", user.id)
        return False


def cancel(run, by=None) -> int:
    """Cancel (run row locked by the caller). Paid seats are flagged for refund and staff get the order ids; enrolled
    learners are told by a background task. → how many paid seats need a refund."""
    from apps.billing.models import Order

    run.status = Status.CANCELLED
    run.save(update_fields=["status"])
    paid = WorkshopEnrollment.objects.filter(run=run, order__isnull=False)
    paid.update(refund_due=True)
    orders = list(Order.objects.filter(pk__in=paid.values("order_id")))
    if orders:
        transaction.on_commit(lambda: _alert_refund(orders, run, "the run was cancelled"))
    return len(orders)


# ── Staff views ──────────────────────────────────────────────────────


def with_counts(qs):
    return qs.annotate(
        n_enrolled=Count("enrollments", distinct=True),
        n_paid=Count("enrollments", filter=Q(enrollments__order__isnull=False), distinct=True),
        n_started=Count("sessions", filter=Q(sessions__started_at__isnull=False), distinct=True),
        n_passed=Count("sessions", filter=Q(sessions__passed=True), distinct=True),
    )


def admin_out(run, at=None) -> dict:
    at = at or services.now()
    w = run.workshop
    enrolled = getattr(run, "n_enrolled", None)
    if enrolled is None:
        enrolled = run.enrollments.count()
    return {
        "id": run.id,
        "workshop": {"slug": w.slug, "title": w.title, "duration_minutes": w.duration_minutes},
        "audience": run.audience,
        "starts_at": run.starts_at,
        **timing(run),
        "capacity": run.capacity or 0,
        "price_paise": run.price_paise,
        "proctoring": run.proctoring,
        "late_join_minutes": run.late_join_minutes,
        "lobby_opens_minutes": run.lobby_opens_minutes,
        "status": run.effective_status(at),
        "announced_at": run.announced_at,
        "enrolled": enrolled,
        "paid_enrolled": getattr(run, "n_paid", 0),
        "seats_left": max(0, run.capacity - enrolled) if run.capacity else None,
        "sessions_started": getattr(run, "n_started", 0),
        "sessions_passed": getattr(run, "n_passed", 0),
        "created_at": run.created_at,
    }


def stats(run) -> dict:
    """Aggregates only: a public run never exposes who did what."""
    sessions = WorkshopSession.objects.filter(run=run)
    started = sessions.filter(started_at__isnull=False)
    finished = sessions.filter(status=WorkshopSession.Status.SUBMITTED)
    score = finished.aggregate(v=Avg("final_score"))["v"]
    spans = [
        (end - start).total_seconds() / 60
        for start, end in finished.filter(started_at__isnull=False, ended_at__isnull=False).values_list(
            "started_at", "ended_at"
        )
    ]
    return {
        "enrolled": run.enrollments.count(),
        "joined": sessions.count(),
        "started": started.count(),
        "finished": finished.count(),
        "passed": sessions.filter(passed=True).count(),
        "avg_score": round(score, 3) if score is not None else None,
        "avg_minutes": round(sum(spans) / len(spans), 1) if spans else None,
        "help_requests": WorkshopEvent.objects.filter(session__run=run, type__in=HELP_EVENTS).count(),
    }
