"""Role checks. Higher roles include lower ones: owner > admin > manager > learner."""

from django.http import Http404
from rest_framework.exceptions import PermissionDenied

from .models import Membership, Organization

RANK = {"learner": 0, "manager": 1, "admin": 2, "owner": 3}


def membership(user, slug) -> Membership:
    m = Membership.objects.select_related("org").filter(org__slug=slug, user=user).first()
    if not m:
        raise Http404  # don't reveal that an org exists to non-members
    if m.org.suspended_at:
        raise PermissionDenied("org_suspended")
    return m


def require(user, slug, role: str) -> Membership:
    m = membership(user, slug)
    if RANK[m.role] < RANK[role]:
        raise PermissionDenied("insufficient_role")
    if role == "manager" and m.role == "manager" and is_unit_scoped(m):
        raise PermissionDenied(
            "unit_scoped"
        )  # unit admins manage only their unit (see unit_scope), never the whole org
    return m


# ── Sub-unit scope (Milestone 9) ──────────────────────────────────────


def is_unit_scoped(m: Membership) -> bool:
    """A manager made admin of one or more units is limited to them. Stored explicitly (Membership.unit_scoped): losing
    the last unit demotes them (signals.release_scope) instead of silently widening them to an org-wide manager."""
    return m.role == "manager" and m.unit_scoped


def staff_org_ids(user):
    """Orgs where the user has org-wide staff powers (owner/admin, or an unscoped manager)."""
    return (
        Membership.objects.filter(user=user, role__in=["owner", "admin", "manager"])
        .exclude(role="manager", unit_scoped=True)
        .values_list("org_id", flat=True)
    )


def make_unit_admin(m: Membership, unit, prior: str | None = None) -> None:
    """Give a learner/manager admin rights over one unit (scoped). Org admins/owners are never narrowed."""
    from .models import UnitAdmin

    if is_org_admin(m):
        return
    if not m.unit_scoped:
        m.prior_role, m.role, m.unit_scoped = prior or m.role, "manager", True
        m.save(update_fields=["prior_role", "role", "unit_scoped"])
    UnitAdmin.objects.get_or_create(unit=unit, membership=m)


def is_org_admin(m: Membership) -> bool:
    return RANK[m.role] >= RANK["admin"]


def managed_unit_ids(m: Membership) -> set[int]:
    """Units this member may manage: every unit for org admins; otherwise their units plus all descendants."""
    from .models import SubUnit

    rows = list(SubUnit.objects.filter(org_id=m.org_id).values_list("id", "parent_id"))
    if is_org_admin(m):
        return {i for i, _ in rows}
    allowed = set(m.unit_roles.values_list("unit_id", flat=True))
    children: dict[int | None, list[int]] = {}
    for i, p in rows:
        children.setdefault(p, []).append(i)
    stack = list(allowed)
    while stack:  # walk down the tree (cycles are impossible: parents are validated on save)
        for c in children.get(stack.pop(), []):
            if c not in allowed:
                allowed.add(c)
                stack.append(c)
    return allowed


def unit_scope(user, slug, unit_id: int | None = None, *, admin_only: bool = False):
    """Permission helper for unit endpoints. Returns (membership, unit or None).

    Org owners/admins: full access to every unit. Unit admins: only their unit(s) and child units, and never
    `admin_only` actions (creating units, assigning groups, inviting unit admins, coverage). Everyone else: refused.
    A unit of another org — or one outside the caller's scope — is a 404 (don't reveal it exists)."""
    from .models import SubUnit

    m = membership(user, slug)
    if is_org_admin(m):
        unit = None
        if unit_id is not None:
            unit = SubUnit.objects.filter(pk=unit_id, org_id=m.org_id).first()
            if not unit:
                raise Http404
        return m, unit
    if admin_only or not is_unit_scoped(m):  # a demoted learner keeps no unit powers
        raise PermissionDenied("insufficient_role")
    if unit_id is None:
        return m, None
    if unit_id not in managed_unit_ids(m):
        raise Http404
    return m, SubUnit.objects.get(pk=unit_id)


def can_author_via_org(user) -> bool:
    """Org owners/admins/managers get Creator Lab access (as agreed in Phase 6)."""
    return Membership.objects.filter(user=user, role__in=["owner", "admin", "manager"]).exists()


def org_of(slug) -> Organization:
    return Organization.objects.get(slug=slug)
