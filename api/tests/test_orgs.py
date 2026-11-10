import csv
import io
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.game.models import Notification
from apps.learning.models import Enrollment, Subsection, UserSubsectionState
from apps.orgs.models import Invitation, Membership, SurveyResponse

pytestmark = pytest.mark.django_db
PW = "Org#2026passwd"


def user(email, name="X"):
    u = User.objects.create_user(email, PW)
    u.profile.display_name = name
    u.profile.save()
    c = APIClient()
    c.force_authenticate(u)
    return c, u


@pytest.fixture
def school():
    owner_c, owner = user("principal@school.in", "Meena Principal")
    slug = owner_c.post("/api/orgs/", {"name": "Sunrise School", "kind": "school"}, format="json").data[
        "slug"
    ]
    return owner_c, owner, slug


def add(slug, u, role):
    from apps.orgs.models import Organization

    return Membership.objects.create(org=Organization.objects.get(slug=slug), user=u, role=role)


def test_create_and_visibility(school):
    owner_c, _, slug = school
    assert slug == "sunrise-school"
    assert owner_c.get("/api/orgs/").data[0]["role"] == "owner"
    outsider, _ = user("x@x.in")
    assert outsider.get(f"/api/orgs/{slug}/").status_code == 404  # no existence leak
    learner_c, learner = user("kid@school.in", "Arun Kumar")
    add(slug, learner, "learner")
    assert learner_c.get(f"/api/orgs/{slug}/").status_code == 200
    for path in ("members", "analytics", "assignments", "surveys", "groups"):
        assert learner_c.get(f"/api/orgs/{slug}/{path}/").status_code == 403


def test_role_rules(school):
    owner_c, owner, slug = school
    mgr_c, mgr = user("teacher@school.in")
    m_mgr = add(slug, mgr, "manager")
    _, kid = user("kid@school.in")
    m_kid = add(slug, kid, "learner")
    assert (
        mgr_c.patch(f"/api/orgs/{slug}/members/{m_kid.id}/", {"role": "admin"}, format="json").status_code
        == 403
    )  # managers can't manage roles
    admin_c, admin = user("admin@school.in")
    add(slug, admin, "admin")
    assert (
        admin_c.patch(f"/api/orgs/{slug}/members/{m_mgr.id}/", {"role": "owner"}, format="json").status_code
        == 403
    )  # can't grant above own role
    assert (
        admin_c.patch(f"/api/orgs/{slug}/members/{m_kid.id}/", {"role": "manager"}, format="json").status_code
        == 200
    )
    owner_m = Membership.objects.get(user=owner)
    assert owner_c.delete(f"/api/orgs/{slug}/members/{owner_m.id}/").data["code"] == "last_owner"
    assert (
        owner_c.patch(f"/api/orgs/{slug}/members/{owner_m.id}/", {"role": "admin"}, format="json").data[
            "code"
        ]
        == "last_owner"
    )
    assert mgr_c.get("/api/lab/courses/").status_code == 200  # managers get Creator Lab


def test_join_code_and_invites(school):
    owner_c, _, slug = school
    g = owner_c.post(f"/api/orgs/{slug}/groups/", {"name": "Class 11-A"}, format="json").data
    code = next(x["join_code"] for x in g if x["name"] == "Class 11-A")
    kid_c, kid = user("kid@school.in")
    r = kid_c.post(f"/api/orgs/join/{code.lower()}/")
    assert r.status_code == 200 and r.data["role"] == "learner" and r.data["group"] == "Class 11-A"
    assert kid_c.post("/api/orgs/join/NOPE123/").status_code == 404
    owner_c.post(
        f"/api/orgs/{slug}/invitations/", {"emails": ["Teacher@School.in"], "role": "manager"}, format="json"
    )
    assert len(mail.outbox) == 1
    token = Invitation.objects.get().token
    wrong_c, _ = user("someone@else.in")
    assert wrong_c.post(f"/api/orgs/invites/{token}/accept/").data["code"] == "wrong_account"
    t_c, _u = user("teacher@school.in")
    _u.email_verified = True  # accepting an invitation needs a verified email
    _u.save()
    assert t_c.post(f"/api/orgs/invites/{token}/accept/").data["role"] == "manager"
    assert t_c.post(f"/api/orgs/invites/{token}/accept/").status_code == 404  # single use


def _authored_course(c):
    cid = c.post("/api/lab/courses/", {"goal": "Class AI basics", "mode": "ai"}, format="json").data["id"]
    for s in c.get(f"/api/lab/courses/{cid}/").data["sections"]:
        for b in s["subsections"]:
            c.post(f"/api/lab/subsections/{b['id']}/generate/")
    return cid


def test_assignments_progress_and_nudges(school):
    owner_c, _, slug = school
    cid = _authored_course(owner_c)
    groups = owner_c.post(f"/api/orgs/{slug}/groups/", {"name": "11-A"}, format="json").data
    gid = next(x["id"] for x in groups if x["name"] == "11-A")
    code = next(x["join_code"] for x in groups if x["name"] == "11-A")
    kid_c, kid = user("kid@school.in", "Arun")
    kid_c.post(f"/api/orgs/join/{code}/")
    r = owner_c.post(
        f"/api/orgs/{slug}/assignments/",
        {
            "curriculum_id": cid,
            "group_id": gid,
            "due_at": (timezone.now() - timedelta(days=1)).isoformat(),
            "note": "Finish by Friday",
        },
        format="json",
    )
    assert r.status_code == 201 and r.data["learners"] == 1 and r.data["overdue"] == 1
    assert Enrollment.objects.filter(user=kid, curriculum_id=cid).exists()
    assert Notification.objects.filter(user=kid, kind="assignment").exists()
    mine = kid_c.get("/api/orgs/me/assignments/").data
    assert mine[0]["course"]["id"] == cid and mine[0]["done"] == 0
    late_c, late = user("late@school.in", "Divya")  # joins after the assignment → enrolled automatically
    late_c.post(f"/api/orgs/join/{code}/")
    assert Enrollment.objects.filter(user=late, curriculum_id=cid).exists()
    sub = Subsection.objects.filter(section__curriculum_id=cid).first()
    UserSubsectionState.objects.create(
        user=kid, subsection=sub, status="completed", score=0.9, completed_at=timezone.now()
    )
    detail = owner_c.get(f"/api/orgs/{slug}/assignments/{r.data['id']}/").data
    arun = next(x for x in detail["rows"] if x["name"] == "Arun")
    assert arun["done"] == 1 and arun["avg_score"] == 0.9
    teacher_c, teacher = user("t2@school.in")
    add(slug, teacher, "manager")
    n = owner_c.post(
        f"/api/orgs/{slug}/nudge/",
        {"user_ids": [kid.id, teacher.id], "message": "You can do it!"},
        format="json",
    ).data
    assert n["nudged"] == 1  # only learners receive nudges
    assert Notification.objects.filter(user=kid, kind="nudge", body="You can do it!").exists()


def test_cannot_assign_someone_elses_course(school):
    owner_c, _, slug = school
    other_c, other = user("other@x.in")
    other.is_creator = True
    other.save()
    cid = _authored_course(other_c)
    assert (
        owner_c.post(f"/api/orgs/{slug}/assignments/", {"curriculum_id": cid}, format="json").status_code
        == 404
    )


def test_analytics_respects_privacy(school):
    owner_c, _, slug = school
    kid_c, kid = user("kid@school.in", "Arun")
    add(slug, kid, "learner")
    personal = kid_c.post("/api/learn/curriculums/", {"goal": "My private hobby course"}, format="json").data[
        "id"
    ]
    sub = Subsection.objects.filter(section__curriculum_id=personal).first()
    UserSubsectionState.objects.create(
        user=kid, subsection=sub, status="completed", score=1.0, completed_at=timezone.now()
    )
    a = owner_c.get(f"/api/orgs/{slug}/analytics/").data
    assert (
        a["kpis"]["learners"] == 1 and a["kpis"]["lessons_completed_30d"] == 0
    )  # personal course not visible
    assert a["at_risk"][0]["name"] == "Arun" and "inactive" in a["at_risk"][0]["reasons"]
    assert len(a["daily"]) == 30
    assert owner_c.post(f"/api/orgs/{slug}/insights/").data["actions"]


def test_surveys_anonymous_and_results(school):
    owner_c, owner, slug = school
    s = owner_c.post(f"/api/orgs/{slug}/surveys/", {"template": "course_feedback"}, format="json").data
    kids = []
    for i, (txt, rating) in enumerate(
        [("More examples please", 4), ("Too fast", 2), ("Loved the cricket bits", 5)]
    ):
        c, u = user(f"k{i}@school.in", f"Kid{i}")
        add(slug, u, "learner")
        kids.append((c, txt, rating))
    c0 = kids[0][0]
    assert (
        c0.post(f"/api/orgs/surveys/{s['id']}/respond/", {"answers": {"q1": 4}}, format="json").status_code
        == 404
    )  # draft
    owner_c.patch(f"/api/orgs/{slug}/surveys/{s['id']}/", {"status": "open"}, format="json")
    assert c0.get("/api/orgs/me/surveys/").data[0]["answered"] is False
    for c, txt, rating in kids:
        assert (
            c.post(
                f"/api/orgs/surveys/{s['id']}/respond/",
                {"answers": {"q1": rating, "q3": "Just right", "q4": txt}},
                format="json",
            ).status_code
            == 201
        )
    assert (
        c0.post(f"/api/orgs/surveys/{s['id']}/respond/", {"answers": {"q1": 3}}, format="json").status_code
        == 409
    )
    assert c0.post(
        f"/api/orgs/surveys/{s['id']}/respond/", {"answers": {"q1": 9}}, format="json"
    ).status_code in (400, 409)
    assert SurveyResponse.objects.filter(user__isnull=False).count() == 0  # anonymous: no user link stored
    r = owner_c.get(f"/api/orgs/{slug}/surveys/{s['id']}/results/").data
    q1 = next(x for x in r["results"] if x["id"] == "q1")
    assert r["responses"] == 3 and q1["avg"] == pytest.approx(3.67, 0.01)
    q4 = next(x for x in r["results"] if x["id"] == "q4")
    assert len(q4["answers"]) == 3 and all(a["name"] is None for a in q4["answers"])
    csv_resp = owner_c.get(f"/api/orgs/{slug}/surveys/{s['id']}/results/?export=csv")
    rows = list(csv.reader(io.StringIO(csv_resp.content.decode())))
    assert len(rows) == 4 and rows[1][0].startswith("#")  # no names in anonymous export
    assert owner_c.post(f"/api/orgs/{slug}/surveys/{s['id']}/summary/").data["themes"]
    assert (
        owner_c.post(
            f"/api/orgs/{slug}/surveys/",
            {"title": "Bad", "questions": [{"type": "choice", "text": "x", "options": ["only one"]}]},
            format="json",
        ).status_code
        == 400
    )


def test_org_llm_tasks_are_routable():
    """Every task name the orgs app sends to the router must map to a capability (forced-provider tests skip this)."""
    import re
    from pathlib import Path

    from apps.providers.catalog import TASK_CAPABILITY

    src = Path(__file__).resolve().parent.parent.joinpath("apps/orgs/api.py").read_text()
    tasks = set(re.findall(r'complete_json_sync\(\s*"(\w+)"', src))
    assert tasks and tasks <= set(TASK_CAPABILITY)
