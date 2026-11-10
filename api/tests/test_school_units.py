"""Milestone 9 — sub-units: unit-scoped admins manage only their unit; org admins keep full access."""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.learning.models import Curriculum, Section, Subsection
from apps.orgs.models import Group, Invitation, Membership, Organization, SubUnit, UnitAdmin
from apps.orgs.perms import make_unit_admin
from apps.paths.models import CareerPath

pytestmark = pytest.mark.django_db
PW = "School#Units2026"


def client_for(email):
    u = User.objects.create_user(email, PW)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def course(owner, title="Science 101", published=True):
    cur = Curriculum.objects.create(
        owner=owner,
        goal=title,
        title=title,
        kind="authored",
        status="ready",
        published_at=timezone.now() if published else None,
    )
    s = Section.objects.create(curriculum=cur, order=1, title="Intro")
    Subsection.objects.create(section=s, order=1, title="L1", lesson_status="ready")
    return cur


@pytest.fixture
def org():
    owner_c, owner = client_for("owner@unit.in")
    o = Organization.objects.create(name="Vidya", slug="vidya", kind="school")
    Membership.objects.create(org=o, user=owner, role="owner")
    Group.objects.create(org=o, name="Everyone")
    primary = SubUnit.objects.create(org=o, name="Primary")
    secondary = SubUnit.objects.create(org=o, name="Secondary")
    g1 = Group.objects.create(org=o, name="Class 3", unit=primary)
    g2 = Group.objects.create(org=o, name="Class 9", unit=secondary)
    kid_c, kid = client_for("kid@unit.in")
    km = Membership.objects.create(org=o, user=kid, role="learner")
    g1.members.add(km)
    teen_c, teen = client_for("teen@unit.in")
    g2.members.add(Membership.objects.create(org=o, user=teen, role="learner"))
    ua_c, ua = client_for("ua@unit.in")
    uam = Membership.objects.create(org=o, user=ua, role="learner")
    make_unit_admin(uam, primary)  # scoped explicitly; back to learner when the last unit goes
    return {
        "org": o,
        "owner": owner_c,
        "owner_u": owner,
        "primary": primary,
        "secondary": secondary,
        "g1": g1,
        "g2": g2,
        "ua": ua_c,
        "ua_u": ua,
        "kid": kid_c,
        "kid_u": kid,
    }


def test_org_admin_creates_unit_with_roles_coverage_groups(org):
    CareerPath.objects.get_or_create(slug="data-analyst", defaults={"title": "Data analyst", "summary": "s"})
    cur = course(org["owner_u"])
    o = org["owner"]
    r = o.post(
        "/api/orgs/vidya/units/",
        {
            "name": "Engineering",
            "target_roles": ["data-analyst"],
            "course_ids": [cur.id],
            "parent_id": org["secondary"].id,
        },
        format="json",
    )
    assert r.status_code == 201, r.data
    assert r.data["target_roles"][0]["slug"] == "data-analyst" and r.data["courses"][0]["id"] == cur.id
    assert (
        o.post("/api/orgs/vidya/units/", {"name": "X", "target_roles": ["nope"]}, format="json").status_code
        == 400
    )
    uid = r.data["id"]
    r = o.patch(f"/api/orgs/vidya/units/{uid}/", {"group_ids": [org["g2"].id]}, format="json")
    assert [g["id"] for g in r.data["groups"]] == [org["g2"].id]
    # no cycles: Secondary can't become a child of its own child
    assert (
        o.patch(
            f"/api/orgs/vidya/units/{org['secondary'].id}/", {"parent_id": uid}, format="json"
        ).status_code
        == 400
    )
    assert len(o.get("/api/orgs/vidya/units/").data["units"]) == 3


def test_unit_admin_sees_and_manages_only_own_unit(org):
    ua, p, s = org["ua"], org["primary"], org["secondary"]
    lst = ua.get("/api/orgs/vidya/units/").data
    assert lst["scoped"] is True and [u["id"] for u in lst["units"]] == [p.id]
    assert ua.get(f"/api/orgs/vidya/units/{p.id}/").status_code == 200
    assert ua.get(f"/api/orgs/vidya/units/{s.id}/").status_code == 404  # another unit: not even revealed
    assert ua.get(f"/api/orgs/vidya/units/{s.id}/learners/").status_code == 404
    assert (
        ua.post(f"/api/orgs/vidya/units/{s.id}/groups/", {"name": "Hack"}, format="json").status_code == 404
    )
    learners = ua.get(f"/api/orgs/vidya/units/{p.id}/learners/").data["learners"]
    assert [x["email"] for x in learners] == ["kid@unit.in"]
    assert (
        ua.post(f"/api/orgs/vidya/units/{p.id}/groups/", {"name": "Class 4"}, format="json").status_code
        == 201
    )
    assert Group.objects.get(name="Class 4").unit_id == p.id
    # unit admin may edit description / target roles, not admin-only fields
    assert (
        ua.patch(f"/api/orgs/vidya/units/{p.id}/", {"description": "Classes 1-5"}, format="json").status_code
        == 200
    )
    assert (
        ua.patch(f"/api/orgs/vidya/units/{p.id}/", {"group_ids": [org["g2"].id]}, format="json").status_code
        == 403
    )
    assert ua.patch(f"/api/orgs/vidya/units/{p.id}/", {"name": "Mine"}, format="json").status_code == 403
    assert ua.delete(f"/api/orgs/vidya/units/{p.id}/").status_code == 403
    assert ua.post("/api/orgs/vidya/units/", {"name": "New"}, format="json").status_code == 403
    assert (
        ua.post(f"/api/orgs/vidya/units/{p.id}/admins/", {"email": "x@y.in"}, format="json").status_code
        == 403
    )


def test_unit_admin_cannot_touch_org_wide_endpoints(org):
    ua = org["ua"]
    assert ua.patch("/api/orgs/vidya/settings/", {"display_name": "Hacked"}, format="json").status_code == 403
    assert (
        ua.get("/api/orgs/vidya/groups/").status_code == 403
    )  # org-wide manager endpoints refuse scoped managers
    assert ua.get("/api/orgs/vidya/members/").status_code == 403
    assert ua.get("/api/orgs/vidya/analytics/").status_code == 403
    assert ua.get("/api/orgs/vidya/cohorts/").status_code == 403
    d = ua.get("/api/orgs/vidya/").data
    assert d["scoped"] is True and d["units"] == [{"id": org["primary"].id, "name": "Primary"}]
    # the org admin is never scoped
    assert org["owner"].get("/api/orgs/vidya/groups/").status_code == 200
    assert org["owner"].get(f"/api/orgs/vidya/units/{org['secondary'].id}/").status_code == 200


def test_child_units_are_in_scope_and_learners_refused(org):
    child = SubUnit.objects.create(org=org["org"], name="Class 1-2", parent=org["primary"])
    assert org["ua"].get(f"/api/orgs/vidya/units/{child.id}/").status_code == 200
    assert org["kid"].get("/api/orgs/vidya/units/").status_code == 403
    assert org["kid"].get(f"/api/orgs/vidya/units/{child.id}/").status_code == 403
    other_c, _ = client_for("other@x.in")
    assert other_c.get("/api/orgs/vidya/units/").status_code == 404
    # a unit from another org is a 404 even for an org admin
    o2 = Organization.objects.create(name="Other", slug="other")
    foreign = SubUnit.objects.create(org=o2, name="Theirs")
    assert org["owner"].get(f"/api/orgs/vidya/units/{foreign.id}/").status_code == 404


def test_unit_assignments_respect_scope_and_coverage(org):
    ua, p = org["ua"], org["primary"]
    cur, other = course(org["owner_u"]), course(org["owner_u"], "Other")
    p.courses.set([cur])
    r = ua.post(
        f"/api/orgs/vidya/units/{p.id}/assignments/",
        {"curriculum_id": other.id, "group_id": org["g1"].id},
        format="json",
    )
    assert r.status_code == 404  # outside module coverage
    r = ua.post(
        f"/api/orgs/vidya/units/{p.id}/assignments/",
        {"curriculum_id": cur.id, "group_id": org["g2"].id},
        format="json",
    )
    assert r.status_code == 404  # another unit's class
    r = ua.post(
        f"/api/orgs/vidya/units/{p.id}/assignments/",
        {"curriculum_id": cur.id, "group_id": org["g1"].id},
        format="json",
    )
    assert r.status_code == 201 and r.data["learners"] == 1
    assert org["kid"].get(f"/api/learn/curriculums/{cur.id}/").status_code == 200
    aid = r.data["id"]
    assert len(ua.get(f"/api/orgs/vidya/units/{p.id}/assignments/").data) == 1
    assert ua.delete(f"/api/orgs/vidya/units/{org['secondary'].id}/assignments/{aid}/").status_code == 404
    assert ua.delete(f"/api/orgs/vidya/units/{p.id}/assignments/{aid}/").status_code == 204


def test_invite_unit_admin_existing_member_and_by_email(org, settings):
    o, s = org["owner"], org["secondary"]
    r = o.post(f"/api/orgs/vidya/units/{s.id}/admins/", {"email": "kid@unit.in"}, format="json")
    assert r.status_code == 201
    m = Membership.objects.get(user=org["kid_u"])
    assert m.role == "manager" and UnitAdmin.objects.filter(unit=s, membership=m).exists()
    assert (
        o.post(f"/api/orgs/vidya/units/{s.id}/admins/", {"email": "owner@unit.in"}, format="json").data[
            "code"
        ]
        == "already_org_admin"
    )
    org["owner_u"].email_verified = True
    org["owner_u"].save()
    r = o.post(f"/api/orgs/vidya/units/{s.id}/admins/", {"email": "newteacher@unit.in"}, format="json")
    assert r.status_code == 201 and r.data["pending_admins"] == ["newteacher@unit.in"]
    inv = Invitation.objects.get(email="newteacher@unit.in")
    nc, _u = client_for("newteacher@unit.in")
    _u.email_verified = True  # accepting an invitation needs a verified email
    _u.save()
    assert nc.post(f"/api/orgs/invites/{inv.token}/accept/").status_code == 200
    assert nc.get(f"/api/orgs/vidya/units/{s.id}/").status_code == 200
    assert nc.get(f"/api/orgs/vidya/units/{org['primary'].id}/").status_code == 404
    assert o.delete(f"/api/orgs/vidya/units/{s.id}/admins/{m.id}/").status_code == 204


def test_course_options_admin_only(org):
    cur = course(org["owner_u"])
    assert [c["id"] for c in org["owner"].get("/api/orgs/vidya/course-options/").data] == [cur.id]
    assert org["ua"].get("/api/orgs/vidya/course-options/").status_code == 403
    assert org["kid"].get("/api/orgs/vidya/course-options/").status_code == 403


# ── Security regressions ─────────────────────────────────────────────


def test_removing_last_unit_demotes_instead_of_widening(org):
    o, ua, p = org["owner"], org["ua"], org["primary"]
    mid = Membership.objects.get(user=org["ua_u"]).id
    assert o.delete(f"/api/orgs/vidya/units/{p.id}/admins/{mid}/").status_code == 204
    m = Membership.objects.get(pk=mid)
    assert m.role == "learner" and not m.unit_scoped
    for url in (
        "/api/orgs/vidya/groups/",
        "/api/orgs/vidya/members/",
        "/api/orgs/vidya/analytics/",
        "/api/orgs/vidya/units/",
    ):
        assert ua.get(url).status_code == 403, url


def test_deleting_a_unit_demotes_its_admins_and_keeps_scope_while_units_remain(org):
    o, ua, p, s = org["owner"], org["ua"], org["primary"], org["secondary"]
    m = Membership.objects.get(user=org["ua_u"])
    make_unit_admin(m, s)
    assert o.delete(f"/api/orgs/vidya/units/{p.id}/").status_code == 204
    m.refresh_from_db()
    assert m.role == "manager" and m.unit_scoped  # still admin of Secondary — still scoped
    assert ua.get("/api/orgs/vidya/groups/").status_code == 403
    child = SubUnit.objects.create(org=org["org"], name="Child", parent=s)
    make_unit_admin(m, child)
    s.delete()  # parent delete cascades to the child unit and both admin rows
    m.refresh_from_db()
    assert m.role == "learner" and not m.unit_scoped
    assert ua.get("/api/orgs/vidya/groups/").status_code == 403


def test_org_wide_manager_made_unit_admin_returns_to_manager(org):
    mc, mu = client_for("teacher@unit.in")
    m = Membership.objects.create(org=org["org"], user=mu, role="manager")
    org["owner"].post(
        f"/api/orgs/vidya/units/{org['primary'].id}/admins/", {"email": "teacher@unit.in"}, format="json"
    )
    assert mc.get("/api/orgs/vidya/groups/").status_code == 403  # scoped now
    org["owner"].delete(f"/api/orgs/vidya/units/{org['primary'].id}/admins/{m.id}/")
    m.refresh_from_db()
    assert m.role == "manager" and not m.unit_scoped and mc.get("/api/orgs/vidya/groups/").status_code == 200


def test_invited_unit_admin_goes_back_to_learner(org):
    org["owner_u"].email_verified = True
    org["owner_u"].save()
    org["owner"].post(
        f"/api/orgs/vidya/units/{org['secondary'].id}/admins/", {"email": "fresh@unit.in"}, format="json"
    )
    nc, nu = client_for("fresh@unit.in")
    nu.email_verified = True  # accepting an invitation needs a verified email
    nu.save()
    nc.post(f"/api/orgs/invites/{Invitation.objects.get(email='fresh@unit.in').token}/accept/")
    m = Membership.objects.get(user=nu)
    assert m.unit_scoped and m.role == "manager" and nc.get("/api/orgs/vidya/groups/").status_code == 403
    UnitAdmin.objects.filter(membership=m).delete()
    m.refresh_from_db()
    assert m.role == "learner" and nc.get("/api/orgs/vidya/groups/").status_code == 403


def test_private_drafts_of_other_members_cannot_be_assigned_or_listed(org):
    o, ua, p = org["owner"], org["ua"], org["primary"]
    tc, tu = client_for("t2@unit.in")
    Membership.objects.create(org=org["org"], user=tu, role="manager")
    draft = course(tu, "Teacher's private draft", published=False)
    own_draft = course(org["owner_u"], "Owner draft", published=False)
    # a unit with no coverage: unit admin can't reach other people's drafts
    r = ua.post(
        f"/api/orgs/vidya/units/{p.id}/assignments/",
        {"curriculum_id": draft.id, "group_id": org["g1"].id},
        format="json",
    )
    assert r.status_code == 404
    assert all(c["id"] != draft.id for c in o.get("/api/orgs/vidya/course-options/").data)
    assert (
        o.patch(f"/api/orgs/vidya/units/{p.id}/", {"course_ids": [draft.id]}, format="json").status_code
        == 400
    )
    # coverage holding the org admin's own unpublished draft: the unit admin can't publish it as a side effect
    assert (
        o.patch(f"/api/orgs/vidya/units/{p.id}/", {"course_ids": [own_draft.id]}, format="json").status_code
        == 200
    )
    r = ua.post(
        f"/api/orgs/vidya/units/{p.id}/assignments/",
        {"curriculum_id": own_draft.id, "group_id": org["g1"].id},
        format="json",
    )
    assert r.status_code == 409 and r.data["code"] == "not_published"
    own_draft.refresh_from_db()
    assert own_draft.published_at is None and own_draft.visibility == "private"
    # older org-wide assignment path and cohorts follow the same rule
    assert (
        o.post("/api/orgs/vidya/assignments/", {"curriculum_id": draft.id}, format="json").status_code == 404
    )
    from datetime import timedelta

    s, e = timezone.now().isoformat(), (timezone.now() + timedelta(days=5)).isoformat()
    assert (
        o.post(
            "/api/orgs/vidya/cohorts/",
            {"name": "C", "starts_at": s, "ends_at": e, "course_ids": [draft.id]},
            format="json",
        ).status_code
        == 400
    )
    draft.refresh_from_db()
    assert draft.published_at is None


def test_deck_export_only_for_author_or_org_template(org):
    from apps.orgs.models import Assignment

    cur = course(org["owner_u"])
    Assignment.objects.create(
        org=org["org"], group=org["g1"], curriculum=cur
    )  # assigned to the unit admin's class
    assert (
        org["ua"].get(f"/api/studio/courses/{cur.id}/export.pptx").status_code == 404
    )  # decks carry keys: not unlocked by assigning
    cur.template_scope, cur.template_org = "org", org["org"]
    cur.save()
    # Org templates' decks (answer keys) are for org-wide staff only: a unit-scoped admin is refused (S35)
    assert org["ua"].get(f"/api/studio/courses/{cur.id}/export.pptx").status_code == 404
    admin_c, admin_u = client_for("admin@unit.in")
    Membership.objects.create(org=org["org"], user=admin_u, role="admin")
    assert (
        admin_c.get(f"/api/studio/courses/{cur.id}/export.pptx").status_code == 200
    )  # this org's own template
    assert org["kid"].get(f"/api/studio/courses/{cur.id}/export.pptx").status_code == 404


def test_explicit_role_changes_end_the_unit_arrangement(org):
    o, p = org["owner"], org["primary"]
    # (a) former org-wide manager made unit admin, then demoted to learner: deleting the unit must not restore manager
    mc, mu = client_for("former@unit.in")
    m = Membership.objects.create(org=org["org"], user=mu, role="manager")
    make_unit_admin(m, p)
    assert o.patch(f"/api/orgs/vidya/members/{m.id}/", {"role": "learner"}, format="json").status_code == 200
    m.refresh_from_db()
    assert m.role == "learner" and not m.unit_scoped and not m.unit_roles.exists()
    assert o.delete(f"/api/orgs/vidya/units/{p.id}/").status_code == 204
    m.refresh_from_db()
    assert m.role == "learner" and mc.get("/api/orgs/vidya/members/").status_code == 403
    # (b) unit admin promoted to org admin is not demoted when their unit goes
    s = org["secondary"]
    am = Membership.objects.get(user=org["ua_u"])
    make_unit_admin(am, s)
    assert o.patch(f"/api/orgs/vidya/members/{am.id}/", {"role": "admin"}, format="json").status_code == 200
    s.delete()
    am.refresh_from_db()
    assert am.role == "admin" and not am.unit_scoped


def test_link_shared_courses_elsewhere_are_not_assignable_by_id(org):
    from datetime import timedelta

    from apps.orgs.courses import assignable_courses
    from apps.orgs.models import Assignment
    from apps.orgs.teach import can_see_keys

    victim_c, victim = client_for("victim@else.in")
    vc = course(victim, "Victim's unlisted course")
    vc.visibility = "link"
    vc.save()
    o, p = org["owner"], org["primary"]
    assert not assignable_courses(org["org"], org["owner_u"]).filter(pk=vc.id).exists()
    assert (
        o.post(
            f"/api/orgs/vidya/units/{p.id}/assignments/",
            {"curriculum_id": vc.id, "group_id": org["g1"].id},
            format="json",
        ).status_code
        == 404
    )
    assert o.post("/api/orgs/vidya/assignments/", {"curriculum_id": vc.id}, format="json").status_code == 404
    s, e = timezone.now().isoformat(), (timezone.now() + timedelta(days=5)).isoformat()
    assert (
        o.post(
            "/api/orgs/vidya/cohorts/",
            {"name": "C", "starts_at": s, "ends_at": e, "course_ids": [vc.id]},
            format="json",
        ).status_code
        == 400
    )
    assert (
        o.patch(f"/api/orgs/vidya/units/{p.id}/", {"course_ids": [vc.id]}, format="json").status_code == 400
    )
    assert org["kid"].get(f"/api/learn/curriculums/{vc.id}/").status_code == 404
    # an admin re-assigning someone else's course doesn't make it "shared" with the org
    Assignment.objects.create(org=org["org"], curriculum=vc, created_by=org["owner_u"])
    assert not assignable_courses(org["org"], org["owner_u"]).filter(pk=vc.id).exists()
    # catalog-approved: assignable, but keys stay hidden (even for an org owner); own course / own-org template: keys
    vc.catalog_status = "approved"
    vc.save()
    assert assignable_courses(org["org"], org["owner_u"]).filter(pk=vc.id).exists()
    me = Membership.objects.get(user=org["owner_u"])
    assert can_see_keys(me, Assignment(org=org["org"], curriculum=vc)) is False
    own = course(org["owner_u"], "Own")
    assert can_see_keys(me, Assignment(org=org["org"], curriculum=own)) is True
    tpl = course(victim, "Their template here")
    tpl.template_scope, tpl.template_org = "org", org["org"]
    tpl.save()
    assert can_see_keys(me, Assignment(org=org["org"], curriculum=tpl)) is True
    assert victim_c.get(f"/api/learn/curriculums/{vc.id}/").status_code == 200
