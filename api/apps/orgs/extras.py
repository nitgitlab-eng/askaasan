"""P9 school/company extras: rebranding, custom member fields, per-org feature switches, setup wizard checklist,
guest invitation campaigns, referral programmes (with payout ledger), shared notes library, member fields in exports."""

import csv
import io
import re
import secrets

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from .models import (
    Campaign,
    Group,
    Invitation,
    Membership,
    Organization,
    OrgDocument,
    ReferralCode,
    ReferralUse,
)
from .perms import RANK, require

FEATURES = ("mentor", "live", "roleplay", "leaderboard", "shop", "external_mcp", "workshops")
# Two separate rules per feature:
# - WHO may flip it. PLATFORM_FEATURES are switched by the platform admin only, never by the org itself (the org's
#   settings endpoint drops them): `workshops` lets an org schedule institution workshop runs, and its monthly
#   `workshop_seats` quota (0 until the platform admin sets one) decides how many learners those runs may hold.
# - The DEFAULT when the org has no explicit setting. Every feature, workshops included, is on unless listed in
#   DEFAULT_OFF_FEATURES. An explicit False always wins: it keeps the org out of institution runs and (blocked())
#   keeps its learners out of workshops altogether.
PLATFORM_FEATURES = ("workshops",)
DEFAULT_OFF_FEATURES: tuple[str, ...] = ()
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
KEY = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
VISIBILITY = (
    "editable",
    "readonly",
    "hidden",
)  # fields created before v2 have no visibility = hidden from the member


# ── Feature switches (enforced server-side) ──────────────────────────


class JoinThrottle(UserRateThrottle):
    scope = "join"  # same budget as the join-code endpoint


# AI features that process a learner's own words, voice or files. An under-18 can't use them until their guardian
# confirms consent (DPDP Act: verifiable parental consent before processing a child's data). Lessons stay open.
GUARDIAN_GATED = frozenset({"mentor", "roleplay", "live", "workshops", "external_mcp", "docs", "voice"})
GUARDIAN_REQUIRED = "guardian_consent_required"


def refusal(user, feature: str) -> str | None:
    """Why `user` can't use `feature`: GUARDIAN_REQUIRED, "feature_off" (an org switched it off), or None."""
    if not getattr(user, "is_authenticated", False):
        return None
    if feature in GUARDIAN_GATED:
        from apps.accounts.guardian import consent_pending

        if consent_pending(user):
            return GUARDIAN_REQUIRED
    if user.is_staff:
        return None
    off = any(
        not (f or {}).get(feature, True)
        for f in Organization.objects.filter(memberships__user=user, memberships__role="learner").values_list(
            "features", flat=True
        )
    )
    return "feature_off" if off else None


def blocked(user, feature: str) -> bool:
    """A learner in any org that switched `feature` off can't use it (schools decide for their students), nor can an
    under-18 use an AI feature before their guardian confirms."""
    return refusal(user, feature) is not None


def hidden_from_boards():
    """User ids that must not appear on any public board: learners of a school that switched the leaderboard off."""
    return Membership.objects.filter(role="learner", org__features__leaderboard=False).values("user_id")


def feature_off_response(feature: str, code: str = "feature_off") -> Response:
    return Response({"code": code, "feature": feature}, status=status.HTTP_403_FORBIDDEN)


def refusal_response(user, feature: str) -> Response | None:
    code = refusal(user, feature)
    return feature_off_response(feature, code) if code else None


def _brand(org) -> dict:
    return {
        "slug": org.slug,
        "name": org.display_name or org.name,
        "brand_color": org.brand_color,
        "logo_url": org.logo_url,
        "features": {k: feature_on(org, k) for k in FEATURES},
    }


def feature_on(org, feature: str) -> bool:
    """On unless the org stores an explicit False, or the feature is in DEFAULT_OFF_FEATURES and was never switched on."""
    return (org.features or {}).get(feature, feature not in DEFAULT_OFF_FEATURES) is True


@api_view(["GET"])
def my_brand(request):
    """Branding + switched-off features for the learner's orgs (the app hides those features)."""
    ms = Membership.objects.filter(user=request.user).select_related("org").order_by("joined_at")
    orgs = [_brand(m.org) for m in ms]
    learner_orgs = [_brand(m.org) for m in ms if m.role == "learner"]
    return Response(
        {
            "orgs": orgs,
            "primary": (learner_orgs or orgs or [None])[0],
            "disabled": sorted(  # what blocked() refuses: only an explicit False, never a missing key
                {
                    k
                    for m in ms
                    if m.role == "learner"
                    for k in FEATURES
                    if (m.org.features or {}).get(k, True) is False
                }
            ),
        }
    )


# ── Settings: brand, member fields, features ─────────────────────────


class FieldDef(serializers.Serializer):
    key = serializers.RegexField(KEY)
    label = serializers.CharField(max_length=40)
    type = serializers.ChoiceField(choices=["text", "select"])
    options = serializers.ListField(child=serializers.CharField(max_length=40), max_length=30, required=False)
    # Member fields v2: what the member sees (editable / read-only / hidden) and whether members fill it in themselves
    visibility = serializers.ChoiceField(choices=VISIBILITY, default="hidden")
    self_fill = serializers.BooleanField(default=False)

    def validate(self, d):
        if d["type"] == "select" and len(d.get("options") or []) < 2:
            raise serializers.ValidationError({"options": "select_needs_options"})
        if d.get("self_fill") and d.get("visibility") != "editable":
            raise serializers.ValidationError({"self_fill": "self_fill_needs_editable"})
        return d


class OrgSettings(serializers.Serializer):
    display_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    description = serializers.CharField(
        max_length=1000, required=False, allow_blank=True
    )  # "About the organisation"
    brand_color = serializers.CharField(max_length=7, required=False, allow_blank=True)
    logo_url = serializers.CharField(max_length=300, required=False, allow_blank=True)
    member_fields = FieldDef(many=True, required=False)
    features = serializers.DictField(child=serializers.BooleanField(), required=False)

    def validate_display_name(self, v):
        from apps.credentials.services import RESERVED

        if v != self.context.get("current", "") and any(r in v.casefold() for r in RESERVED):
            raise serializers.ValidationError(
                "name_reserved"
            )  # orgs can't pose as the platform (certificates, emails)
        return v

    def validate_brand_color(self, v):
        if v and not HEX.match(v):
            raise serializers.ValidationError("bad_color")
        return v

    def validate_logo_url(self, v):
        if v and not re.fullmatch(re.escape(settings.MEDIA_URL) + r"[\w/\-]+\.(png|jpe?g|webp|svg)", v):
            raise serializers.ValidationError(
                "upload_logo_first"
            )  # only our own media — no external trackers on the learner side
        return v

    def validate_member_fields(self, v):
        if len(v) > 10 or len({f["key"] for f in v}) != len(v):
            raise serializers.ValidationError("max_10_unique_keys")
        for f in v:  # partial PATCHes skip nested defaults
            f.setdefault("visibility", "hidden")
            f.setdefault("self_fill", False)
        return v

    def validate_features(self, v):
        if not set(v) <= set(FEATURES):
            raise serializers.ValidationError("unknown_feature")
        # Only the platform admin switches these: dropped here, so a settings form echoing them back still saves.
        return {k: on for k, on in v.items() if k not in PLATFORM_FEATURES}


def settings_out(org) -> dict:
    return {
        **_brand(org),
        "display_name": org.display_name,
        "member_fields": org.member_fields or [],
        "setup": org.setup or {},
        "description": org.description,
        "workshop_seats": org.workshop_seats,
    }


@api_view(["GET", "PATCH"])
def org_settings(request, slug):
    me = require(request.user, slug, "manager" if request.method == "GET" else "admin")
    org = me.org
    if request.method == "PATCH":
        ser = OrgSettings(data=request.data, partial=True, context={"current": me.org.display_name})
        ser.is_valid(raise_exception=True)
        for k, v in ser.validated_data.items():
            setattr(org, k, {**(org.features or {}), **v} if k == "features" else v)
        org.save()
    return Response(settings_out(org))


@api_view(["PATCH"])
def member_fields(request, slug, pk):
    """Set a member's custom fields (roll no., section, department…)."""
    me = require(request.user, slug, "manager")
    m = get_object_or_404(Membership, pk=pk, org=me.org)
    if RANK[m.role] > RANK[me.role]:
        raise PermissionDenied("cannot_manage_higher_role")  # same rule as member_detail
    defs = {f["key"]: f for f in me.org.member_fields or []}
    raw = request.data.get("fields") or {}
    if not isinstance(raw, dict) or not set(raw) <= set(defs):
        return Response({"code": "unknown_field"}, status=status.HTTP_400_BAD_REQUEST)
    vals = dict(m.fields or {})
    for k, v in raw.items():
        v = str(v or "").strip()[:80]
        if v and defs[k]["type"] == "select" and v not in defs[k].get("options", []):
            return Response({"code": "bad_option", "field": k}, status=status.HTTP_400_BAD_REQUEST)
        if v:
            vals[k] = v
        else:
            vals.pop(k, None)
    m.fields = vals
    m.save(update_fields=["fields"])
    return Response({"id": m.id, "fields": m.fields})


def _member_view(m) -> dict:
    """What one member may see of their own custom fields: hidden fields (and their values) are never included."""
    out = []
    for f in m.org.member_fields or []:
        vis = f.get("visibility", "hidden")
        if vis == "hidden":
            continue
        val = (m.fields or {}).get(f["key"], "")
        out.append(
            {
                "key": f["key"],
                "label": f["label"],
                "type": f["type"],
                "options": f.get("options") or [],
                "value": val,
                "editable": vis == "editable",
                "self_fill": bool(f.get("self_fill")),
                "missing": bool(f.get("self_fill")) and not val,
            }
        )
    return {"slug": m.org.slug, "org": m.org.display_name or m.org.name, "fields": out}


@api_view(["GET"])
def my_fields(request):
    """The learner's own custom fields in each org (only those the org lets them see), plus which self-fill ones are missing."""
    rows = [
        _member_view(m)
        for m in Membership.objects.filter(user=request.user).select_related("org").order_by("joined_at")
    ]
    rows = [r for r in rows if r["fields"]]
    return Response({"orgs": rows, "missing": sum(1 for r in rows for f in r["fields"] if f["missing"])})


@api_view(["PATCH"])
def my_fields_update(request, slug):
    """A member updates their own editable fields only; read-only, hidden or unknown keys are refused."""
    m = Membership.objects.select_related("org").filter(org__slug=slug, user=request.user).first()
    if not m:
        return Response(status=status.HTTP_404_NOT_FOUND)
    defs = {f["key"]: f for f in m.org.member_fields or [] if f.get("visibility") == "editable"}
    raw = request.data.get("fields")
    if not isinstance(raw, dict) or not raw or len(raw) > 10:
        return Response({"code": "bad_fields"}, status=status.HTTP_400_BAD_REQUEST)
    if not set(raw) <= set(defs):
        return Response({"code": "not_editable"}, status=status.HTTP_403_FORBIDDEN)
    vals = dict(m.fields or {})
    for k, v in raw.items():
        v = str(v or "").strip()[:80]
        if v and defs[k]["type"] == "select" and v not in defs[k].get("options", []):
            return Response({"code": "bad_option", "field": k}, status=status.HTTP_400_BAD_REQUEST)
        if v:
            vals[k] = v
        else:
            vals.pop(k, None)
    m.fields = vals
    m.save(update_fields=["fields"])
    return Response(_member_view(m))


@api_view(["GET", "PATCH"])
def setup_checklist(request, slug):
    """Admin setup wizard: progress is mostly derived from real data; admins can skip optional steps."""
    me = require(request.user, slug, "admin" if request.method == "PATCH" else "manager")
    org = me.org
    if request.method == "PATCH":
        step = str(request.data.get("skip") or "")
        if step in ("about", "brand", "fields", "groups", "invite", "assign", "dpa"):
            org.setup = {**(org.setup or {}), step: "skipped"}
            org.save(update_fields=["setup"])
    skipped = {k for k, v in (org.setup or {}).items() if v == "skipped"}
    done = {
        "about": bool(org.description),
        "brand": bool(org.display_name or org.logo_url or org.brand_color),
        "fields": bool(org.member_fields),
        "groups": org.groups.exclude(name="Everyone").exists(),
        "invite": org.memberships.filter(role="learner").exists()
        or Invitation.objects.filter(org=org).exists()
        or org.campaigns.exists(),
        "assign": org.assignments.exists(),
        "dpa": bool(org.dpa_accepted_at),
    }
    steps = [{"key": k, "done": v, "skipped": k in skipped and not v} for k, v in done.items()]
    return Response({"steps": steps, "complete": all(s["done"] or s["skipped"] for s in steps)})


# ── Campaigns (bulk guest invitations) ───────────────────────────────


class CampaignIn(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    quota = serializers.IntegerField(min_value=1, max_value=5000, default=50)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    group_id = serializers.IntegerField(required=False, allow_null=True)
    active = serializers.BooleanField(required=False)


def _campaign_out(c) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "quota": c.quota,
        "used": c.used,
        "expires_at": c.expires_at,
        "active": c.active,
        "group": {"id": c.group_id, "name": c.group.name} if c.group_id else None,
        "link": f"{settings.FRONTEND_URL}/join/c/{c.token}",
    }


@api_view(["GET", "POST"])
def campaigns(request, slug):
    me = require(request.user, slug, "manager")
    if request.method == "POST":
        ser = CampaignIn(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        group = get_object_or_404(Group, pk=d["group_id"], org=me.org) if d.get("group_id") else None
        c = Campaign.objects.create(
            org=me.org,
            name=d["name"],
            quota=d["quota"],
            expires_at=d.get("expires_at"),
            group=group,
            created_by=request.user,
        )
        return Response(_campaign_out(c), status=status.HTTP_201_CREATED)
    return Response(
        [_campaign_out(c) for c in me.org.campaigns.select_related("group").order_by("-created_at")[:100]]
    )


@api_view(["PATCH", "DELETE"])
def campaign_detail(request, slug, pk):
    me = require(request.user, slug, "manager")
    c = get_object_or_404(Campaign, pk=pk, org=me.org)
    if request.method == "DELETE":
        c.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    ser = CampaignIn(data=request.data, partial=True)
    ser.is_valid(raise_exception=True)
    for k in ("name", "quota", "expires_at", "active"):
        if k in ser.validated_data:
            setattr(c, k, ser.validated_data[k])
    c.save()
    return Response(_campaign_out(c))


EMAIL = re.compile(r"[^@\s,;<>\"']+@[^@\s,;<>\"']+\.[a-zA-Z]{2,}")


@api_view(["POST"])
def campaign_emails(request, slug, pk):
    """Paste or upload a CSV of emails → personal invitations (campaign's group), each emailed once."""
    me = require(request.user, slug, "manager")
    c = get_object_or_404(Campaign, pk=pk, org=me.org)
    text = str(request.data.get("csv") or "")[:200_000]
    emails = sorted(
        {e.lower() for row in csv.reader(io.StringIO(text)) for cell in row for e in EMAIL.findall(cell)}
    )
    if not emails:
        return Response({"code": "no_emails"}, status=status.HTTP_400_BAD_REQUEST)
    if len(emails) > 500:
        return Response({"code": "max_500_emails"}, status=status.HTTP_400_BAD_REQUEST)
    existing = set(
        Invitation.objects.filter(org=me.org, email__in=emails, accepted_at__isnull=True).values_list(
            "email", flat=True
        )
    )
    members = set(
        Membership.objects.filter(org=me.org, user__email__in=emails).values_list("user__email", flat=True)
    )
    from apps.legal.mail import mail_ready

    from .api import email_invite, invite_mail_out, invite_refusal

    if refused := invite_refusal(request.user, me.org, len(set(emails) - existing - members)):
        return refused
    sent, unsent, ready = [], [], mail_ready()
    for email in emails:
        if email in existing or email in members:
            continue
        inv = Invitation.objects.create(
            org=me.org, email=email, role="learner", group=c.group, invited_by=request.user
        )
        if miss := email_invite(
            inv,
            f"You're invited to learn on Aasan with {me.org.display_name or me.org.name} ({c.name}).",
            ready,
        ):
            unsent.append(miss)
        sent.append(email)
    return Response(
        {"invited": len(sent), "skipped": len(emails) - len(sent), **invite_mail_out(unsent)},
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET", "POST"])
@throttle_classes([JoinThrottle])  # join links can't be guessed by brute force
def campaign_join(request, token):
    from .api import _join

    c = get_object_or_404(Campaign.objects.select_related("org", "group"), token=token)
    open_ = c.active and c.used < c.quota and not (c.expires_at and c.expires_at < timezone.now())
    if request.method == "GET":
        return Response(
            {
                "org": _brand(c.org),
                "campaign": c.name,
                "open": open_,
                "member": Membership.objects.filter(org=c.org, user=request.user).exists(),
            }
        )
    if Membership.objects.filter(org=c.org, user=request.user).exists():
        return Response({"slug": c.org.slug, "already": True})
    if not open_:
        return Response({"code": "campaign_closed"}, status=status.HTTP_410_GONE)
    with transaction.atomic():
        n = Campaign.objects.filter(pk=c.pk, used__lt=F("quota")).update(used=F("used") + 1)  # atomic quota
        if not n:
            return Response({"code": "campaign_closed"}, status=status.HTTP_410_GONE)
        _join(request.user, c.org, "learner", c.group)
    return Response({"slug": c.org.slug, "joined": True}, status=status.HTTP_201_CREATED)


# ── Referral programmes ──────────────────────────────────────────────


class ReferralIn(serializers.Serializer):
    code = serializers.RegexField(r"^[A-Za-z0-9_-]{6,24}$", required=False)  # join links are rate-limited too
    reward = serializers.CharField(max_length=160, required=False, allow_blank=True)
    reward_paise = serializers.IntegerField(min_value=0, max_value=10_000_000, default=0)
    owner_id = serializers.IntegerField(
        required=False, allow_null=True
    )  # a member who refers (teacher, ambassador)
    active = serializers.BooleanField(required=False)


def _ref_out(r) -> dict:
    uses = r.uses.all()
    return {
        "id": r.id,
        "code": r.code,
        "reward": r.reward,
        "reward_paise": r.reward_paise,
        "active": r.active,
        "owner": r.owner.email if r.owner_id else None,
        "link": f"{settings.FRONTEND_URL}/join/r/{r.code}",
        "joins": uses.count(),
        "owed_paise": sum(u.amount_paise for u in uses if u.status == "approved"),
        "paid_paise": sum(u.amount_paise for u in uses if u.status == "paid"),
    }


@api_view(["GET", "POST"])
def referrals(request, slug):
    me = require(request.user, slug, "admin")
    if request.method == "POST":
        ser = ReferralIn(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        owner = None
        if d.get("owner_id"):
            owner = get_object_or_404(Membership, org=me.org, user_id=d["owner_id"]).user
        try:
            r = ReferralCode.objects.create(
                org=me.org,
                code=(d.get("code") or secrets.token_hex(5)).upper(),
                reward=d.get("reward", ""),
                reward_paise=d["reward_paise"],
                owner=owner,
            )
        except IntegrityError:
            return Response({"code": "code_taken"}, status=status.HTTP_409_CONFLICT)
        return Response(_ref_out(r), status=status.HTTP_201_CREATED)
    return Response(
        [_ref_out(r) for r in me.org.referral_codes.prefetch_related("uses").select_related("owner")]
    )


@api_view(["PATCH"])
def referral_detail(request, slug, pk):
    me = require(request.user, slug, "admin")
    r = get_object_or_404(ReferralCode, pk=pk, org=me.org)
    ser = ReferralIn(data=request.data, partial=True)
    ser.is_valid(raise_exception=True)
    for k in ("reward", "reward_paise", "active"):
        if k in ser.validated_data:
            setattr(r, k, ser.validated_data[k])
    r.save()
    return Response(_ref_out(r))


@api_view(["GET"])
def referral_ledger(request, slug):
    me = require(request.user, slug, "admin")
    rows = (
        ReferralUse.objects.filter(code__org=me.org)
        .select_related("code", "user__profile")
        .order_by("-created_at")[:500]
    )
    return Response(
        [
            {
                "id": u.id,
                "code": u.code.code,
                "user": (u.user.profile.display_name or u.user.email.split("@")[0])[:40],
                "status": u.status,
                "amount_paise": u.amount_paise,
                "note": u.note,
                "created_at": u.created_at,
                "paid_at": u.paid_at,
            }
            for u in rows
        ]
    )


@api_view(["PATCH"])
def referral_use(request, slug, pk):
    """Approve / reject / mark paid (payout tracking). Paid is final."""
    me = require(request.user, slug, "admin")
    u = get_object_or_404(ReferralUse, pk=pk, code__org=me.org)
    st = request.data.get("status")
    allowed = {
        "pending": {"approved", "rejected"},
        "approved": {"paid", "rejected"},
        "rejected": {"pending"},
        "paid": set(),
    }
    if st not in allowed[u.status]:
        return Response({"code": "bad_transition"}, status=status.HTTP_400_BAD_REQUEST)
    u.status, u.note = st, str(request.data.get("note") or u.note)[:200]
    if st == "paid":
        u.paid_at = timezone.now()
    u.save()
    return Response({"id": u.id, "status": u.status, "paid_at": u.paid_at})


@api_view(["GET", "POST"])
@throttle_classes([JoinThrottle])  # join links can't be guessed by brute force
def referral_join(request, code):
    from .api import _join

    r = get_object_or_404(ReferralCode.objects.select_related("org"), code=code.upper())
    if request.method == "GET":
        return Response({"org": _brand(r.org), "reward": r.reward, "open": r.active})
    if not r.active:
        return Response({"code": "referral_closed"}, status=status.HTTP_410_GONE)
    if r.owner_id == request.user.id:
        return Response({"code": "own_code"}, status=status.HTTP_400_BAD_REQUEST)
    already = Membership.objects.filter(org=r.org, user=request.user).exists()
    with transaction.atomic():
        _join(request.user, r.org, "learner")
        if not already:  # only genuinely new members count toward a payout
            ReferralUse.objects.get_or_create(
                code=r, user=request.user, defaults={"amount_paise": r.reward_paise}
            )
    return Response(
        {"slug": r.org.slug, "joined": not already}, status=status.HTTP_201_CREATED if not already else 200
    )


# ── Shared notes library ─────────────────────────────────────────────


@api_view(["GET", "POST"])
def org_documents(request, slug):
    from apps.docs.models import Document

    if request.method == "POST":
        from .parse import to_int

        me = require(request.user, slug, "manager")
        # own notes only: a school knowledge-base upload is the org's, never re-shareable through its uploader
        doc = get_object_or_404(
            Document.objects.exclude(shared_in__source="kb"),
            pk=to_int(request.data.get("document_id")) or 0,
            owner=request.user,
        )
        OrgDocument.objects.get_or_create(org=me.org, document=doc, defaults={"shared_by": request.user})
    me = require(request.user, slug, "learner")
    if me.partner:
        return Response([])  # cohort partners get their programme's courses, not the org's internal documents
    return Response(
        [
            {
                "id": od.id,
                "document_id": od.document_id,
                "title": od.document.title,
                "pages": od.document.pages,
                "shared_by": (od.shared_by.profile.display_name if od.shared_by_id else "") or "",
                "created_at": od.created_at,
            }
            for od in me.org.documents.filter(source="shared", document__isnull=False)
            .select_related("document", "shared_by__profile")
            .defer("raw")
            .order_by("-created_at")
        ]
    )


@api_view(["DELETE"])
def org_document(request, slug, pk):
    me = require(request.user, slug, "manager")
    get_object_or_404(
        OrgDocument, pk=pk, org=me.org, source="shared"
    ).delete()  # knowledge-base docs: see knowledge.py
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
def my_shared_documents(request):
    """Notes my orgs shared with me — usable in 'Ask about my notes'."""
    rows = readable_org_documents(request.user).select_related("document", "org").defer("raw")
    return Response(
        [
            {
                "document_id": od.document_id,
                "title": od.document.title,
                "pages": od.document.pages,
                "org": od.org.display_name or od.org.name,
            }
            for od in rows
        ]
    )


def readable_org_documents(user):
    """Org documents a member may read: shared notes, and knowledge-base docs (org-wide staff always; learners unless the
    admin switched that document to staff-only). Unit admins are not org-wide staff (see perms.staff_org_ids). Cohort
    partners and ex-members get none. All conditions sit in one filter() so they apply to the same membership row."""
    from django.db.models import Q

    me = {"org__memberships__user": user, "org__memberships__partner": False}
    return (
        OrgDocument.objects.filter(document__isnull=False)
        .filter(
            Q(**me, source="shared")
            | Q(**me, learners_can_read=True)
            | Q(**me, org__memberships__role__in=["owner", "admin"])
            | Q(**me, org__memberships__role="manager", org__memberships__unit_scoped=False)
        )
        .distinct()
    )


def viewable_documents(user):
    """Docs the user may chat with: their own notes + documents their orgs let them read. Knowledge-base docs count only
    through membership (an uploader who left the org loses them)."""
    from django.db.models import Q

    from apps.docs.models import Document

    own = Q(owner=user) & ~Q(shared_in__source="kb")
    return Document.objects.filter(
        own | Q(id__in=readable_org_documents(user).values("document_id"))
    ).distinct()
