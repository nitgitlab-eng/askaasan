"""Endpoints for the Aasan Companion browser extension (mounted at /api/ext/).

Pairing: the signed-in web app asks for a 6-digit code (normal JWT); the extension trades it once for a device token.
Tasks/submit: authenticated ONLY by that device token (ExtensionTokenAuthentication) and graded by the same
browser_task path as the web attempt — same AI budget, attempt record, review scheduling and rewards."""

import fnmatch
import re
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from apps.game import services as game
from apps.learning import activities as acts
from apps.learning.access import get_viewable_activity, viewable_q
from apps.learning.api import AI_GRADES_PER_DAY
from apps.learning.models import Activity, ActivityAttempt, UserSubsectionState
from apps.review.services import record_attempt
from llm.images import decode_data_url

from . import steps as obs
from .auth import ExtensionTokenAuthentication
from .models import ExtensionPairing, ExtensionToken, ObservedSteps, token_hash

CODE_TTL = timedelta(minutes=10)
# Wrong codes across ALL callers (a guess is tried against every live code at once, so a per-IP limit alone isn't
# enough). Once this many misses pile up within one window, claims pause (429) until the window ends. Codes are NOT
# expired: wiping every learner's live code let one IP break pairing for everyone. Worst case for an attacker is
# CLAIM_FAIL_BUDGET guesses per window platform-wide; worst case for learners is a short pause, then retry.
CLAIM_FAIL_BUDGET = 20
CLAIM_FAIL_WINDOW = 10 * 60  # seconds
CLAIM_FAIL_KEY = "ext-pair-claim-fails"
MAX_IMAGE_BYTES = 2_000_000  # same ceiling the screenshot grader accepts
MAX_DEVICES = 10
LANGS = ("hi", "te", "kn", "ml", "bn", "mr", "gu", "en", "ta")
HOST_RE = re.compile(r"^(\*\.)?[a-z0-9.-]{1,253}$")


class PairStartThrottle(UserRateThrottle):
    scope, rate = "ext_pair_start", "10/hour"


class PairClaimThrottle(AnonRateThrottle):
    scope, rate = "ext_pair_claim", "10/hour"

    def get_cache_key(self, request, view):
        from apps.guests.services import ip_bucket

        # One bucket per IPv6 /64: rotating addresses inside one allocation doesn't buy more guesses.
        return self.cache_format % {"scope": self.scope, "ident": ip_bucket(self.get_ident(request))}


class SubmitThrottle(UserRateThrottle):
    scope, rate = "ext_submit", "60/hour"


# ── Pairing (from the web app) ──────────────────────────────────────


def _new_code() -> str:
    now = timezone.now()
    while True:
        code = f"{secrets.randbelow(10**6):06d}"
        if not ExtensionPairing.objects.filter(
            code=code, claimed_at__isnull=True, expires_at__gt=now
        ).exists():
            return code


@api_view(["POST"])
@throttle_classes([PairStartThrottle])
def pair_start(request):
    now = timezone.now()
    with transaction.atomic():
        # Only one live code per learner: asking again replaces the old one.
        ExtensionPairing.objects.filter(
            user=request.user, claimed_at__isnull=True, expires_at__gt=now
        ).update(expires_at=now)
        p = ExtensionPairing.objects.create(user=request.user, code=_new_code(), expires_at=now + CODE_TTL)
    return Response({"code": p.code, "expires_at": p.expires_at}, status=status.HTTP_201_CREATED)


def _device_name(ua: str) -> str:
    ua = ua or ""
    browser = "Edge" if "Edg/" in ua else "Chrome" if "Chrome/" in ua else "Browser"
    for key, os_name in (
        ("Windows", "Windows"),
        ("Mac OS X", "macOS"),
        ("CrOS", "ChromeOS"),
        ("Android", "Android"),
        ("Linux", "Linux"),
    ):
        if key in ua:
            return f"{browser} on {os_name}"
    return browser


def _fail_key(now) -> str:
    return f"{CLAIM_FAIL_KEY}:{int(now.timestamp() // CLAIM_FAIL_WINDOW)}"


def _claims_paused(now) -> bool:
    from apps.accounts import counters

    return counters.count(_fail_key(now)) >= CLAIM_FAIL_BUDGET


def _claim_failed(now) -> None:
    from apps.accounts import counters

    counters.bump(_fail_key(now), CLAIM_FAIL_WINDOW * 2)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([PairClaimThrottle])
def pair_claim(request):
    code = re.sub(r"\D", "", str(request.data.get("code") or ""))
    if len(code) != 6:
        return Response({"code": "bad_code"}, status=status.HTTP_400_BAD_REQUEST)
    now = timezone.now()
    if _claims_paused(
        now
    ):  # too many wrong codes platform-wide: no guess is even checked until the window ends
        resp = Response({"code": "pairing_busy"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        resp["Retry-After"] = str(CLAIM_FAIL_WINDOW - int(now.timestamp()) % CLAIM_FAIL_WINDOW)
        return resp
    with transaction.atomic():
        p = (
            ExtensionPairing.objects.select_for_update(of=("self",))
            .select_related("user")
            .filter(code=code, claimed_at__isnull=True, expires_at__gt=now)
            .first()
        )
        if not p or not p.user.is_active:
            _claim_failed(now)
            return Response({"code": "bad_code"}, status=status.HTTP_400_BAD_REQUEST)
        p.claimed_at = now
        p.save(update_fields=["claimed_at"])
        live = ExtensionToken.objects.filter(user=p.user, revoked_at__isnull=True).order_by("-created_at")
        for old in live[MAX_DEVICES - 1 :]:  # keep the device list bounded
            ExtensionToken.objects.filter(pk=old.pk).update(revoked_at=now)
        raw = secrets.token_urlsafe(32)
        ExtensionToken.objects.create(
            user=p.user,
            token_hash=token_hash(raw),
            name=_device_name(request.META.get("HTTP_USER_AGENT", ""))[:120],
        )
    u = p.user
    prof = getattr(u, "profile", None) if hasattr(u, "profile") else None
    name = (prof.display_name if prof else "") or u.first_name or u.email.split("@")[0]
    return Response({"token": raw, "user": {"display_name": name}})


# ── Connected browsers (from the web app) ───────────────────────────


def _device_out(t):
    return {"id": t.id, "name": t.name, "created_at": t.created_at, "last_used_at": t.last_used_at}


@api_view(["GET"])
def devices(request):
    qs = ExtensionToken.objects.filter(user=request.user, revoked_at__isnull=True).order_by("-created_at")
    return Response([_device_out(t) for t in qs])


@api_view(["DELETE"])
def device_detail(request, pk):
    n = ExtensionToken.objects.filter(user=request.user, pk=pk, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
    if not n:
        return Response({"detail": "not_found"}, status=status.HTTP_404_NOT_FOUND)
    return Response(status=status.HTTP_204_NO_CONTENT)


# ── Tasks + submit (from the extension, device token only) ──────────


def site_rules(activity) -> dict:
    """Optional site rules an author can put on the activity source: target_host ("docs.google.com" or
    "*.google.com") and url_pattern (a glob on the full URL). Without them we only hint with the task link's host."""
    src = activity.source if isinstance(activity.source, dict) else {}
    host = str(src.get("target_host") or "").strip().lower()
    pattern = str(src.get("url_pattern") or "").strip()[:300]
    rules = {
        "target_host": host if HOST_RE.match(host) else "",
        "url_pattern": pattern if pattern.startswith(("http://", "https://")) else "",
    }
    link = (activity.payload or {}).get("link") or ""
    rules["hint_host"] = rules["target_host"] or (urlsplit(link).hostname or "" if link else "")
    return rules


def host_matches(host: str, pattern: str) -> bool:
    host, pattern = (host or "").lower(), (pattern or "").lower()
    if pattern.startswith("*."):
        return host == pattern[2:] or host.endswith(pattern[1:])
    return host == pattern


def url_ok(url: str, rules: dict) -> bool:
    if rules["target_host"] and not host_matches(urlsplit(url).hostname or "", rules["target_host"]):
        return False
    return not rules["url_pattern"] or fnmatch.fnmatchcase(url, rules["url_pattern"])


def _steps_for(activity_ids) -> dict[int, list]:
    return dict(
        ObservedSteps.objects.filter(activity_id__in=activity_ids).values_list("activity_id", "steps")
    )


def _optional_for(activity_ids) -> set[int]:
    return set(
        ObservedSteps.objects.filter(activity_id__in=activity_ids, optional=True).values_list(
            "activity_id", flat=True
        )
    )


def _task_out(a, last, steps=None, optional=False):
    sub, cur = a.subsection, a.subsection.section.curriculum
    p = a.payload or {}
    rules = site_rules(a)
    return {
        "id": a.id,
        "title": a.title,
        "prompt": p.get("prompt", ""),
        "steps": p.get("steps", []),
        "proof": p.get("proof", ""),
        "link": p.get("link", ""),
        "course_title": cur.title,
        "lesson_title": sub.title,
        "lesson_path": f"/learn/{cur.id}/lesson/{sub.id}",
        "target_host": rules["target_host"],
        "url_pattern": rules["url_pattern"],
        "hint_host": rules["hint_host"],
        "last_score": round(last[a.id], 3) if a.id in last else None,
        "observe": obs.public(steps or [], optional),  # live-observation steps (null = screenshot only)
    }


@api_view(["GET"])
@authentication_classes([ExtensionTokenAuthentication])
@permission_classes([IsAuthenticated])
def tasks(request):
    """Open browser tasks: in lessons the learner has started, not yet passed. Never includes the key/rubric."""
    user = request.user
    started = dict(
        UserSubsectionState.objects.filter(user=user)
        .exclude(status=UserSubsectionState.Status.NOT_STARTED)
        .values_list("subsection_id", "started_at")
    )
    passed = ActivityAttempt.objects.filter(user=user, correct=True, activity__type="browser_task").values(
        "activity_id"
    )
    qs = (
        Activity.objects.filter(
            viewable_q(user, "subsection__section__curriculum__"),
            type="browser_task",
            subsection_id__in=list(started),
        )
        .filter(
            Q(subsection__archived=False, subsection__section__archived=False)
            | Q(subsection__section__curriculum__owner=user)
        )
        .exclude(id__in=passed)
        .select_related("subsection__section__curriculum")
        .distinct()
    )
    epoch = timezone.now() - timedelta(days=36500)
    acts_list = sorted(
        qs[:200], key=lambda a: (started.get(a.subsection_id) or epoch, -a.order), reverse=True
    )[:50]
    last = dict(
        ActivityAttempt.objects.filter(user=user, activity_id__in=[a.id for a in acts_list])
        .order_by("created_at")
        .values_list("activity_id", "score")
    )
    ids = [a.id for a in acts_list]
    steps, optional = _steps_for(ids), _optional_for(ids)
    return Response({"tasks": [_task_out(a, last, steps.get(a.id), a.id in optional) for a in acts_list]})


@api_view(["POST"])
@authentication_classes([ExtensionTokenAuthentication])
@permission_classes([IsAuthenticated])
def disconnect(request):
    """The extension's own "Disconnect": revoke the token it is using."""
    ExtensionToken.objects.filter(pk=request.auth.pk).update(revoked_at=timezone.now())
    return Response(status=status.HTTP_204_NO_CONTENT)


class SubmitIn(serializers.Serializer):
    url = serializers.CharField(max_length=2048)
    title = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    image = serializers.CharField(max_length=MAX_IMAGE_BYTES * 4 // 3 + 64)
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    lang = serializers.CharField(max_length=8, required=False, allow_blank=True, default="")
    # Live-observation evidence: [{step, url, title, text_found}] in step order (re-validated against the patterns).
    observed = serializers.ListField(
        child=serializers.DictField(), required=False, allow_null=True, max_length=obs.MAX_STEPS, default=None
    )


@api_view(["POST"])
@authentication_classes([ExtensionTokenAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([SubmitThrottle])
def submit(request, pk):
    user = request.user
    try:
        activity = get_viewable_activity(user, pk)
    except Http404:
        return Response({"code": "not_found"}, status=status.HTTP_404_NOT_FOUND)
    if activity.type != "browser_task":
        return Response({"code": "not_browser_task"}, status=status.HTTP_400_BAD_REQUEST)
    ser = SubmitIn(data=request.data)
    if not ser.is_valid():
        code = "bad_image" if "image" in ser.errors else "bad_request"
        return Response({"code": code}, status=status.HTTP_400_BAD_REQUEST)
    d = ser.validated_data
    url = d["url"].strip()
    if not obs.safe_url(url) or urlsplit(url).scheme not in ("http", "https") or not urlsplit(url).hostname:
        return Response({"code": "bad_url"}, status=status.HTTP_400_BAD_REQUEST)
    image = d["image"]
    if not image.startswith(("data:image/jpeg;", "data:image/png;")) or not decode_data_url(
        image, max_bytes=MAX_IMAGE_BYTES
    ):
        return Response({"code": "bad_image"}, status=status.HTTP_400_BAD_REQUEST)
    rules = site_rules(activity)
    if not url_ok(url, rules):  # cheap check first: no AI spend for the wrong website
        return Response(
            {"code": "wrong_site", "target_host": rules["target_host"] or rules["hint_host"]}, status=422
        )
    evidence = None
    steps = _steps_for([activity.id]).get(activity.id) or []
    if steps and d["observed"] is None and activity.id not in _optional_for([activity.id]):
        return Response({"code": "steps_required"}, status=422)  # the author wants the steps watched
    if (
        d["observed"] is not None
    ):  # sent by the side panel after watching the steps: all checks before any AI spend
        try:
            evidence = obs.check_evidence(steps, d["observed"])
        except obs.EvidenceError as e:
            return Response({"code": e.code, "step": e.step}, status=422)
        if not any(obs.host_matches(urlsplit(url).hostname or "", h) for h in obs.hosts(steps)):
            return Response({"code": "wrong_site", "target_host": ", ".join(obs.hosts(steps))}, status=422)

    from apps.providers.services import BudgetExceeded, charge

    try:
        # same weighting as the web submit path (grader output budget of 1500 tokens)
        charge(user, "ai_grades", 1, AI_GRADES_PER_DAY, max_tokens=1500)
    except BudgetExceeded:
        return Response({"code": "grading_budget_exceeded"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    lang = d["lang"] if d["lang"] in LANGS else activity.subsection.section.curriculum.language
    title = " ".join(d["title"].split())[:200]
    # Page title/URL come from an arbitrary website: pass them as quoted context, never as instructions.
    seen = ""
    if evidence:
        seen = (
            " Step list CLIENT-REPORTED by the learner's browser extension (unverified; URLs only re-checked against the"
            " task's patterns), in order: "
            + "; ".join(f"{e['step']} at {e['url'][:200]!r}" for e in evidence)
            + "."
        )
    note = (
        f"(Sent from the Aasan Companion browser extension. Page URL: {url[:500]!r}; page title: {title!r}.{seen}) "
        + " ".join(d["note"].split())[:600]
    ).strip()
    try:
        g = acts.grade(activity, {"image": image, "text": note}, lang, user=user)
    except Exception:  # noqa: BLE001 — AI grading outage shouldn't 500
        return Response({"code": "grading_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    first_try = not ActivityAttempt.objects.filter(user=user, activity=activity).exists()
    stored = {
        "text": d["note"][:600],
        "image": "[screenshot not stored]",
        "url": url[:500],
        "title": title,
        "via": "extension",
    }
    if evidence:
        stored["observed"] = evidence
    ActivityAttempt.objects.create(
        user=user, activity=activity, answer=stored, score=g.score, correct=g.correct, feedback=g.feedback
    )
    record_attempt(user, activity, g.score)
    reward = game.on_activity(user, activity, g.score, first_try)
    cur, sub = activity.subsection.section.curriculum, activity.subsection
    return Response(
        {
            "score": round(g.score, 3),
            "correct": g.correct,
            "feedback": g.feedback,
            "reward": reward,
            "lesson_path": f"/learn/{cur.id}/lesson/{sub.id}",
        }
    )


# ── Live-observation steps (from the web Lab, course author only) ───


@api_view(["GET", "PUT"])
def activity_steps(request, pk):
    """The author's live-observation steps for one of their browser_task activities. PUT {"steps": [...]} replaces
    them ([] removes them). Anyone else gets 404 — the same as an activity that doesn't exist."""
    from apps.learning.lab_api import _owned_activity

    a = _owned_activity(request, pk)
    if a.type != "browser_task":
        return Response({"code": "not_browser_task"}, status=status.HTTP_400_BAD_REQUEST)
    if request.method == "PUT":
        try:
            steps = obs.validate(request.data.get("steps") if isinstance(request.data, dict) else None)
        except obs.StepError as e:
            return Response(
                {"code": "invalid_steps", "step": e.index, "field": e.field, "detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        optional = request.data.get("optional", False) if isinstance(request.data, dict) else False
        if not isinstance(optional, bool):
            return Response(
                {"code": "invalid_steps", "field": "optional", "detail": "optional must be true or false"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if steps:
            ObservedSteps.objects.update_or_create(
                activity=a, defaults={"steps": steps, "optional": optional, "updated_by": request.user}
            )
        else:
            ObservedSteps.objects.filter(activity=a).delete()
    steps = _steps_for([a.id]).get(a.id) or []
    return Response(
        {
            "steps": steps,
            "hosts": obs.hosts(steps),
            "origins": obs.origins(steps),
            "optional": a.id in _optional_for([a.id]),
        }
    )
