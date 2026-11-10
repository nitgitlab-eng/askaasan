"""Organisation API v1 (/api/v1/orgs/<slug>/…), API keys only (see auth.py). Every list pages with ?page= (50) and
exports with ?export=csv.

  GET    members/                    read:members   members (first name, email, role, classes, joined)
  POST   members/                    write:members  {emails: [...], group_id?} → invite learners (same daily allowance)
  DELETE members/<id>/               write:members  remove a learner (staff are refused)
  GET    assignments/                read:progress  assignments with completion numbers
  GET    assignments/<id>/progress/  read:progress  per-learner progress for one assignment
  GET    certificates/               read:progress  certificates issued by the organisation
  GET    training-records/           read:progress  compliance training records (?user ?kind ?from ?to)
"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.response import Response

from apps.accounts.admin_paging import paged

from .auth import ApiKeyAuthentication, ApiKeyThrottle, scoped


class _Rows(list):
    """A list `paged` can page (it calls .count() and slices)."""

    def count(self, *args):
        return len(self) if not args else super().count(*args)


def v1(methods, scope):
    def wrap(fn):
        fn = throttle_classes([ApiKeyThrottle])(fn)
        fn = permission_classes([scoped(scope)])(fn)
        fn = authentication_classes([ApiKeyAuthentication])(fn)
        return api_view(methods)(fn)

    return wrap


def _org(request):
    return request.auth.org


def _member_row(m) -> dict:
    from apps.orgs.api import _first

    return {
        "id": m.id,
        "user_id": m.user_id,
        "first_name": _first(m.user),
        "email": m.user.email,
        "role": m.role,
        "groups": [g.id for g in m.groups.all()],
        "joined_at": m.joined_at,
    }


@v1(["GET", "POST"], "read:members")
def members(request, slug):
    from apps.orgs.models import Membership

    if request.method == "POST":
        return _invite(request)
    qs = (
        Membership.objects.filter(org=_org(request))
        .select_related("user__profile")
        .prefetch_related("groups")
        .order_by("joined_at", "id")
    )
    return paged(request, qs, _member_row, name=f"members-{slug}")


def _invite(request):
    from apps.legal.mail import mail_ready
    from apps.orgs.api import InviteIn, email_invite, invite_allowance, invite_mail_out
    from apps.orgs.models import Group, Invitation

    key = request.auth
    if "write:members" not in (key.scopes or []):
        return Response({"detail": "missing_scope"}, status=status.HTTP_403_FORBIDDEN)
    ser = InviteIn(data={**request.data, "role": "learner"})  # keys invite learners only
    ser.is_valid(raise_exception=True)
    d, org = ser.validated_data, key.org
    if not key.created_by_id:
        return Response({"code": "key_owner_gone"}, status=status.HTTP_409_CONFLICT)
    emails = sorted({e.lower() for e in d["emails"]})
    left = invite_allowance(key.created_by, org)  # counted against the admin who made the key
    if len(emails) > left:
        return Response({"code": "invite_limit", "left": left}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    group = Group.objects.filter(id=d.get("group_id"), org=org).first() if d.get("group_id") else None
    unsent, ready = [], mail_ready()
    for email in emails:
        Invitation.objects.filter(
            org=org, email=email, accepted_at__isnull=True, cohort__isnull=True, unit__isnull=True
        ).delete()
        inv = Invitation.objects.create(
            org=org, email=email, role="learner", group=group, invited_by=key.created_by
        )
        if miss := email_invite(inv, f"You're invited to learn on Aasan with {org.name}.", ready):
            unsent.append(miss)
    return Response({"invited": emails, **invite_mail_out(unsent)}, status=status.HTTP_201_CREATED)


@v1(["DELETE"], "write:members")
def member_detail(request, slug, pk):
    from apps.orgs.api import _void_invites_by
    from apps.orgs.models import Invitation, Membership

    m = get_object_or_404(Membership.objects.select_related("user"), pk=pk, org=_org(request))
    if m.role != "learner":
        return Response({"code": "learners_only"}, status=status.HTTP_403_FORBIDDEN)
    with transaction.atomic():
        Invitation.objects.filter(org=m.org, email__iexact=m.user.email, accepted_at__isnull=True).delete()
        _void_invites_by(m, "learner", removed=True)
        m.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


def _assignment_row(a) -> dict:
    return {k: v for k, v in a.items() if k != "rows"}


@v1(["GET"], "read:progress")
def assignments(request, slug):
    from apps.orgs.api import ASSIGNMENT_RELATED, _assignments_out

    org = _org(request)
    rows = _assignments_out(org, org.assignments.select_related(*ASSIGNMENT_RELATED)[:500])
    return paged(request, _Rows(rows), _assignment_row, name=f"assignments-{slug}")


@v1(["GET"], "read:progress")
def assignment_progress(request, slug, pk):
    from apps.orgs.api import ASSIGNMENT_RELATED, _assignments_out
    from apps.orgs.models import Assignment

    org = _org(request)
    a = get_object_or_404(Assignment.objects.select_related(*ASSIGNMENT_RELATED), pk=pk, org=org)
    rows = _assignments_out(org, [a], with_rows=True)[0]["rows"]
    out = [{"first_name": r["name"], **{k: v for k, v in r.items() if k != "name"}} for r in rows]
    return paged(request, _Rows(out), lambda r: r, name=f"assignment-{pk}-progress")


def _cert_row(c) -> dict:
    from apps.credentials.services import verify_url

    return {
        "code": c.code,
        "kind": c.kind,
        "title": c.title,
        "learner_name": c.learner_name,
        "user_id": c.user_id,
        "issued_at": c.issued_at,
        "revoked": bool(c.revoked_at),
        "verify_url": verify_url(c),
    }


@v1(["GET"], "read:progress")
def certificates(request, slug):
    from apps.credentials.models import Certificate

    qs = Certificate.objects.filter(org=_org(request)).order_by("-issued_at", "-id")
    return paged(request, qs, _cert_row, name=f"certificates-{slug}")


@v1(["GET"], "read:progress")
def training_records(request, slug):
    from apps.orgs.models import TrainingRecord
    from apps.orgs.records import filtered, row

    qs = filtered(request, TrainingRecord.objects.filter(org=_org(request)))
    return paged(request, qs, row, name=f"training-records-{slug}")
