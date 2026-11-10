"""Milestone 9 — partner cohorts: courses only inside the access window; the end date ends access but keeps progress."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.learning.models import Enrollment, UserSubsectionState
from apps.orgs.models import Group, Invitation, Membership, Organization
from tests.test_school_units import client_for, course

pytestmark = pytest.mark.django_db


def iso(days):
    return (timezone.now() + timedelta(days=days)).isoformat()


@pytest.fixture
def org():
    admin, au = client_for("admin@co.in")
    au.email_verified = True
    au.save()
    o = Organization.objects.create(name="Partner Co", slug="pco", kind="company")
    Membership.objects.create(org=o, user=au, role="owner")
    g = Group.objects.create(org=o, name="Batch 1")
    kid, ku = client_for("kid@co.in")
    km = Membership.objects.create(org=o, user=ku, role="learner")
    g.members.add(km)
    cur = course(au, "Excel for partners")
    return o, admin, au, g, kid, ku, km, cur


def test_window_enforced_before_during_after(org):
    o, admin, au, g, kid, ku, km, cur = org
    r = admin.post(
        "/api/orgs/pco/cohorts/",
        {
            "name": "Spring",
            "partner": "NSDC",
            "starts_at": iso(2),
            "ends_at": iso(30),
            "course_ids": [cur.id],
        },
        format="json",
    )
    assert r.status_code == 201 and r.data["state"] == "upcoming"
    cid = r.data["id"]
    assert (
        admin.post(f"/api/orgs/pco/cohorts/{cid}/members/", {"group_ids": [g.id]}, format="json").data[
            "added"
        ]
        == 1
    )
    url = f"/api/learn/curriculums/{cur.id}/"
    assert kid.get(url).status_code == 404  # before start
    mine = kid.get("/api/orgs/me/cohorts/").data
    assert mine[0]["state"] == "upcoming" and mine[0]["courses"][0]["id"] == cur.id
    admin.patch(f"/api/orgs/pco/cohorts/{cid}/", {"starts_at": iso(-1)}, format="json")
    assert kid.get(url).status_code == 200  # inside the window
    UserSubsectionState.objects.create(
        user=ku, subsection=cur.sections.first().subsections.first(), status="completed"
    )
    admin.patch(f"/api/orgs/pco/cohorts/{cid}/", {"starts_at": iso(-10), "ends_at": iso(-1)}, format="json")
    assert kid.get(url).status_code == 404  # after end
    assert UserSubsectionState.objects.filter(user=ku, status="completed").exists()  # progress kept
    assert kid.get("/api/orgs/me/cohorts/").data[0]["state"] == "ended"


def test_another_users_active_window_does_not_leak(org):
    o, admin, au, g, kid, ku, km, cur = org
    other, ou = client_for("other@co.in")
    Membership.objects.create(org=o, user=ou, role="learner")
    Enrollment.objects.create(
        user=ou,
        curriculum=cur,
        access_from=timezone.now() - timedelta(days=1),
        access_until=timezone.now() + timedelta(days=9),
    )
    Enrollment.objects.create(
        user=ku,
        curriculum=cur,
        access_from=timezone.now() - timedelta(days=9),
        access_until=timezone.now() - timedelta(days=1),
    )
    assert other.get(f"/api/learn/curriculums/{cur.id}/").status_code == 200
    assert kid.get(f"/api/learn/curriculums/{cur.id}/").status_code == 404


def test_assignment_is_permanent_and_removal_ends_access(org):
    o, admin, au, g, kid, ku, km, cur = org
    c = admin.post(
        "/api/orgs/pco/cohorts/",
        {"name": "C", "starts_at": iso(-1), "ends_at": iso(5), "course_ids": [cur.id]},
        format="json",
    ).data
    admin.post(f"/api/orgs/pco/cohorts/{c['id']}/members/", {"emails": ["kid@co.in"]}, format="json")
    assert kid.get(f"/api/learn/curriculums/{cur.id}/").status_code == 200
    assert admin.delete(f"/api/orgs/pco/cohorts/{c['id']}/members/{km.id}/").status_code == 204
    assert kid.get(f"/api/learn/curriculums/{cur.id}/").status_code == 404
    # an assignment grants permanent access, even over a cohort window
    admin.post(f"/api/orgs/pco/cohorts/{c['id']}/members/", {"emails": ["kid@co.in"]}, format="json")
    admin.post("/api/orgs/pco/assignments/", {"curriculum_id": cur.id, "group_id": g.id}, format="json")
    e = Enrollment.objects.get(user=ku, curriculum=cur)
    assert e.access_from is None and e.access_until is None
    admin.delete(f"/api/orgs/pco/cohorts/{c['id']}/")
    assert kid.get(f"/api/learn/curriculums/{cur.id}/").status_code == 200


def test_invite_into_cohort_and_validation(org):
    o, admin, au, g, kid, ku, km, cur = org
    assert (
        admin.post(
            "/api/orgs/pco/cohorts/", {"name": "Bad", "starts_at": iso(5), "ends_at": iso(1)}, format="json"
        ).status_code
        == 400
    )
    other_course = course(client_for("outsider@x.in")[1], "Not ours")
    assert (
        admin.post(
            "/api/orgs/pco/cohorts/",
            {"name": "X", "starts_at": iso(0), "ends_at": iso(3), "course_ids": [other_course.id]},
            format="json",
        ).status_code
        == 400
    )
    c = admin.post(
        "/api/orgs/pco/cohorts/",
        {"name": "C", "starts_at": iso(-1), "ends_at": iso(5), "course_ids": [cur.id]},
        format="json",
    ).data
    r = admin.post(f"/api/orgs/pco/cohorts/{c['id']}/members/", {"emails": ["new@co.in"]}, format="json")
    assert r.data["invited"] == 1 and r.data["pending"] == ["new@co.in"]
    nc, _u = client_for("new@co.in")
    _u.email_verified = True  # accepting an invitation needs a verified email
    _u.save()
    assert (
        nc.post(f"/api/orgs/invites/{Invitation.objects.get(email='new@co.in').token}/accept/").status_code
        == 200
    )
    assert nc.get(f"/api/learn/curriculums/{cur.id}/").status_code == 200
    assert nc.get("/api/orgs/me/cohorts/").data[0]["ends_at"]


def test_cohort_permissions(org):
    o, admin, au, g, kid, ku, km, cur = org
    mgr, mu = client_for("mgr@co.in")
    Membership.objects.create(org=o, user=mu, role="manager")
    for c in (mgr, kid):
        assert c.get("/api/orgs/pco/cohorts/").status_code == 403
        assert (
            c.post(
                "/api/orgs/pco/cohorts/", {"name": "x", "starts_at": iso(0), "ends_at": iso(1)}, format="json"
            ).status_code
            == 403
        )
    stranger, _ = client_for("s@x.in")
    assert stranger.get("/api/orgs/pco/cohorts/").status_code == 404
    assert stranger.get("/api/orgs/me/cohorts/").data == []


def test_deleting_cohort_deletes_pending_invitations(org):
    o, admin, au, g, kid, ku, km, cur = org
    c = admin.post(
        "/api/orgs/pco/cohorts/",
        {"name": "C", "starts_at": iso(-1), "ends_at": iso(5), "course_ids": [cur.id]},
        format="json",
    ).data
    admin.post(f"/api/orgs/pco/cohorts/{c['id']}/members/", {"emails": ["later@co.in"]}, format="json")
    token = Invitation.objects.get(email="later@co.in").token
    admin.delete(f"/api/orgs/pco/cohorts/{c['id']}/")
    assert not Invitation.objects.filter(email="later@co.in").exists()
    lc, _ = client_for("later@co.in")
    assert (
        lc.post(f"/api/orgs/invites/{token}/accept/").status_code == 404
    )  # no silent plain-member invite left behind


def test_partner_gets_no_org_wide_assignments(org):
    o, admin, au, g, kid, ku, km, cur = org
    Group.objects.create(org=o, name="Everyone").members.add(km)
    admin.post("/api/orgs/pco/assignments/", {"curriculum_id": cur.id}, format="json")  # whole-org assignment
    c = admin.post(
        "/api/orgs/pco/cohorts/", {"name": "C", "starts_at": iso(-1), "ends_at": iso(5)}, format="json"
    ).data
    admin.post(f"/api/orgs/pco/cohorts/{c['id']}/members/", {"emails": ["p@co.in"]}, format="json")
    pc, pu = client_for("p@co.in")
    pu.email_verified = True  # accepting an invitation needs a verified email
    pu.save()
    pc.post(f"/api/orgs/invites/{Invitation.objects.get(email='p@co.in').token}/accept/")
    assert not Enrollment.objects.filter(user=pu, curriculum=cur).exists()
    assert pc.get(f"/api/learn/curriculums/{cur.id}/").status_code == 404
    assert pc.get("/api/orgs/me/assignments/").data == []
    assert kid.get(f"/api/learn/curriculums/{cur.id}/").status_code == 200


def test_review_cards_hidden_after_window_ends(org):
    from apps.learning.models import Activity
    from apps.review.models import ReviewCard

    o, admin, au, g, kid, ku, km, cur = org
    sub = cur.sections.first().subsections.first()
    act = Activity.objects.create(
        subsection=sub,
        order=1,
        type="quiz",
        title="Q",
        kind="lesson",
        payload={"prompt": "p", "options": ["a", "b"], "multiple": False},
        key={"correct": [0]},
    )
    c = admin.post(
        "/api/orgs/pco/cohorts/",
        {"name": "C", "starts_at": iso(-3), "ends_at": iso(5), "course_ids": [cur.id]},
        format="json",
    ).data
    admin.post(f"/api/orgs/pco/cohorts/{c['id']}/members/", {"group_ids": [g.id]}, format="json")
    card = ReviewCard.objects.create(user=ku, activity=act, due=timezone.now() - timedelta(hours=1))
    assert len(kid.get("/api/review/session/?mode=due").data["cards"]) == 1
    admin.patch(
        f"/api/orgs/pco/cohorts/{c['id']}/", {"starts_at": iso(-3), "ends_at": iso(-1)}, format="json"
    )
    for mode in ("due", "quick", "exam"):
        assert kid.get(f"/api/review/session/?mode={mode}").data["cards"] == []
    assert (
        kid.post(
            f"/api/review/cards/{card.id}/answer/", {"answer": {"selected": [0]}}, format="json"
        ).status_code
        == 404
    )
    assert kid.get("/api/review/overview/").data["due"] == 0
