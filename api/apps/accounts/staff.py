"""Admin console roles and audit trail.

Roles: superadmin (everything, incl. staff and system settings), support (users, organisations, reports, help),
finance (payments, plans, codes, invoices, refunds), content (catalog, workshops, certificates). Access is decided per
admin section from the request path, so every /api/admin/ endpoint is covered by one table — a new endpoint without an
entry is superadmin-only until it is added here."""

import json
import logging

from django.conf import settings
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission

log = logging.getLogger(__name__)
ADMIN_PREFIX = "/api/admin/"

# First matching prefix wins (more specific first). Superadmin may always enter; () means superadmin only.
SECTION_ROLES: list[tuple[str, tuple[str, ...]]] = [
    ("overview/", ("support", "finance", "content")),
    ("model-prices/", ("finance",)),
    ("system-check/", ()),
    ("providers/", ()),
    ("features/", ("content",)),  # lesson media switches (podcast, explainer, Listen)
    ("site/", ()),
    ("mail/", ()),
    ("calendar-apps/", ()),
    ("staff/", ()),
    ("audit/", ()),
    ("catalog/", ("content",)),
    ("creators/", ("content", "support")),
    ("payments/", ("finance",)),
    ("plans/", ("finance",)),
    ("promos/", ("finance",)),
    ("redeem-codes/", ("finance",)),
    ("invoices/", ("finance",)),
    ("refunds/", ("finance",)),
    ("family-groups/", ("finance", "support")),
    ("gifts/", ("finance",)),
    ("reports/", ("support",)),
    ("help/", ("support", "content")),
    ("workshops/orgs/", ("support",)),
    ("workshops/", ("content",)),
    ("users/", ("support", "finance")),
    ("orgs/", ("support", "finance")),
    ("certificate-templates/", ("content",)),
    ("certificates/", ("content", "support")),
]

SECRET_KEYS = ("secret", "password", "key", "token", "otp", "code_hash", "authorization")


def roles_of(user) -> set[str]:
    if not getattr(user, "is_authenticated", False) or not (user.is_staff or user.is_superuser):
        return set()
    if user.is_superuser:
        return {"superadmin"}
    from .models import StaffRole

    row = StaffRole.objects.filter(user=user).first()
    if row is None:
        return (
            set()
        )  # fail closed: roles are granted by make_admin or the console (migration 0013 backfilled)
    return {r for r in row.roles if r in StaffRole.ROLES}


def section_of(path: str) -> tuple[str, tuple[str, ...]] | None:
    if not path.startswith(ADMIN_PREFIX):
        return None
    rest = path[len(ADMIN_PREFIX) :]
    for prefix, roles in SECTION_ROLES:
        if rest.startswith(prefix):
            return prefix.rstrip("/"), roles
    return "", ()


def may_enter(user, path: str) -> bool:
    roles = roles_of(user)
    if not roles:
        return False
    if "superadmin" in roles:
        return True
    sec = section_of(path)
    if sec is None:  # staff-only endpoints outside the admin console (exports etc.): any staff role
        return True
    return bool(roles & set(sec[1]))


def has_role(user, *wanted: str) -> bool:
    roles = roles_of(user)
    return "superadmin" in roles or bool(roles & set(wanted))


class AdminSection(BasePermission):
    """Use instead of IsAdminUser on admin endpoints. Changes also need a recent sign-in (ADMIN_REAUTH_MINUTES), so a
    stolen staff session alone can't alter the platform; the web answers `reauth_required` with its re-auth dialog."""

    def has_permission(self, request, view):
        if not may_enter(request.user, request.path):
            return False
        minutes = settings.ADMIN_REAUTH_MINUTES
        if request.method not in SAFE_METHODS and minutes:
            from .passkeys import _reauth_methods, needs_second_factor
            from .tokens import recently_authenticated, strongly_authenticated

            if not recently_authenticated(request, within=minutes * 60) or (
                needs_second_factor(request.user) and not strongly_authenticated(request)
            ):
                from .security_log import security_event

                security_event("admin_reauth_required", user_id=request.user.pk, path=request.path[:200])
                raise PermissionDenied({"code": "reauth_required", "methods": _reauth_methods(request.user)})
        return True


def _mask(value, depth=0):
    if depth > 4:
        return "…"
    if isinstance(value, dict):
        return {
            k: (
                "•••"
                if any(s in k.lower() for s in SECRET_KEYS) and v not in ("", None)
                else _mask(v, depth + 1)
            )
            for k, v in list(value.items())[:50]
        }
    if isinstance(value, list):
        return [_mask(v, depth + 1) for v in value[:50]]
    if isinstance(value, str):
        return value[:300]
    return value


def _client_ip(request) -> str | None:
    from rest_framework.throttling import BaseThrottle

    try:
        ip = BaseThrottle().get_ident(request)  # honours NUM_PROXIES like the throttles do
    except Exception:  # noqa: BLE001
        ip = request.META.get("REMOTE_ADDR")
    return (ip or "").split(",")[0].strip()[:45] or None


class AdminAudit:
    """Middleware: records every non-GET admin request that reached a view (any status but 401/403/404/405), after the
    response, with the authenticated staff user DRF attached to the request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        audited = request.path.startswith(ADMIN_PREFIX) and request.method not in ("GET", "HEAD", "OPTIONS")
        body = None
        if audited:
            try:
                body = json.loads(request.body or b"{}") if request.content_type == "application/json" else {}
            except Exception:  # noqa: BLE001 — bad or oversized JSON: the view answers it, we just log no body
                body = {}
        response = self.get_response(request)
        if audited and response.status_code not in (401, 403, 404, 405):
            try:
                self._record(request, response, body)
            except Exception:
                log.exception("admin audit write failed")
        return response

    def _record(self, request, response, body):
        from .models import AdminAuditLog

        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False):
            return
        sec = section_of(request.path)
        kwargs = getattr(getattr(request, "resolver_match", None), "kwargs", {}) or {}
        AdminAuditLog.objects.create(
            actor=user,
            actor_email=user.email,
            method=request.method,
            path=request.path[:300],
            section=(sec[0] if sec else "")[:40],
            target=" ".join(f"{k}={v}" for k, v in kwargs.items())[:80],
            data=_mask(body if isinstance(body, dict) else {"_": body}),
            status=response.status_code,
            ip=_client_ip(request),
            request_id=str(getattr(request, "request_id", "") or request.META.get("HTTP_X_REQUEST_ID", ""))[
                :64
            ],
        )
