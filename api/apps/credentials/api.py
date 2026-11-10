"""Credentials: my certificates (list, hide, revoke, PDF), public verification, org-manager issuing, and
"Share your progress" (AI-written manager summary or LinkedIn post from the learner's own facts)."""

import json
import re

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from apps.orgs.perms import require
from llm.fence import fence

from . import services as svc
from .models import Certificate


class VerifyThrottle(AnonRateThrottle):
    scope = "cert_verify"
    rate = "120/hour"


def _mine(request, pk) -> Certificate:
    return get_object_or_404(Certificate, pk=pk, user=request.user)


@api_view(["GET"])
def my_certificates(request):
    return Response(
        [svc.owner_out(c) for c in Certificate.objects.filter(user=request.user).select_related("org")]
    )


@api_view(["PATCH"])
def certificate_detail(request, pk):
    """Owner hides / shows the public verification page."""
    c = _mine(request, pk)
    if not isinstance(request.data.get("hidden"), bool):
        return Response({"code": "bad_request"}, status=status.HTTP_400_BAD_REQUEST)
    c.hidden = request.data["hidden"]
    c.save(update_fields=["hidden"])
    return Response(svc.owner_out(c))


@api_view(["POST"])
def certificate_revoke(request, pk):
    """Owner revokes for good: the verification page stops working and it can't be undone."""
    c = _mine(request, pk)
    if not c.revoked_at:
        c.revoked_at = timezone.now()
        c.save(update_fields=["revoked_at"])
    return Response(svc.owner_out(c))


@api_view(["GET"])
def certificate_pdf(request, pk):
    from .pdf import render

    c = _mine(request, pk)
    if c.revoked_at:
        return Response({"code": "revoked"}, status=status.HTTP_404_NOT_FOUND)
    resp = HttpResponse(render(c), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="aasan-certificate-{c.id}.pdf"'
    return resp


@api_view(["GET"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
@throttle_classes([VerifyThrottle])
def verify(request, code):
    """Public: only the learner's display name, title, issuer, date and 'verified'. Unknown or hidden → 404. Revoked →
    410 with the revocation date only (an employer checking it must learn it was withdrawn, not just "not found")."""
    if not svc.CODE_RE.match(code or ""):
        return Response({"code": "not_found"}, status=status.HTTP_404_NOT_FOUND)
    c = Certificate.objects.filter(code=code, hidden=False).first()
    if not c:
        return Response({"code": "not_found"}, status=status.HTTP_404_NOT_FOUND)
    if c.revoked_at:
        return Response({"code": "revoked", "revoked_at": c.revoked_at}, status=status.HTTP_410_GONE)
    return Response(svc.public_out(c))


# ── Org managers ─────────────────────────────────────────────────────


@api_view(["GET", "POST"])
def org_certificates(request, slug):
    from apps.orgs.models import Membership, Survey
    from apps.roleplay.models import Scenario

    me = require(request.user, slug, "manager")
    org = me.org
    if request.method == "GET":
        return Response([svc.manager_out(c) for c in Certificate.objects.filter(org=org)[:300]])
    m = (
        Membership.objects.filter(org=org, pk=request.data.get("member_id"))
        .select_related("user__profile")
        .first()
        if str(request.data.get("member_id") or "").isdigit()
        else None
    )
    kind = request.data.get("kind")
    if not m or kind not in ("course", "scenario", "test") or not str(request.data.get("id") or "").isdigit():
        return Response({"code": "bad_request"}, status=status.HTTP_400_BAD_REQUEST)
    item_id = int(request.data["id"])
    allowed = {r["id"] for r in svc.eligible(org, m)[kind]}
    if item_id not in allowed:  # must be assigned + completed, or a passed test of this org
        return Response({"code": "not_eligible"}, status=status.HTTP_403_FORBIDDEN)
    from apps.learning.models import Curriculum

    item = {"course": Curriculum, "scenario": Scenario, "test": Survey}[kind].objects.get(pk=item_id)
    detail = {"pct": svc.best_pct(org, m.user, item)} if kind == "test" else {}
    try:
        cert, created = svc.issue(m.user, kind, item, org=org, issued_by=request.user, detail=detail)
    except svc.ReservedIssuer:  # an org can't issue as (or as if it were) Aasan
        return Response({"code": "issuer_name_reserved"}, status=status.HTTP_400_BAD_REQUEST)
    if created:
        from apps.game.services import notify

        notify(m.user, "certificate", f"🎓 {cert.title}"[:160], "", "/certificates")
    return Response(svc.manager_out(cert), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(["GET"])
def org_eligible(request, slug, member_id):
    from apps.orgs.models import Membership

    me = require(request.user, slug, "manager")
    m = get_object_or_404(Membership.objects.select_related("user"), org=me.org, pk=member_id)
    return Response(svc.eligible(me.org, m))


@api_view(["POST"])
def org_revoke(request, slug, pk):
    me = require(request.user, slug, "manager")
    c = get_object_or_404(Certificate, pk=pk, org=me.org)
    if not c.revoked_at:
        c.revoked_at = timezone.now()
        c.save(update_fields=["revoked_at"])
    return Response(svc.manager_out(c))


# ── Share your progress ──────────────────────────────────────────────


def _facts(request, source, cert_id) -> dict | None:
    """Only the learner's own data. Review facts come from the same numbers as the quarterly review."""
    if source == "certificate":
        c = (
            Certificate.objects.filter(pk=cert_id, user=request.user, revoked_at__isnull=True).first()
            if str(cert_id or "").isdigit()
            else None
        )
        if not c:
            return None
        return {
            "kind": "certificate",
            "name": c.learner_name,
            "certificate": c.title,
            "type": c.kind,
            "issuer": c.issuer_name,
            "issuer_type": c.issuer_type,
            **({"course_by": c.author_name} if c.author_name else {}),
            "date": timezone.localtime(c.issued_at).date().isoformat(),
            "verify_url": svc.verify_url(c),
            **({"score_pct": c.detail["pct"]} if c.detail.get("pct") is not None else {}),
        }
    if source == "review":
        from apps.studio.export_api import _quarter, _review_facts

        f = _review_facts(request.user)
        t = f["totals"]
        stats = {
            k: t.get(k)
            for k in (
                "minutes",
                "lessons",
                "active_days",
                "streak",
                "best_streak",
                "first_try_accuracy",
                "xp",
            )
            if t.get(k)
        }
        return {
            "kind": "review",
            "name": svc.learner_name(request.user),
            "period": f"{_quarter()} (last 90 days)",
            "stats": stats,
            "courses": [{"title": k, "lessons_completed": len(v)} for k, v in f["courses"].items()][:6],
            "skills": [s for s in f["skills"] if s.get("mastery_pct")][:6],
            "certificates": [
                c.title for c in Certificate.objects.filter(user=request.user, revoked_at__isnull=True)[:5]
            ],
        }
    return None


@api_view(["GET"])
def share_facts(request):
    """Facts for the client-side share image (free; no AI)."""
    q = request.query_params
    facts = _facts(request, q.get("source"), q.get("id") or q.get("certificate_id"))
    return Response(facts) if facts else Response(status=status.HTTP_404_NOT_FOUND)


def _refund(user, metric: str) -> None:
    from django.db.models import F

    from apps.providers.models import UsageCounter

    UsageCounter.objects.filter(user=user, day=timezone.localdate(), metric=metric, amount__gte=1).update(
        amount=F("amount") - 1
    )


@api_view(["POST"])
def share(request):
    """AI-written, editable text from the learner's own facts: a plain manager summary or a LinkedIn post (charged)."""
    from apps.orgs.surveys import _lang_rule
    from apps.providers.services import BudgetExceeded, charge
    from llm.base import LLMError
    from llm.prompts.credentials import SHARE_SHAPES, SHARE_SYSTEM, ShareOut
    from llm.structured import complete_json_sync

    fmt = request.data.get("format")
    if fmt not in SHARE_SHAPES:
        return Response({"code": "bad_request"}, status=status.HTTP_400_BAD_REQUEST)
    facts = _facts(
        request, request.data.get("source"), request.data.get("certificate_id") or request.data.get("id")
    )
    if not facts:
        return Response({"code": "not_found"}, status=status.HTTP_404_NOT_FOUND)
    try:
        charge(request.user, "ai_grades", 1, 200, max_tokens=1200)  # 1 unit; _refund gives back 1
    except BudgetExceeded:
        return Response({"code": "ai_budget_exceeded"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    what, shape = SHARE_SHAPES[fmt]
    system = SHARE_SYSTEM.format(fmt=what, shape=shape, lang_rule=_lang_rule(request.user))
    try:
        out = complete_json_sync(
            "suggest",
            system,
            fence("facts", json.dumps(facts, ensure_ascii=False, default=str)),
            ShareOut,
            max_tokens=1200,
        )
    except Exception as e:  # noqa: BLE001
        _refund(
            request.user, "ai_grades"
        )  # reserved before the call (so parallel requests can't pass the cap); give it back
        return Response(
            {"code": e.code if isinstance(e, LLMError) else "ai_unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    tags = []
    if fmt == "linkedin":
        for h in out.hashtags:
            clean = re.sub(r"[^\w]", "", h, flags=re.UNICODE)[:40]
            if clean and clean.lower() not in {x.lower() for x in tags}:
                tags.append(clean)
    return Response({"format": fmt, "text": out.text.strip()[:3000], "hashtags": tags[:6], "facts": facts})
