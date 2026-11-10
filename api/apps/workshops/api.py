"""REST for AI workshops (/api/workshops/) and the staff test run (/api/admin/workshops/)."""

import base64
import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.decorators import api_view, parser_classes, permission_classes, throttle_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from apps.accounts.staff import AdminSection

from . import monitor, public, services
from .models import Workshop, WorkshopEnrollment, WorkshopRun, WorkshopSession, WorkshopTurn
from .org import institution_notice, institution_sees

log = logging.getLogger(__name__)

HELP_IMAGE_MAX = 4 * 1024 * 1024
HELP_ERROR_MAX = 4000
HELP_NOTE_MAX = 500
VISIBLE_STATUSES = (WorkshopRun.Status.SCHEDULED, WorkshopRun.Status.LIVE, WorkshopRun.Status.ENDED)


def _blocked(user):
    from apps.orgs.extras import refusal_response

    return refusal_response(user, "workshops")


def visible_runs(user):
    """Published public runs (and cancelled ones the user holds a seat on), the user's own staff test runs, and org
    (institution) runs the user is enrolled in while still a learner in one of the run's classes or cohorts."""
    from .org import in_audience_q

    pub = Q(audience=WorkshopRun.Audience.PUBLIC, workshop__is_published=True)
    mine = Q(id__in=WorkshopEnrollment.objects.filter(user=user).values("run_id"))
    mine_cancelled = Q(status=WorkshopRun.Status.CANCELLED) & mine
    org = Q(audience=WorkshopRun.Audience.ORG) & mine & in_audience_q(user)
    return WorkshopRun.objects.filter(
        pub & (Q(status__in=VISIBLE_STATUSES) | mine_cancelled)
        | Q(audience=WorkshopRun.Audience.TEST, created_by=user)
        | org & (Q(status__in=VISIBLE_STATUSES) | Q(status=WorkshopRun.Status.CANCELLED))
    ).select_related("workshop", "org")


def _run_out(run, enrollment, pending: bool = False) -> dict:
    w = run.workshop
    session = getattr(enrollment, "session", None) if enrollment else None
    opens, closes = run.join_window()
    test = run.audience == WorkshopRun.Audience.TEST
    enrolled_n = getattr(run, "n_enrolled", None)
    if enrolled_n is None and run.capacity:
        enrolled_n = run.enrollments.count()
    return {
        "id": run.id,
        "workshop": {
            "slug": w.slug,
            "title": w.title,
            "summary": w.summary,
            "level": w.level,
            "duration_minutes": w.duration_minutes,
        },
        "audience": run.audience,
        "starts_at": run.starts_at,
        "join_opens_at": opens if not test else None,
        "join_closes_at": closes if not test else None,
        "lobby_opens_at": opens if not test else None,
        "ends_at": run.ends_at if not test else None,
        "status": run.effective_status(services.now()),
        "price_paise": run.price_paise,
        "proctoring": run.effective_proctoring,
        "enrolled": enrollment is not None,
        "my_status": "enrolled" if enrollment else "paid_pending" if pending else "none",
        "seats_left": max(0, run.capacity - enrolled_n) if run.capacity else None,
        "session_id": session.id if session else None,
        "org": {"slug": run.org.slug, "name": run.org.display_name or run.org.name}
        if run.audience == WorkshopRun.Audience.ORG and run.org_id
        else None,
    }


def _pending_runs(user, run_ids) -> set:
    """Runs with a signed payment from this user that isn't captured yet (the webhook will grant the seat)."""
    from apps.billing.models import Order

    return set(
        Order.objects.filter(user=user, workshop_run_id__in=run_ids, status=Order.Status.CREATED)
        .exclude(rp_payment_id="")
        .values_list("workshop_run_id", flat=True)
    )


def _session_or_404(request, pk) -> WorkshopSession:
    s = get_object_or_404(
        WorkshopSession.objects.select_related("run__workshop", "user", "certificate"),
        pk=pk,
        user=request.user,
    )
    if s.run.audience == WorkshopRun.Audience.ORG:
        from django.http import Http404

        from .org import in_audience

        if not in_audience(
            s.run, request.user
        ):  # removed from the run's classes: the run is no longer theirs
            raise Http404
    return s


@api_view(["GET"])
def runs(request):
    if denied := _blocked(request.user):
        return denied
    from django.db.models import Count

    rows = list(
        visible_runs(request.user)
        .annotate(n_enrolled=Count("enrollments", distinct=True))
        .order_by("starts_at")
    )
    mine = {
        e.run_id: e
        for e in WorkshopEnrollment.objects.filter(user=request.user, run__in=rows).select_related("session")
    }
    pending = _pending_runs(request.user, [r.id for r in rows])
    return Response([_run_out(r, mine.get(r.id), r.id in pending) for r in rows])


def _tracked(mode: str) -> list[str]:
    """What this run records about a learner (shown before enrolling and again before the start). Never the camera."""
    out = ["answers", "steps_done", "help_requests"]
    if mode in ("activity", "strict"):
        out += ["tab_visibility", "window_focus", "idle_time"]
    if mode == "strict":
        out.append("fullscreen_exit")
    return out


@api_view(["GET"])
def run_detail(request, pk):
    if denied := _blocked(request.user):
        return denied
    run = get_object_or_404(visible_runs(request.user), pk=pk)
    enrollment = (
        WorkshopEnrollment.objects.filter(run=run, user=request.user).select_related("session").first()
    )
    w = run.workshop
    out = _run_out(run, enrollment, run.id in _pending_runs(request.user, [run.id]))
    out["workshop"].update(grace_minutes=w.grace_minutes, language=w.language, pass_mark=w.pass_mark)
    out["prerequisites"] = [
        {"key": p.get("key"), "label": p.get("label"), "how_to_md": p.get("how_to_md", "")}
        for p in w.prerequisites or []
    ]
    out["agenda"] = [  # the outline only: never stage material, questions or answer keys
        {"title": st.get("title", ""), "kind": st.get("kind", ""), "minutes": st.get("minutes", 0)}
        for st in w.agenda or []
    ]
    out["tracked"] = _tracked(run.effective_proctoring)
    out["institution_notice"] = institution_notice(
        run
    )  # org runs: what the institution sees (shown before start)
    out["institution_sees"] = institution_sees(run)
    out["certificate"] = True  # passing at pass_mark issues an Aasan certificate
    return Response(out)


@api_view(["POST"])
def enroll(request, pk):
    if denied := _blocked(request.user):
        return denied
    run = get_object_or_404(visible_runs(request.user), pk=pk)
    if WorkshopEnrollment.objects.filter(run=run, user=request.user).exists():
        return Response({"enrolled": True})
    if code := public.enrol_refusal(run, request.user):
        return Response({"code": code}, status=status.HTTP_409_CONFLICT)
    # Paid runs: POST runs/<id>/checkout/, and the seat is granted only on a verified capture.
    if run.price_paise > 0:
        return Response({"code": "payment_required"}, status=status.HTTP_402_PAYMENT_REQUIRED)
    with transaction.atomic():
        locked = WorkshopRun.objects.select_for_update(of=("self",)).select_related("workshop").get(pk=run.pk)
        if locked.price_paise > 0:
            return Response({"code": "payment_required"}, status=status.HTTP_402_PAYMENT_REQUIRED)
        code = public.enrol_refusal(locked, request.user)
        if code == "already_enrolled":
            return Response({"enrolled": True})
        if code:
            return Response({"code": code}, status=status.HTTP_409_CONFLICT)
        try:
            with transaction.atomic():
                WorkshopEnrollment.objects.create(run=locked, user=request.user)
        except IntegrityError:
            pass  # a double click: already enrolled
    return Response({"enrolled": True})


class CheckoutThrottle(UserRateThrottle):
    rate = "30/hour"


@api_view(["POST"])
@throttle_classes([CheckoutThrottle])
def checkout(request, pk):
    """A Razorpay order for a paid public run. The amount is the run's price from the database (nothing the client
    sends changes it), and the seat is granted only on a verified capture (billing verify / webhook → grant_seat).
    The response matches POST /api/billing/checkout/, so the web reuses the same Razorpay Checkout flow and verify."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.billing import razorpay as rp
    from apps.billing.invoices import GSTIN, STATES
    from apps.billing.models import Order
    from apps.billing.services import pay_config

    if denied := _blocked(request.user):
        return denied
    run = get_object_or_404(visible_runs(request.user).filter(audience=WorkshopRun.Audience.PUBLIC), pk=pk)
    if str(request.data.get("promo") or "").strip():  # promo codes are plan-scoped; not offered on workshops
        return Response({"code": "promo_invalid"}, status=status.HTTP_400_BAD_REQUEST)
    gstin = str(request.data.get("buyer_gstin") or "").strip().upper()
    state = str(request.data.get("buyer_state") or "").strip()
    if gstin and not GSTIN.match(gstin) or state and state not in STATES:
        return Response({"code": "bad_gst_details"}, status=status.HTTP_400_BAD_REQUEST)
    cfg = pay_config()
    with transaction.atomic():
        locked = WorkshopRun.objects.select_for_update(of=("self",)).select_related("workshop").get(pk=run.pk)
        if locked.price_paise <= 0:
            return Response({"code": "not_paid"}, status=status.HTTP_400_BAD_REQUEST)
        if code := public.enrol_refusal(locked, request.user):
            return Response({"code": code}, status=status.HTTP_409_CONFLICT)
        recent = Order.objects.filter(
            user=request.user, created_at__gte=timezone.now() - timedelta(hours=1)
        ).count()
        if recent >= 10:
            return Response({"code": "too_many_orders"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        if not cfg.ready:
            return Response({"code": "payments_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        amount = locked.price_paise
        try:
            ro = rp.create_order(
                cfg.keys,
                amount,
                "INR",
                receipt=f"aasan-w{locked.id}-{request.user.id}-{int(timezone.now().timestamp())}",
                notes={"user_id": str(request.user.id), "workshop_run": str(locked.id)},
            )
        except rp.RazorpayError as e:
            log.warning("razorpay order failed for workshop run %s: %s", locked.id, e)
            return Response({"code": "gateway_error"}, status=status.HTTP_502_BAD_GATEWAY)
        order = Order.objects.create(
            user=request.user,
            plan=None,
            workshop_run=locked,
            amount_paise=amount,
            list_paise=amount,
            rp_order_id=ro["id"],
            mode=cfg.mode,
            buyer_name=str(request.data.get("buyer_name") or "").strip()[:160],
            buyer_gstin=gstin,
            buyer_state=state,
        )
    profile = getattr(request.user, "profile", None)
    return Response(
        {
            "order_id": order.rp_order_id,
            "amount": order.amount_paise,
            "currency": "INR",
            "key_id": cfg.key_id,
            "name": cfg.business_name,
            "description": order.label,
            "mode": cfg.mode,
            "prefill": {"email": request.user.email, "name": getattr(profile, "display_name", "") or ""},
        },
        status=status.HTTP_201_CREATED,
    )


def _get_or_create_session(user, run) -> tuple[WorkshopSession | None, Response | None]:
    enrollment = WorkshopEnrollment.objects.filter(run=run, user=user).first()
    if not enrollment:
        return None, Response({"code": "not_enrolled"}, status=status.HTTP_403_FORBIDDEN)
    existing = WorkshopSession.objects.filter(enrollment=enrollment).first()
    if existing:  # resuming is always allowed (a dropped connection, or coming back tomorrow)
        return existing, None
    if run.status == WorkshopRun.Status.CANCELLED:
        return None, Response({"code": "run_cancelled"}, status=status.HTTP_409_CONFLICT)
    if run.audience != WorkshopRun.Audience.TEST:
        opens, closes = run.join_window()
        at = services.now()
        if at < opens:
            return None, Response({"code": "too_early", "opens_at": opens}, status=status.HTTP_409_CONFLICT)
        if at > closes:
            return None, Response({"code": "too_late", "closed_at": closes}, status=status.HTTP_409_CONFLICT)
    try:
        with transaction.atomic():
            s = WorkshopSession.objects.create(enrollment=enrollment, user=user, run=run)
    except IntegrityError:
        s = WorkshopSession.objects.get(enrollment=enrollment)
    return s, None


@api_view(["POST"])
def run_session(request, pk):
    if denied := _blocked(request.user):
        return denied
    run = get_object_or_404(visible_runs(request.user), pk=pk)
    s, err = _get_or_create_session(request.user, run)
    if err:
        return err
    return Response(services.session_out(services.load(s.id)))


@api_view(["GET"])
def session_detail(request, pk):
    if denied := _blocked(request.user):
        return denied
    return Response(services.session_out(_session_or_404(request, pk)))


class PrereqIn(serializers.Serializer):
    key = serializers.CharField(max_length=60)
    done = serializers.BooleanField()


@api_view(["POST"])
def session_prereq(request, pk):
    if denied := _blocked(request.user):
        return denied
    s = _session_or_404(request, pk)
    ser = PrereqIn(data=request.data)
    ser.is_valid(raise_exception=True)
    if not services.tick_prereq(s, ser.validated_data["key"], ser.validated_data["done"]):
        return Response({"code": "unknown_prerequisite"}, status=status.HTTP_400_BAD_REQUEST)
    monitor.publish_after_commit(s.id)
    return Response(services.session_out(s))


class StartIn(serializers.Serializer):
    proctor_notice = serializers.BooleanField()


@api_view(["POST"])
def session_start(request, pk):
    if denied := _blocked(request.user):
        return denied
    s = _session_or_404(request, pk)
    ser = StartIn(data=request.data)
    ser.is_valid(raise_exception=True)
    if not ser.validated_data["proctor_notice"]:
        return Response({"code": "proctor_notice_required"}, status=status.HTTP_400_BAD_REQUEST)
    if code := services.start(s):
        return Response({"code": code}, status=status.HTTP_409_CONFLICT)
    monitor.publish_after_commit(s.id)
    return Response(services.session_out(s))


class HelpThrottle(UserRateThrottle):
    scope = "workshop_help"

    def get_rate(self):
        return f"{settings.WORKSHOP_HELP_PER_HOUR}/hour"


def _image(upload):
    """The upload as an in-memory llm Image (real PNG/JPEG/WebP bytes only), or an error code. Never saved."""
    from llm.images import decode_data_url

    if upload.size > HELP_IMAGE_MAX:
        return None, "image_too_large"
    raw = upload.read(HELP_IMAGE_MAX + 1)
    if len(raw) > HELP_IMAGE_MAX:
        return None, "image_too_large"
    img = decode_data_url(f"data:image/x;base64,{base64.b64encode(raw).decode()}", max_bytes=HELP_IMAGE_MAX)
    return (img, None) if img else (None, "bad_image")


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def session_help(request, pk):
    """A screenshot and/or pasted error → what's wrong and the next fix. The image is held in memory for this one AI
    call only; the event keeps just the AI's ≤200-char summary."""
    if denied := _blocked(request.user):
        return denied
    s = _session_or_404(request, pk)
    throttle = HelpThrottle()
    if not throttle.allow_request(request, None):
        wait = throttle.wait()
        return Response(
            {"code": "rate_limited", "retry_after": round(wait) if wait else None},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )
    error_text = str(request.data.get("error_text") or "").strip()
    note = str(request.data.get("note") or "").strip()
    if len(error_text) > HELP_ERROR_MAX or len(note) > HELP_NOTE_MAX:
        return Response({"code": "too_long"}, status=status.HTTP_400_BAD_REQUEST)
    image = None
    if upload := request.FILES.get("image"):
        image, code = _image(upload)
        if code:
            return Response({"code": code}, status=status.HTTP_400_BAD_REQUEST)
    if not image and not error_text:
        return Response({"code": "nothing_to_check"}, status=status.HTTP_400_BAD_REQUEST)
    if reason := services.spend(s.id, services.HELP_MAX_TOKENS):
        # "budget" (this session's AI budget is used up) or "cap" (daily safety cap) — distinct from rate_limited
        return Response({"code": reason}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    try:
        out = services.help_reply(s, image, error_text, note)
    except Exception:
        log.exception("workshop help failed for session %s", s.id)
        return Response({"code": "help_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    finally:
        image = None  # drop the only reference to the screenshot
    monitor.publish_after_commit(s.id)
    return Response(out)


class FinalIn(serializers.Serializer):
    answers = serializers.DictField(
        child=serializers.IntegerField(min_value=0, max_value=20), allow_empty=True
    )
    practical = serializers.CharField(max_length=6000, allow_blank=True, trim_whitespace=True)


@api_view(["POST"])
def session_final(request, pk):
    if denied := _blocked(request.user):
        return denied
    s = _session_or_404(request, pk)
    ser = FinalIn(data=request.data)
    ser.is_valid(raise_exception=True)
    if not s.started_at:
        return Response({"code": "not_started"}, status=status.HTTP_409_CONFLICT)
    if (services.stage(s) or {}).get("kind") != "assessment":
        return Response({"code": "not_at_final"}, status=status.HTTP_409_CONFLICT)
    if s.passed or s.final_attempts >= services.FINAL_ATTEMPTS:
        return Response({"code": "no_attempts_left"}, status=status.HTTP_409_CONFLICT)
    try:
        out = services.grade_final(s, ser.validated_data["answers"], ser.validated_data["practical"])
    except Exception:
        log.exception("workshop final grading failed for session %s", s.id)
        return Response({"code": "grading_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if code := out.get("error"):  # lost a race for the last attempt
        return Response({"code": code}, status=status.HTTP_409_CONFLICT)
    monitor.publish_after_commit(s.id)
    return Response(out)


class BuildIn(serializers.Serializer):
    answer = serializers.DictField()


_BUILD_STATUS = {
    "not_started": status.HTTP_409_CONFLICT,
    "submitted": status.HTTP_409_CONFLICT,
    "not_build": status.HTTP_409_CONFLICT,
    "no_attempts_left": status.HTTP_409_CONFLICT,
    "bad_answer": status.HTTP_400_BAD_REQUEST,
    "empty": status.HTTP_400_BAD_REQUEST,
    "budget": status.HTTP_429_TOO_MANY_REQUESTS,
    "cap": status.HTTP_429_TOO_MANY_REQUESTS,
}


@api_view(["POST"])
def session_build(request, pk):
    """Hand in the current `build` stage's task (code, open_input or artifact_check), graded on the server with the
    lesson activity graders. → {score, passed, feedback, reveal, best_score, attempts_left, session}."""
    if denied := _blocked(request.user):
        return denied
    s = _session_or_404(request, pk)
    ser = BuildIn(data=request.data)
    ser.is_valid(raise_exception=True)
    try:
        out = services.grade_build(s.id, ser.validated_data["answer"])
    except Exception:
        log.exception("workshop build grading failed for session %s", s.id)
        return Response({"code": "grading_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if code := out.get("error"):
        return Response({"code": code}, status=_BUILD_STATUS.get(code, status.HTTP_400_BAD_REQUEST))
    monitor.publish_after_commit(s.id)
    return Response({**out, "session": services.session_out(services.load(s.id))})


# ── Agent builder (M2) ───────────────────────────────────────────────

_AGENT_STATUS = {
    "external_off": status.HTTP_403_FORBIDDEN,
    "too_many_servers": status.HTTP_409_CONFLICT,
    "runs_exhausted": status.HTTP_429_TOO_MANY_REQUESTS,
    "rate_limited": status.HTTP_429_TOO_MANY_REQUESTS,
    "no_pending": status.HTTP_409_CONFLICT,
    "unreachable": status.HTTP_502_BAD_GATEWAY,
    "timeout": status.HTTP_502_BAD_GATEWAY,
    "not_mcp": status.HTTP_502_BAD_GATEWAY,
    "auth_failed": status.HTTP_502_BAD_GATEWAY,
}


def _agent_session(request, pk, write: bool = True):
    """→ (session, None) for the owner of a started session in a workshop with an agent builder, else (None, error)."""
    from .agent import has_builder

    if denied := _blocked(request.user):
        return None, denied
    s = _session_or_404(request, pk)
    if not has_builder(s.run.workshop):
        return None, Response({"code": "no_agent_builder"}, status=status.HTTP_404_NOT_FOUND)
    if not s.started_at:
        return None, Response({"code": "not_started"}, status=status.HTTP_409_CONFLICT)
    if write and s.status == WorkshopSession.Status.SUBMITTED:
        return None, Response({"code": "session_submitted"}, status=status.HTTP_409_CONFLICT)
    return s, None


def _refused(e) -> Response:
    return Response({"code": e.code}, status=_AGENT_STATUS.get(e.code, status.HTTP_400_BAD_REQUEST))


@api_view(["GET", "PUT"])
def session_agent(request, pk):
    from . import agent

    s, err = _agent_session(request, pk, write=request.method == "PUT")
    if err:
        return err
    if request.method == "PUT":
        if not isinstance(request.data, dict):
            return Response({"code": "bad_request"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            agent.save(s, request.data)
        except agent.AgentRefused as e:
            return _refused(e)
    return Response(agent.agent_out(services.load(s.id)))


class ServerIn(serializers.Serializer):
    url = serializers.CharField(max_length=500)
    label = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    token = serializers.CharField(
        max_length=2000, required=False, allow_blank=True, default="", trim_whitespace=True
    )


@api_view(["POST"])
def agent_servers(request, pk):
    from . import agent

    s, err = _agent_session(request, pk)
    if err:
        return err
    ser = ServerIn(data=request.data)
    if not ser.is_valid():
        return Response({"code": "bad_url"}, status=status.HTTP_400_BAD_REQUEST)
    d = ser.validated_data
    try:
        agent.add_server(s, d["url"], d["label"], d["token"])
    except agent.AgentRefused as e:
        return _refused(e)
    return Response(agent.agent_out(services.load(s.id)), status=status.HTTP_201_CREATED)


def _server_or_404(s, sid):
    from .models import WorkshopAgentServer

    return get_object_or_404(WorkshopAgentServer, pk=sid, session=s)


@api_view(["POST"])
def agent_server_refresh(request, pk, sid):
    from . import agent

    s, err = _agent_session(request, pk)
    if err:
        return err
    try:
        agent.refresh_server(s, _server_or_404(s, sid))
    except agent.AgentRefused as e:
        return _refused(e)
    return Response(agent.agent_out(services.load(s.id)))


@api_view(["DELETE"])
def agent_server_delete(request, pk, sid):
    from . import agent

    s, err = _agent_session(request, pk)
    if err:
        return err
    agent.delete_server(s, _server_or_404(s, sid))
    return Response(agent.agent_out(services.load(s.id)))


class RunIn(serializers.Serializer):
    message = serializers.CharField(max_length=1000, trim_whitespace=True)


@api_view(["POST"])
def agent_run(request, pk):
    from . import agent

    s, err = _agent_session(request, pk)
    if err:
        return err
    ser = RunIn(data=request.data)
    if not ser.is_valid():
        return Response({"code": "bad_message"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        return Response(agent.run_message(s, ser.validated_data["message"]))
    except agent.AgentRefused as e:
        return _refused(e)


class ApproveIn(serializers.Serializer):
    call_id = serializers.CharField(max_length=40)
    decision = serializers.ChoiceField(choices=["approve", "deny", "always"])


@api_view(["POST"])
def agent_approve(request, pk):
    from . import agent

    s, err = _agent_session(request, pk)
    if err:
        return err
    ser = ApproveIn(data=request.data)
    if not ser.is_valid():
        return Response({"code": "bad_decision"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        return Response(agent.approve(s, ser.validated_data["call_id"], ser.validated_data["decision"]))
    except agent.AgentRefused as e:
        return _refused(e)


@api_view(["POST"])
def agent_reset(request, pk):
    from . import agent

    s, err = _agent_session(request, pk)
    if err:
        return err
    agent.reset(s)
    return Response(agent.agent_out(services.load(s.id)))


@api_view(["GET"])
def session_transcript(request, pk):
    if denied := _blocked(request.user):
        return denied
    s = _session_or_404(request, pk)
    return Response([services.turn_out(t) for t in WorkshopTurn.objects.filter(session=s)])


# ── Admin (staff) ────────────────────────────────────────────────────


@api_view(["GET"])
@permission_classes([AdminSection])
def admin_workshops(request):
    return Response(
        [
            {
                "slug": w.slug,
                "title": w.title,
                "summary": w.summary,
                "level": w.level,
                "duration_minutes": w.duration_minutes,
                "proctoring": w.proctoring,
                "is_published": w.is_published,
                "stages": len(w.agenda or []),
                "prerequisites": len(w.prerequisites or []),
            }
            for w in Workshop.objects.all()
        ]
    )


@api_view(["POST"])
@permission_classes([AdminSection])
def admin_test_run(request, slug):
    """A private try-out: a test run owned by this staff member, starting now, with them enrolled."""
    w = get_object_or_404(Workshop, slug=slug)
    with transaction.atomic():
        run = WorkshopRun.objects.create(
            workshop=w,
            audience=WorkshopRun.Audience.TEST,
            starts_at=services.now(),
            status=WorkshopRun.Status.LIVE,
            created_by=request.user,
        )
        enrollment = WorkshopEnrollment.objects.create(run=run, user=request.user)
        s = WorkshopSession.objects.create(enrollment=enrollment, user=request.user, run=run)
    return Response({"run_id": run.id, "session_id": s.id}, status=status.HTTP_201_CREATED)
