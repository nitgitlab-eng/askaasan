"""M9 teacher tools: assignments v2 (scenarios, mandatory, survey hook), role-play analytics, answer drill-down with keys,
AI insights / misconceptions (cached + charged), pilot KPI report and its PDF/PPTX exports."""

import io
import zipfile
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.game.models import XPEvent
from apps.learning.models import Activity, ActivityAttempt, LessonFeedback, Subsection, UserSubsectionState
from apps.orgs.models import Group, Membership, Organization, SurveyResponse, TeachInsight
from apps.providers.models import UsageCounter
from apps.roleplay.models import RolePlaySession, Scenario

pytestmark = pytest.mark.django_db
PW = "Teach#2026passwd"


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
    owner_c, owner = user("principal@school.in", "Meena")
    slug = owner_c.post("/api/orgs/", {"name": "Sunrise School", "kind": "school"}, format="json").data[
        "slug"
    ]
    org = Organization.objects.get(slug=slug)
    ga, gb = Group.objects.create(org=org, name="7-A"), Group.objects.create(org=org, name="7-B")
    ta_c, ta = user("ta@school.in", "Anitha")
    member(org, ta, "manager", ga)
    tb_c, tb = user("tb@school.in", "Bala")
    member(org, tb, "manager", gb)
    ka_c, ka = user("ka@school.in", "=HYPERLINK(evil)")  # formula-looking name must stay text in exports
    member(org, ka, "learner", ga)
    kb_c, kb = user("kb@school.in", "Kavin")
    member(org, kb, "learner", gb)
    return {
        "slug": slug,
        "org": org,
        "ga": ga,
        "gb": gb,
        "owner": (owner_c, owner),
        "ta": (ta_c, ta),
        "tb": (tb_c, tb),
        "ka": (ka_c, ka),
        "kb": (kb_c, kb),
    }


def _scenario(owner):
    return Scenario.objects.create(
        source="custom",
        owner=owner,
        title="Calm a worried parent",
        summary="s",
        learner_role="Teacher",
        character={"name": "Mrs. Rao", "persona": "worried", "goal": "g", "style": "s"},
        setting="PTA",
        objectives=["Listen", "Agree next step"],
        competencies=[{"name": "Empathy", "description": "d"}],
        opening_line="Hello?",
    )


def _result(score):
    return {
        "overall": score,
        "competencies": [{"name": "Empathy", "score": 3, "evidence": [], "comment": ""}],
        "objectives": [{"text": "Listen", "met": True}],
        "strengths": ["Warm greeting"],
        "improvements": ["Close clearly"],
        "better_phrasing": [],
        "summary": "Good start.",
    }


def _session(u, sc, score=None, assignment="auto"):
    """Like POST /roleplay/sessions/: linked to the learner's newest assignment of this scenario (None = personal practice)."""
    if assignment == "auto":
        from apps.orgs.api import learner_assignments

        assignment = learner_assignments(u).filter(scenario=sc).order_by("-created_at").first()
    s = RolePlaySession.objects.create(
        user=u,
        scenario=sc,
        status="completed" if score is not None else "active",
        result=_result(score) if score is not None else None,
        assignment=assignment,
    )
    if score is not None:
        s.ended_at = s.started_at + timedelta(minutes=4)
        s.save()
    return s


def _course(c):
    cid = c.post("/api/lab/courses/", {"goal": "Class AI basics", "mode": "ai"}, format="json").data["id"]
    for s in c.get(f"/api/lab/courses/{cid}/").data["sections"]:
        for b in s["subsections"]:
            c.post(f"/api/lab/subsections/{b['id']}/generate/")
    return cid


def _survey(owner_c, slug, nps=False):
    body = {
        "title": "How was the training?",
        "questions": [
            {"id": "q1", "type": "nps" if nps else "rating", "text": "Recommend us?", "required": True}
        ],
    }
    s = owner_c.post(f"/api/orgs/{slug}/surveys/", body, format="json").data
    owner_c.patch(f"/api/orgs/{slug}/surveys/{s['id']}/", {"status": "open"}, format="json")
    return s["id"]


# ── Assignments v2 ───────────────────────────────────────────────────


def test_assign_scenario_mandatory_overdue_and_access(school):
    owner_c, owner = school["owner"]
    slug = school["slug"]
    sc = _scenario(owner)
    r = owner_c.post(
        f"/api/orgs/{slug}/assignments/",
        {
            "scenario_id": sc.id,
            "group_id": school["ga"].id,
            "mandatory": True,
            "due_at": (timezone.now() - timedelta(days=1)).isoformat(),
        },
        format="json",
    )
    assert (
        r.status_code == 201
        and r.data["kind"] == "scenario"
        and r.data["mandatory"] is True
        and r.data["overdue"] == 1
    )
    ka_c, ka = school["ka"]
    mine = ka_c.get("/api/orgs/me/assignments/").data
    assert (
        mine[0]["kind"] == "scenario"
        and mine[0]["scenario"]["id"] == sc.id
        and mine[0]["mandatory"]
        and mine[0]["overdue"]
    )
    assert mine[0]["status"] == "not_started"
    kb_c, _ = school["kb"]
    assert kb_c.get("/api/orgs/me/assignments/").data == []  # other class
    assert (
        ka_c.post("/api/roleplay/sessions/", {"scenario_id": sc.id}, format="json").status_code == 201
    )  # assigned → may start
    assert kb_c.post("/api/roleplay/sessions/", {"scenario_id": sc.id}, format="json").status_code == 404
    assert ka_c.get("/api/orgs/me/assignments/").data[0]["status"] == "in_progress"
    # validation: exactly one target; someone else's scenario can't be assigned
    assert owner_c.post(f"/api/orgs/{slug}/assignments/", {}, format="json").status_code == 400
    _, stranger = user("x@else.in")
    assert (
        owner_c.post(
            f"/api/orgs/{slug}/assignments/", {"scenario_id": _scenario(stranger).id}, format="json"
        ).status_code
        == 404
    )
    # a class survey can't be linked to an assignment for a different class
    sid = _survey(owner_c, slug)
    from apps.orgs.models import Survey

    Survey.objects.filter(pk=sid).update(group=school["gb"])
    bad = owner_c.post(
        f"/api/orgs/{slug}/assignments/",
        {"scenario_id": sc.id, "group_id": school["ga"].id, "survey_id": sid},
        format="json",
    )
    assert bad.status_code == 400 and bad.data["code"] == "survey_audience"
    # cockpit analytics keep working with scenario assignments in the mix
    assert owner_c.get(f"/api/orgs/{slug}/analytics/").status_code == 200


# ── Role-play analytics ──────────────────────────────────────────────


def test_roleplay_report_permissions_exports_and_insights(school):
    owner_c, owner = school["owner"]
    slug = school["slug"]
    sc = _scenario(owner)
    a = owner_c.post(
        f"/api/orgs/{slug}/assignments/", {"scenario_id": sc.id, "group_id": school["ga"].id}, format="json"
    ).data
    org_wide = owner_c.post(f"/api/orgs/{slug}/assignments/", {"scenario_id": sc.id}, format="json").data
    _, ka = school["ka"]
    from apps.orgs.models import Assignment

    _session(ka, sc, 55, assignment=Assignment.objects.get(pk=a["id"]))
    _session(ka, sc, 80, assignment=Assignment.objects.get(pk=a["id"]))
    url = f"/api/orgs/{slug}/teach/assignments/{a['id']}/roleplay/"
    ta_c, _ = school["ta"]
    d = ta_c.get(url).data
    row = d["rows"][0]
    assert d["summary"]["learners"] == 1 and d["summary"]["done"] == 1
    assert (row["latest"], row["best"], row["attempts"], row["status"], row["last_duration"]) == (
        80,
        80,
        2,
        "done",
        240,
    )
    # teacher of another class, a plain learner and another org are refused
    tb_c, _ = school["tb"]
    assert tb_c.get(url).status_code == 403
    assert school["ka"][0].get(url).status_code == 403
    other_c, _ = user("boss@other.in")
    other_slug = other_c.post("/api/orgs/", {"name": "Other School"}, format="json").data["slug"]
    assert other_c.get(url).status_code == 404
    assert other_c.get(f"/api/orgs/{other_slug}/teach/assignments/{a['id']}/roleplay/").status_code == 404
    # org-wide assignment: teacher B only sees their own class
    wide = tb_c.get(f"/api/orgs/{slug}/teach/assignments/{org_wide['id']}/roleplay/").data
    assert [r["name"] for r in wide["rows"]] == ["Kavin"]
    # attempt drill-down with coach feedback; learners outside the teacher's scope are hidden
    att = ta_c.get(f"{url}learners/{ka.id}/").data
    assert [x["score"] for x in att["attempts"]] == [55, 80] and att["attempts"][1]["result"][
        "strengths"
    ] == ["Warm greeting"]
    assert ta_c.get(f"{url}learners/{school['kb'][1].id}/").status_code == 404
    # exports are formula-safe
    body = ta_c.get(url + "?export=csv").content.decode()
    assert "'=HYPERLINK(evil)" in body and "\n=HYPERLINK" not in body
    x = ta_c.get(url + "?export=xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"
    from openpyxl import load_workbook

    ws = load_workbook(io.BytesIO(x.content)).active
    assert ws["A2"].value == "=HYPERLINK(evil)" and ws["A2"].data_type == "s"
    # AI insights: charged, cached, regenerable
    assert ta_c.get(url + "insights/").data["insights"] is None
    r = ta_c.post(url + "insights/")
    assert r.status_code == 200 and r.data["insights"]["struggles"]
    assert ta_c.get(url).data["insights"]["headline"]
    assert UsageCounter.objects.get(user=school["ta"][1], metric="teach_ai").amount == 1
    ta_c.post(url + "insights/")
    assert TeachInsight.objects.filter(kind="roleplay").count() == 1
    assert school["ka"][0].post(url + "insights/").status_code == 403


# ── Course drill-down with keys ──────────────────────────────────────


def test_lesson_drilldown_keys_for_teachers_only_and_misconceptions(school):
    owner_c, _ = school["owner"]
    slug = school["slug"]
    cid = _course(owner_c)
    a = owner_c.post(
        f"/api/orgs/{slug}/assignments/", {"curriculum_id": cid, "group_id": school["ga"].id}, format="json"
    ).data
    sub = Subsection.objects.filter(section__curriculum_id=cid).order_by("section__order", "order").first()
    q = Activity.objects.create(
        subsection=sub,
        order=99,
        type="quiz",
        kind="lesson",
        title="Capital",
        payload={"prompt": "Capital of Tamil Nadu?", "options": ["Madurai", "Chennai"], "multiple": False},
        key={"correct": [1], "explanation": "Chennai is the capital."},
    )
    ka_c, ka = school["ka"]
    # the learner's lesson view never carries the key
    lesson = ka_c.get(f"/api/learn/subsections/{sub.id}/").data
    mine = next(x for x in lesson["activities"] if x["id"] == q.id)
    assert (
        "key" not in mine
        and "correct" not in mine["payload"]
        and "Chennai is the capital." not in str(lesson)
    )
    ActivityAttempt.objects.create(user=ka, activity=q, answer={"selected": [0]}, score=0, correct=False)
    base = f"/api/orgs/{slug}/teach/assignments/{a['id']}/lessons/"
    ta_c, _ = school["ta"]
    lessons = ta_c.get(base).data
    assert lessons["learners"] == 1 and any(
        x["id"] == sub.id and x["answers"] >= 1 for x in lessons["lessons"]
    )
    d = ta_c.get(f"{base}{sub.id}/").data
    qd = next(x for x in d["questions"] if x["id"] == q.id)
    assert qd["key"] is None  # keys only for the course's author (or this org's own templates)
    own_d = owner_c.get(f"{base}{sub.id}/").data
    assert next(x for x in own_d["questions"] if x["id"] == q.id)["key"] == {
        "answer": "B) Chennai",
        "rationale": "Chennai is the capital.",
    }
    assert qd["learners"][0]["answer"] == "A) Madurai" and qd["learners"][0]["correct"] is False
    # refused: plain learner, teacher of another class, other org's lesson id
    assert ka_c.get(f"{base}{sub.id}/").status_code == 403
    assert school["tb"][0].get(f"{base}{sub.id}/").status_code == 403
    other_c, _ = user("o@x.in")
    other_c.post("/api/orgs/", {"name": "Elsewhere"}, format="json")
    other_c.get("/api/orgs/")
    foreign = Subsection.objects.exclude(section__curriculum_id=cid).first()
    if foreign:
        assert ta_c.get(f"{base}{foreign.id}/").status_code == 404
    assert (
        ta_c.post(f"{base}{sub.id}/misconceptions/").status_code == 403
    )  # keys hidden → no misconception read-out
    # this org's own template: its teachers see keys
    from apps.learning.models import Curriculum

    Curriculum.objects.filter(pk=cid).update(template_scope="org", template_org=school["org"])
    assert (
        next(x for x in ta_c.get(f"{base}{sub.id}/").data["questions"] if x["id"] == q.id)["key"]["answer"]
        == "B) Chennai"
    )
    # misconceptions: cached per lesson, charged
    r = ta_c.post(f"{base}{sub.id}/misconceptions/")
    assert r.status_code == 200 and r.data["misconceptions"]["misconceptions"][0]["reteach_tip"]
    assert ta_c.get(f"{base}{sub.id}/").data["misconceptions"]["summary"]
    assert ta_c.get(f"{base}{sub.id}/misconceptions/").data["misconceptions"]
    assert ka_c.post(f"{base}{sub.id}/misconceptions/").status_code == 403


# ── End-of-training survey hook ──────────────────────────────────────


def test_feedback_survey_after_last_lesson_and_roleplay(school):
    owner_c, owner = school["owner"]
    slug = school["slug"]
    sid = _survey(owner_c, slug)
    cid = _course(owner_c)
    owner_c.post(
        f"/api/orgs/{slug}/assignments/",
        {"curriculum_id": cid, "group_id": school["ga"].id, "survey_id": sid},
        format="json",
    )
    ka_c, ka = school["ka"]
    subs = list(Subsection.objects.filter(section__curriculum_id=cid).order_by("section__order", "order"))
    for s in subs[:-1]:
        assert ka_c.post(f"/api/learn/subsections/{s.id}/complete/").data["feedback_survey"] is None
    last = ka_c.post(f"/api/learn/subsections/{subs[-1].id}/complete/").data
    assert last["feedback_survey"]["id"] == sid
    assert (
        ka_c.post(f"/api/orgs/surveys/{sid}/respond/", {"answers": {"q1": 5}}, format="json").status_code
        == 201
    )
    assert (
        ka_c.post(f"/api/learn/subsections/{subs[-1].id}/complete/").data["feedback_survey"] is None
    )  # answered already
    # role-play: shown on the finished session (other learners in other classes don't get it)
    sid2 = _survey(owner_c, slug)
    sc = _scenario(owner)
    owner_c.post(
        f"/api/orgs/{slug}/assignments/",
        {"scenario_id": sc.id, "group_id": school["ga"].id, "survey_id": sid2},
        format="json",
    )
    s = _session(ka, sc, 70)
    assert ka_c.get(f"/api/roleplay/sessions/{s.id}/").data["feedback_survey"]["id"] == sid2
    active = _session(ka, sc)
    assert ka_c.get(f"/api/roleplay/sessions/{active.id}/").data["feedback_survey"] is None
    _, kb = school["kb"]
    s2 = _session(kb, sc, 70)
    assert school["kb"][0].get(f"/api/roleplay/sessions/{s2.id}/").data["feedback_survey"] is None


# ── Pilot KPI report ─────────────────────────────────────────────────


def test_pilot_kpi_math(school):
    from apps.study.models import CheckpointAttempt

    owner_c, _ = school["owner"]
    slug, org = school["slug"], school["org"]
    cid = _course(owner_c)
    owner_c.post(
        f"/api/orgs/{slug}/assignments/", {"curriculum_id": cid}, format="json"
    )  # whole org: ka + kb
    _, ka = school["ka"]
    _, kb = school["kb"]
    _, kc = user("kc@school.in", "Charu")
    member(org, kc, "learner")
    _, kd = user("kd@school.in", "Deepa")
    member(org, kd, "learner")
    today = timezone.localdate()
    subs = list(Subsection.objects.filter(section__curriculum_id=cid))
    now = timezone.now()
    for s in subs:  # ka finishes the course
        UserSubsectionState.objects.create(
            user=ka, subsection=s, status="completed", score=1, started_at=now, completed_at=now
        )
    UserSubsectionState.objects.create(user=kb, subsection=subs[0], status="in_progress", started_at=now)
    UserSubsectionState.objects.create(
        user=kc, subsection=subs[0], status="in_progress", started_at=now
    )  # 3 of 4 activated
    for u, days_ago in [
        (ka, 0),
        (ka, 14),
        (kb, 1),
        (kb, 3),
        (kc, 20),
    ]:  # ka: 2 weeks; kb: 1 week; kc: 1 week → 1 sustained
        XPEvent.objects.create(user=u, kind="lesson", xp=10, day=today - timedelta(days=days_ago))
    CheckpointAttempt.objects.create(user=ka, curriculum_id=cid, kind="pre", correct=2, total=10)
    CheckpointAttempt.objects.create(user=ka, curriculum_id=cid, kind="post", correct=8, total=10)
    CheckpointAttempt.objects.create(
        user=kb, curriculum_id=cid, kind="pre", correct=5, total=10
    )  # no post → not counted
    sid = _survey(owner_c, slug, nps=True)
    for i, v in enumerate([10, 9, 5]):
        c, u = user(f"n{i}@school.in")
        member(org, u, "learner")
        assert (
            c.post(f"/api/orgs/surveys/{sid}/respond/", {"answers": {"q1": v}}, format="json").status_code
            == 201
        )
    LessonFeedback.objects.create(user=ka, subsection=subs[0], rating=5)
    d = owner_c.get(f"/api/orgs/{slug}/teach/pilot/").data
    k = d["kpis"]
    assert k["learners"] == 7  # ka, kb, kc, kd + 3 survey respondents
    assert k["activation"]["n"] == 3
    assert k["sustained"]["n"] == 1
    assert (k["completion"]["n"], k["completion"]["of"]) == (1, 7)  # org-wide course: 7 learners, 1 finished
    assert k["gain"] == {"pairs": 1, "avg_pre": 0.2, "avg_post": 0.8, "avg_gain": 0.6}
    r = k["recommend"]
    assert (
        r["source"] == "nps"
        and r["nps"] == 33
        and r["promoters"] == pytest.approx(0.667)
        and r["rating_4plus"] == 1.0
    )
    assert sum(w["active"] for w in d["weekly"][-1:]) == 2 and d["highlights"]
    # teacher A's scope: only class 7-A (ka)
    ta = school["ta"][0].get(f"/api/orgs/{slug}/teach/pilot/").data["kpis"]
    assert ta["learners"] == 1 and ta["completion"]["n"] == 1
    # date range filter: a range before anything happened
    old = owner_c.get(f"/api/orgs/{slug}/teach/pilot/?from=2020-01-01&to=2020-02-01").data["kpis"]
    assert old["learners"] == 0 and old["activation"]["value"] is None
    assert owner_c.get(f"/api/orgs/{slug}/teach/pilot/?from=2026-05-01&to=2026-01-01").status_code == 400
    assert owner_c.get(f"/api/orgs/{slug}/teach/pilot/?from=nope").status_code == 400


def test_pilot_exports_open_and_permissions(school):
    owner_c, _ = school["owner"]
    slug = school["slug"]
    org = school["org"]
    org.name = "Sunrise <b>School</b> & Co"
    org.save()
    XPEvent.objects.create(user=school["ka"][1], kind="lesson", xp=10, day=timezone.localdate())
    pdf = owner_c.get(f"/api/orgs/{slug}/teach/pilot/report.pdf")
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-" and pdf["Content-Type"] == "application/pdf"
    pptx = owner_c.get(f"/api/orgs/{slug}/teach/pilot/report.pptx")
    assert pptx.status_code == 200 and pptx.content[:2] == b"PK"
    names = zipfile.ZipFile(io.BytesIO(pptx.content)).namelist()
    assert sum(n.startswith("ppt/slides/slide") and n.endswith(".xml") for n in names) == 5
    from pptx import Presentation

    texts = [
        sh.text_frame.text
        for sl in Presentation(io.BytesIO(pptx.content)).slides
        for sh in sl.shapes
        if sh.has_text_frame
    ]
    assert "Sunrise <b>School</b> & Co" in texts
    ka_c = school["ka"][0]
    for p in ("teach/pilot/", "teach/pilot/report.pdf", "teach/pilot/report.pptx", "teach/scenarios/"):
        assert ka_c.get(f"/api/orgs/{slug}/{p}").status_code == 403
    other_c, _ = user("z@z.in")
    assert other_c.get(f"/api/orgs/{slug}/teach/pilot/report.pdf").status_code == 404
    assert owner_c.get(f"/api/orgs/{slug}/teach/scenarios/").status_code == 200


def test_survey_response_count_unchanged_by_hook(school):
    """The hook only reads: showing the prompt never creates responses or drafts."""
    owner_c, owner = school["owner"]
    slug = school["slug"]
    sid = _survey(owner_c, slug)
    sc = _scenario(owner)
    owner_c.post(f"/api/orgs/{slug}/assignments/", {"scenario_id": sc.id, "survey_id": sid}, format="json")
    s = _session(school["ka"][1], sc, 90)
    for _ in range(2):
        school["ka"][0].get(f"/api/roleplay/sessions/{s.id}/")
    assert SurveyResponse.objects.count() == 0


def test_patch_assignment_flags(school):
    owner_c, owner = school["owner"]
    slug = school["slug"]
    a = owner_c.post(
        f"/api/orgs/{slug}/assignments/", {"scenario_id": _scenario(owner).id}, format="json"
    ).data
    r = owner_c.patch(
        f"/api/orgs/{slug}/assignments/{a['id']}/", {"mandatory": True, "due_at": None}, format="json"
    )
    assert r.status_code == 200 and r.data["mandatory"] is True
    assert (
        owner_c.patch(
            f"/api/orgs/{slug}/assignments/{a['id']}/", {"due_at": "not a date"}, format="json"
        ).status_code
        == 400
    )
    assert (
        school["ka"][0]
        .patch(f"/api/orgs/{slug}/assignments/{a['id']}/", {"mandatory": False}, format="json")
        .status_code
        == 403
    )


# ── Security review regressions ──────────────────────────────────────


def test_scope_key_is_full_hash_and_creator_gets_no_bypass(school):
    from apps.orgs.models import Assignment
    from apps.orgs.teach import scope_key

    org = school["org"]
    long_a = [Group.objects.create(org=org, name=f"A{i}") for i in range(40)]
    _, t1 = user("t1@school.in")
    _, t2 = user("t2@school.in")
    m1, m2 = member(org, t1, "manager"), member(org, t2, "manager")
    m1.groups.add(*long_a)
    m2.groups.add(*long_a[:-1])  # same long prefix, one class fewer
    assert scope_key(m1) != scope_key(m2) and len(scope_key(m1)) <= 80
    wide = Assignment.objects.create(org=org, scenario=_scenario(school["owner"][1]), created_by=t1)
    # Decision (S19): creating an org-wide assignment gives a class-scoped teacher no extra reach; they see their
    # classes only, so a demoted or class-removed creator can't keep reading every learner's rows.
    assert scope_key(m1, wide).startswith("g:") and scope_key(m1, wide) != scope_key(m2, wide)
    assert scope_key(m2, wide).startswith("g:")


def test_roleplay_counts_only_sessions_of_this_assignment(school):
    owner_c, _ = school["owner"]
    slug = school["slug"]
    ka_c, ka = school["ka"]
    ka_c.get("/api/roleplay/scenarios/")
    lib = Scenario.objects.filter(source="library").first()
    _session(ka, lib, 90, assignment=None)  # personal practice before
    a = owner_c.post(f"/api/orgs/{slug}/assignments/", {"scenario_id": lib.id}, format="json").data
    # a second school assigns the same library scenario to the same learner
    other_c, _ = user("p@other.in")
    other_slug = other_c.post("/api/orgs/", {"name": "Other School"}, format="json").data["slug"]
    member(Organization.objects.get(slug=other_slug), ka, "learner")
    b = other_c.post(f"/api/orgs/{other_slug}/assignments/", {"scenario_id": lib.id}, format="json").data
    r = ka_c.post("/api/roleplay/sessions/", {"scenario_id": lib.id, "assignment_id": a["id"]}, format="json")
    sess = RolePlaySession.objects.get(pk=r.data["id"])
    assert sess.assignment_id == a["id"]
    sess.status, sess.result, sess.ended_at = "completed", _result(60), timezone.now()
    sess.save()
    _session(ka, lib, 30, assignment=None)  # personal practice after: not counted
    mine = owner_c.get(f"/api/orgs/{slug}/teach/assignments/{a['id']}/roleplay/").data["rows"]
    assert next(x for x in mine if x["user_id"] == ka.id)["attempts"] == 1
    theirs = other_c.get(f"/api/orgs/{other_slug}/teach/assignments/{b['id']}/roleplay/").data["rows"]
    assert theirs[0]["attempts"] == 0  # not double counted in the other school
    # an assignment id from another org can't be attached
    r2 = ka_c.post("/api/roleplay/sessions/", {"scenario_id": lib.id, "assignment_id": 999999}, format="json")
    assert RolePlaySession.objects.get(pk=r2.data["id"]).assignment_id in (a["id"], b["id"])


def test_managers_cannot_assign_or_read_keys_of_other_staff_private_items(school):
    owner_c, owner = school["owner"]
    slug = school["slug"]
    ta_c, ta = school["ta"]
    private_sc = _scenario(owner)  # the principal's own, never shared
    listed = {s["id"] for s in ta_c.get(f"/api/orgs/{slug}/teach/scenarios/").data}
    assert private_sc.id not in listed
    assert (
        ta_c.post(f"/api/orgs/{slug}/assignments/", {"scenario_id": private_sc.id}, format="json").status_code
        == 404
    )
    cid = _course(owner_c)  # owner's private, unpublished course
    assert (
        ta_c.post(
            f"/api/orgs/{slug}/assignments/",
            {"curriculum_id": cid, "group_id": school["ga"].id},
            format="json",
        ).status_code
        == 404
    )
    own = _scenario(ta)
    assert (
        ta_c.post(
            f"/api/orgs/{slug}/assignments/",
            {"scenario_id": own.id, "group_id": school["ga"].id},
            format="json",
        ).status_code
        == 201
    )
    # an old assignment a manager made of someone else's course (before this fix): keys stay hidden from that manager
    from apps.learning.models import Curriculum
    from apps.orgs.models import Assignment

    Curriculum.objects.filter(pk=cid).update(published_at=timezone.now())
    a = Assignment.objects.create(org=school["org"], group=school["ga"], curriculum_id=cid, created_by=ta)
    sub = Subsection.objects.filter(section__curriculum_id=cid).first()
    Activity.objects.create(
        subsection=sub,
        order=99,
        type="quiz",
        kind="lesson",
        title="Q",
        payload={"prompt": "?", "options": ["a", "b"], "multiple": False},
        key={"correct": [1], "explanation": "SECRET"},
    )
    d = ta_c.get(f"/api/orgs/{slug}/teach/assignments/{a.id}/lessons/{sub.id}/").data
    assert d["keys"] is False and "SECRET" not in str(d)
    assert (
        ta_c.post(f"/api/orgs/{slug}/teach/assignments/{a.id}/lessons/{sub.id}/misconceptions/").status_code
        == 403
    )
    # once the author shares it with the org it becomes assignable — but keys stay with the author
    Assignment.objects.create(org=school["org"], curriculum_id=cid, created_by=owner)
    assert ta_c.get(f"/api/orgs/{slug}/teach/assignments/{a.id}/lessons/{sub.id}/").data["keys"] is False
    assert (
        ta_c.post(
            f"/api/orgs/{slug}/assignments/",
            {"curriculum_id": cid, "group_id": school["ga"].id},
            format="json",
        ).status_code
        == 201
    )


def test_manager_without_class_sees_nobody_when_org_has_classes(school):
    owner_c, owner = school["owner"]
    slug = school["slug"]
    nc_c, nc = user("noclass@school.in")
    member(school["org"], nc, "manager")
    a = owner_c.post(
        f"/api/orgs/{slug}/assignments/", {"scenario_id": _scenario(owner).id}, format="json"
    ).data
    d = nc_c.get(f"/api/orgs/{slug}/teach/assignments/{a['id']}/roleplay/").data
    assert d["rows"] == [] and d["no_class"] is True
    p = nc_c.get(f"/api/orgs/{slug}/teach/pilot/").data
    assert p["kpis"]["learners"] == 0 and p["no_class"] is True
    assert (
        nc_c.get(f"/api/orgs/{slug}/teach/assignments/{a['id']}/roleplay/?export=csv")
        .content.decode()
        .count("\n")
        == 1
    )  # header only
    # an org with no classes at all: a manager still sees everyone
    c2, boss = user("boss@tiny.in")
    tiny = c2.post("/api/orgs/", {"name": "Tiny Tuition"}, format="json").data["slug"]
    org2 = Organization.objects.get(slug=tiny)
    tc, t = user("t@tiny.in")
    member(org2, t, "manager")
    _, kid = user("kid@tiny.in")
    member(org2, kid, "learner")
    assert tc.get(f"/api/orgs/{tiny}/teach/pilot/").data["kpis"]["learners"] == 1
