"""Org-admin screens for Connect Claude: server URL, connected clients (revoke), audit log."""

from urllib.parse import urlsplit

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.orgs.perms import require

from .models import ConnectAuditLog, Grant
from .oauth import _admin_orgs, resource_url, revoke_grant
from .tools import TOOLS


def _who(user) -> str:
    p = getattr(user, "profile", None) if user else None
    return ((getattr(p, "display_name", "") or "").strip() or "Admin")[:80] if user else ""


@api_view(["GET"])
def me(request):
    orgs = _admin_orgs(request.user)
    if not orgs:
        raise PermissionDenied("not_org_admin")
    return Response(
        {
            "server_url": resource_url(),
            "orgs": orgs,
            "tools": [{"name": n, "title": t["title"]} for n, t in TOOLS.items()],
        }
    )


def _grant_out(g: Grant, me_id: int) -> dict:
    hosts = sorted({urlsplit(u).hostname or "" for u in g.client.redirect_uris})
    return {
        "id": g.id,
        "client_name": g.client.name,
        "redirect_hosts": hosts,
        "approved_by": _who(g.user),
        "mine": g.user_id == me_id,
        "created_at": g.created_at,
        "last_used_at": g.last_used_at,
        "calls": g.audit.filter(event="tool").count(),
    }


@api_view(["GET"])
def clients(request, slug):
    m = require(request.user, slug, "admin")
    qs = Grant.objects.filter(org=m.org, revoked_at__isnull=True).select_related("client", "user__profile")[
        :100
    ]
    return Response([_grant_out(g, request.user.id) for g in qs])


@api_view(["DELETE"])
def client_detail(request, slug, pk):
    m = require(request.user, slug, "admin")
    g = get_object_or_404(Grant, pk=pk, org=m.org, revoked_at__isnull=True)
    revoke_grant(g, "user", by=request.user)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
def audit(request, slug):
    m = require(request.user, slug, "admin")
    try:
        page = max(1, min(int(request.query_params.get("page", 1)), 1000))
    except ValueError:
        page = 1
    size = 50
    qs = ConnectAuditLog.objects.filter(org=m.org).select_related("user__profile")
    total = qs.count()
    rows = qs[(page - 1) * size : page * size]
    return Response(
        {
            "total": total,
            "page": page,
            "pages": (total + size - 1) // size,
            "rows": [
                {
                    "id": r.id,
                    "event": r.event,
                    "client_name": r.client_name,
                    "user": _who(r.user),
                    "tool": r.tool,
                    "args": r.args_summary,
                    "ok": r.ok,
                    "error": r.error,
                    "created_at": r.created_at,
                }
                for r in rows
            ],
        }
    )
