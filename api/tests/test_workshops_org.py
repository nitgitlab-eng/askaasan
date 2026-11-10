"""Institution workshops (M4): the platform switch and monthly seats, org runs scheduled by owners/admins with
auto-enrolment, visibility for class members only, drill-down scope, the PDF/PPTX/CSV report and the org-run notice."""

import csv
import io
import zipfile
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.game.models import Notification
from apps.orgs.models import Cohort, Group, Membership, Organization
from apps.workshops import services, tasks
from apps.workshops.content import seed
from apps.workshops.models import WorkshopEnrollment, WorkshopEvent, WorkshopRun, WorkshopSession

pytestmark = pytest.mark.django_db
PW = "Work#2026passwd"


@pytest.fixture(autouse=True)
def _seeded(db):
    seed()


def user(email, name="X", staff=False):
    u = User.objects.create_user(email, PW, is_staff=staff, email_verified=True)
    u.profile.display_name = name
    u.profile.save()
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def member(org, u, role, group=None, **fields):
    m = Membership.objects.create(org=org, user=u, role=role, fields=fields)
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
    org.features = {"workshops": True}
    org.workshop_seats = 10
    org.save()
    ga, gb = Group.objects.create(org=org, name="7-A"), Group.objects.create(org=org, name="7-B")
    ta_c, ta = user("ta@school.in", "Anitha")
    member(org, ta, "manager", ga)
    tb_c, tb = user("tb@school.in", "Bala")
    member(org, tb, "manager", gb)
    ka_c, ka = user("ka@school.in", "=HYPERLINK(evil)")  # a formula-looking name must stay text in exports
    member(org, ka, "learner", ga, roll_no="01")
    kb_c, kb = user("kb@school.in", "கவின்")  # Tamil name (Noto fonts in the PDF)
    member(org, kb, "learner", gb, roll_no="02")
    kc_c, kc = user("kc@school.in", "Outsider")
    member(org, kc, "learner")  # in the org, in no selected class
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
        "kc": (kc_c, kc),
    }


def base(school):
    return f"/api/orgs/{school['slug']}/workshops"


def _future(**kw):
    return (timezone.now() + timedelta(**(kw or {"days": 2}))).isoformat()


def create(school, groups=None, cohorts=(), client=None, **kw):
    c = client or school["owner"][0]
    body = {
        "workshop_slug": "quick-check",
        "starts_at": _future(),
        "groups": [
            getattr(g, "id", g) for g in (groups if groups is not None else [school["ga"], school["gb"]])
        ],
        "cohorts": list(cohorts),
        **kw,
    }
    return c.post(f"{base(school)}/runs/", body, format="json")


def _start_session(run, u, **kw):
    e = WorkshopEnrollment.objects.get(run=run, user=u)
    s = WorkshopSession.objects.create(enrollment=e, user=u, run=run, **kw)
    s.prereqs_done = {p["key"]: "x" for p in run.workshop.prerequisites}
    s.save()
    services.start(s)
    return s


# ── Feature switch and roles ─────────────────────────────────────────


def test_fresh_org_has_workshops_on_but_no_seats(school):
    """An org never touched by the platform admin: the cockpit works (200), but seats are 0 so nothing schedules."""
    from apps.orgs.extras import feature_on

    org, owner_c = school["org"], school["owner"][0]
    org.features = {}
    org.workshop_seats = 0
    org.save()
    assert feature_on(org, "workshops") is True
    for path in ("templates/", "runs/"):
        assert owner_c.get(f"{base(school)}/{path}").status_code == 200, path
    ov = owner_c.get(f"{base(school)}/").data
    assert ov["enabled"] is True and ov["can_manage"] is True and ov["seats"] == 0
    res = create(school)
    assert res.status_code == 409 and res.data["code"] == "quota_exceeded" and res.data["seats"] == 0
    org.workshop_seats = 10
    org.save()
    assert create(school).status_code == 201


def test_explicit_off_is_403_and_org_admin_cannot_switch_it(school):
    org, owner_c = school["org"], school["owner"][0]
    org.features = {"workshops": False}  # what the platform admin stores when switching it off
    org.save()
    for path in ("templates/", "runs/"):
        res = owner_c.get(f"{base(school)}/{path}")
        assert res.status_code == 403 and res.data["code"] == "feature_off"
    assert create(school).status_code == 403
    assert owner_c.get(f"{base(school)}/").data["enabled"] is False
    # The org's own settings can't switch the platform feature back on (silently dropped, the rest still saves).
    res = owner_c.patch(
        f"/api/orgs/{school['slug']}/settings/",
        {"features": {"workshops": True, "shop": False}},
        format="json",
    )
    assert (
        res.status_code == 200
        and res.data["features"]["workshops"] is False
        and res.data["features"]["shop"] is False
    )
    org.refresh_from_db()
    assert org.features == {"workshops": False, "shop": False}
    # An explicit off is the whole switch: the org's learners lose workshops too.
    ka_c = school["ka"][0]
    assert ka_c.get("/api/workshops/runs/").status_code == 403
    assert "workshops" in ka_c.get("/api/orgs/me/brand/").data["disabled"]
    # ...and the org can't switch it off either: a default-on org stays on after its own PATCH.
    org.features = {}
    org.save()
    res = owner_c.patch(
        f"/api/orgs/{school['slug']}/settings/", {"features": {"workshops": False}}, format="json"
    )
    assert res.status_code == 200 and res.data["features"]["workshops"] is True
    org.refresh_from_db()
    assert org.features == {}
    assert ka_c.get("/api/workshops/runs/").status_code == 200


def test_roles_schedule_admin_only_view_manager(school):
    assert create(school, client=school["ta"][0]).status_code == 403  # teachers can't schedule
    assert school["ka"][0].get(f"{base(school)}/runs/").status_code == 403  # learners see no staff pages
    other_c, _ = user("z@z.in")
    assert other_c.get(f"{base(school)}/runs/").status_code == 404  # non-members don't learn the org exists
    assert school["ta"][0].get(f"{base(school)}/templates/").status_code == 200
    ov = school["ta"][0].get(f"{base(school)}/").data
    assert ov["enabled"] and ov["can_manage"] is False and ov["scope"] == "classes"


def test_platform_admin_sets_feature_and_seats(school):
    org = school["org"]
    org.features = {"shop": False}
    org.save()
    assert school["owner"][0].get("/api/admin/workshops/orgs/").status_code == 403
    staff_c, _ = user("ops@aasan.in", staff=True)
    rows = staff_c.get("/api/admin/workshops/orgs/?q=sunrise").data
    assert [r["id"] for r in rows] == [org.id] and rows[0]["workshops"] is True  # on by default
    res = staff_c.patch(
        f"/api/admin/workshops/orgs/{org.id}/", {"workshops": True, "workshop_seats": 40}, format="json"
    )
    assert res.status_code == 200 and res.data["workshops"] and res.data["workshop_seats"] == 40
    org.refresh_from_db()
    assert org.features == {"shop": False, "workshops": True} and org.workshop_seats == 40
    assert (
        staff_c.patch(
            f"/api/admin/workshops/orgs/{org.id}/", {"workshop_seats": -1}, format="json"
        ).status_code
        == 400
    )
    assert (
        staff_c.patch(f"/api/admin/workshops/orgs/{org.id}/", {"workshops": "yes"}, format="json").status_code
        == 400
    )
    # Off stores an explicit False (the only way to be off now), which blocks the cockpit and the org's learners.
    res = staff_c.patch(f"/api/admin/workshops/orgs/{org.id}/", {"workshops": False}, format="json")
    assert res.status_code == 200 and res.data["workshops"] is False
    org.refresh_from_db()
    assert org.features == {"shop": False, "workshops": False}
    assert school["owner"][0].get(f"{base(school)}/runs/").status_code == 403
    assert school["ka"][0].get("/api/workshops/runs/").status_code == 403
    assert staff_c.get("/api/admin/workshops/orgs/?q=sunrise").data[0]["workshops"] is False


# ── Scheduling, auto-enrolment, visibility ───────────────────────────


def test_create_auto_enrols_notifies_and_only_members_see_it(school):
    res = create(school, proctoring="activity")
    assert res.status_code == 201, res.data
    run = WorkshopRun.objects.get(pk=res.data["id"])
    assert (
        run.audience == "org"
        and run.org == school["org"]
        and run.price_paise == 0
        and run.status == "scheduled"
    )
    ka, kb, kc = school["ka"][1], school["kb"][1], school["kc"][1]
    assert set(run.enrollments.values_list("user_id", flat=True)) == {
        ka.id,
        kb.id,
    }  # learners only, no teachers
    assert res.data["enrolled"] == 2
    assert Notification.objects.filter(user=ka, kind="workshop", link=f"/workshops/{run.id}").exists()
    assert not Notification.objects.filter(user=kc, kind="workshop").exists()
    # Learners in the classes see it (free, enrolled, with the institution notice); others can't see or join.
    ka_c, kc_c = school["ka"][0], school["kc"][0]
    mine = [r for r in ka_c.get("/api/workshops/runs/").data if r["id"] == run.id]
    assert mine and mine[0]["enrolled"] and mine[0]["org"]["slug"] == school["slug"]
    detail = ka_c.get(f"/api/workshops/runs/{run.id}/").data
    assert detail["institution_notice"].startswith(
        "Your institution can see your progress, answers, scores and help summaries during this workshop"
    )
    assert "attention" in detail["institution_notice"] and "attention" in detail["institution_sees"]
    assert run.id not in [r["id"] for r in kc_c.get("/api/workshops/runs/").data]
    assert kc_c.get(f"/api/workshops/runs/{run.id}/").status_code == 404
    assert kc_c.post(f"/api/workshops/runs/{run.id}/enroll/").status_code == 404
    assert kc_c.post(f"/api/workshops/runs/{run.id}/session/").status_code == 404
    other_c, _ = user("stranger@x.in")
    assert other_c.get(f"/api/workshops/runs/{run.id}/").status_code == 404
    # A learner taken out of the class loses the run (and their session on it).
    run.starts_at = timezone.now() + timedelta(minutes=5)
    run.save()
    sid = ka_c.post(f"/api/workshops/runs/{run.id}/session/").data["id"]
    school["ga"].members.remove(Membership.objects.get(org=school["org"], user=ka))
    assert ka_c.get(f"/api/workshops/runs/{run.id}/").status_code == 404
    assert ka_c.get(f"/api/workshops/sessions/{sid}/").status_code == 404


def test_cohort_audience_and_validation(school):
    org = school["org"]
    co = Cohort.objects.create(
        org=org, name="Partner batch", starts_at=timezone.now(), ends_at=timezone.now() + timedelta(days=60)
    )
    _, kd = user("kd@school.in", "Divya")
    co.members.add(member(org, kd, "learner"))
    res = create(school, groups=[], cohorts=[co.id])
    assert res.status_code == 201 and res.data["enrolled"] == 1
    assert res.data["cohorts"] == [{"id": co.id, "name": "Partner batch"}]
    # Another org's class, junk ids, an empty class, a past time, an unknown template.
    other = Organization.objects.create(name="Other", slug="other-org")
    foreign = Group.objects.create(org=other, name="X")
    assert create(school, groups=[foreign.id]).data["code"] == "bad_groups"
    assert create(school, groups=["x"]).data["code"] == "bad_groups"
    assert create(school, groups=[], cohorts=[999999]).data["code"] == "bad_cohorts"
    empty = Group.objects.create(org=org, name="Empty")
    assert create(school, groups=[empty]).data["code"] == "no_learners"
    assert (
        create(school, starts_at=(timezone.now() - timedelta(hours=1)).isoformat()).data["code"]
        == "bad_starts_at"
    )
    assert create(school, workshop_slug="nope").data["code"] == "bad_workshop"
    assert create(school, proctoring="camera").data["code"] == "bad_proctoring"
    # Price / capacity can't be smuggled in: org runs are free.
    res = create(school, price_paise=50000, capacity=1)
    run = WorkshopRun.objects.get(pk=res.data["id"])
    assert run.price_paise == 0 and run.capacity is None


def test_monthly_seat_quota_counts_distinct_learners(school):
    # Runs start minutes from now, so they're in this month's quota (two days ahead crossed into next month on the
    # 30th and 31st, and the cockpit's "used this month" was then 0).
    soon = _future(minutes=5)
    org = school["org"]
    org.workshop_seats = 1
    org.save()
    res = create(school, starts_at=soon)
    assert res.status_code == 409 and res.data["code"] == "quota_exceeded" and res.data["needed"] == 2
    assert not WorkshopRun.objects.exists()
    org.workshop_seats = 2
    org.save()
    first = create(school, starts_at=soon)
    assert first.status_code == 201
    # The same learners again this month: no new seats needed.
    assert create(school, groups=[school["ga"]], starts_at=soon).status_code == 201
    # A new learner would be the third distinct one.
    _, kd = user("kd@school.in")
    member(org, kd, "learner", school["ga"])
    assert create(school, groups=[school["ga"]], starts_at=soon).data["code"] == "quota_exceeded"
    # A cancelled run frees its seats.
    for r in WorkshopRun.objects.all():
        school["owner"][0].post(f"{base(school)}/runs/{r.id}/cancel/")
    assert create(school, groups=[school["ga"]], starts_at=soon).status_code == 201
    quota = school["owner"][0].get(f"{base(school)}/runs/").data["quota"]
    assert quota == {"limit": 2, "used": 2, "month": quota["month"]}


def test_patch_cancel_and_reminders(school):
    owner_c = school["owner"][0]
    run_id = create(school, groups=[school["ga"]]).data["id"]
    run = WorkshopRun.objects.get(pk=run_id)
    WorkshopEnrollment.objects.filter(run=run).update(reminded_24h=True)
    assert (
        school["ta"][0]
        .patch(f"{base(school)}/runs/{run_id}/", {"proctoring": "strict"}, format="json")
        .status_code
        == 403
    )
    soon = (timezone.now() + timedelta(minutes=10)).isoformat()
    res = owner_c.patch(
        f"{base(school)}/runs/{run_id}/",
        {"starts_at": soon, "groups": [school["ga"].id, school["gb"].id]},
        format="json",
    )
    assert res.status_code == 200 and res.data["enrolled"] == 2
    assert not WorkshopEnrollment.objects.filter(
        run=run, reminded_24h=True
    ).exists()  # moved: reminders again
    assert Notification.objects.filter(user=school["kb"][1], kind="workshop").exists()  # newly enrolled told
    # Org runs get the M3 reminders too.
    sent = tasks.send_reminders()
    assert sent["15m"] == 2
    # Dropping a class removes the unused seats of its learners.
    owner_c.patch(f"{base(school)}/runs/{run_id}/", {"groups": [school["ga"].id]}, format="json")
    assert list(run.enrollments.values_list("user_id", flat=True)) == [school["ka"][1].id]
    # Live runs can't be edited (the notice was shown); cancel works and tells learners.
    WorkshopRun.objects.filter(pk=run_id).update(starts_at=timezone.now() - timedelta(minutes=1))
    assert (
        owner_c.patch(f"{base(school)}/runs/{run_id}/", {"proctoring": "strict"}, format="json").data["code"]
        == "not_editable"
    )
    assert school["ta"][0].post(f"{base(school)}/runs/{run_id}/cancel/").status_code == 403
    res = owner_c.post(f"{base(school)}/runs/{run_id}/cancel/")
    assert res.status_code == 200 and res.data["status"] == "cancelled"
    assert Notification.objects.filter(user=school["ka"][1], title__startswith="Cancelled").exists()


def test_teacher_lists_runs_with_own_learners_only(school):
    create(school, groups=[school["ga"]])
    create(school, groups=[school["gb"]])
    rows = school["ta"][0].get(f"{base(school)}/runs/").data["runs"]
    assert len(rows) == 1 and rows[0]["enrolled"] == 1 and rows[0]["groups"][0]["name"] == "7-A"
    assert len(school["owner"][0].get(f"{base(school)}/runs/").data["runs"]) == 2
    gb_run = WorkshopRun.objects.filter(groups=school["gb"]).first()
    assert school["ta"][0].get(f"{base(school)}/runs/{gb_run.id}/").status_code == 404


# ── Drill-down and report ────────────────────────────────────────────


@pytest.fixture
def ran(school):
    run = WorkshopRun.objects.get(pk=create(school, proctoring="activity").data["id"])
    sa = _start_session(run, school["ka"][1])
    sb = _start_session(run, school["kb"][1])
    services.event(sa, "answer", item=0, score=0.2, tries=1)
    services.event(sa, "help_error", summary="=cmd|' /C calc'!A0 pip install failed")
    services.event(sa, "staff_nudge", text="Keep going!", name="Meena")
    services.event(sa, "tab_hidden")
    sa.final_score, sa.passed, sa.status = 0.9, True, "submitted"
    sa.scores = {sa.run.workshop.agenda[0]["key"]: 0.8}
    sa.save()
    sb.final_score, sb.status = 0.3, "submitted"
    sb.save()
    return {**school, "run": run, "sa": sa, "sb": sb}


def test_drilldown_is_scoped(ran):
    run, sa, sb = ran["run"], ran["sa"], ran["sb"]
    url = f"{base(ran)}/runs/{run.id}/learners"
    d = ran["owner"][0].get(f"{url}/{sa.id}/").data
    assert d["learner"]["roll_no"] == "01" and d["tile"]["session_id"] == sa.id
    assert d["answers"][0]["score"] == 0.2 and d["answers"][0]["correct"] is False
    assert d["help"][0]["summary"].endswith("pip install failed")
    assert d["nudges"] == [{"at": d["nudges"][0]["at"], "text": "Keep going!", "from": "Meena"}]
    assert d["attention"][0]["kind"] == "tab_hidden"  # proctoring on
    assert d["stages"][0]["status"] == "current" and d["transcript"] == []
    assert ran["ta"][0].get(f"{url}/{sa.id}/").status_code == 200
    assert ran["ta"][0].get(f"{url}/{sb.id}/").status_code == 404  # another teacher's class
    assert ran["tb"][0].get(f"{url}/{sb.id}/").status_code == 200
    assert ran["ka"][0].get(f"{url}/{sa.id}/").status_code == 403
    # A session id from another run never resolves under this one.
    other = WorkshopRun.objects.get(pk=create(ran, groups=[ran["ga"]]).data["id"])
    assert ran["owner"][0].get(f"{base(ran)}/runs/{other.id}/learners/{sa.id}/").status_code == 404


def test_drilldown_hides_attention_when_proctoring_off(ran):
    WorkshopRun.objects.filter(pk=ran["run"].id).update(proctoring="off")
    d = ran["owner"][0].get(f"{base(ran)}/runs/{ran['run'].id}/learners/{ran['sa'].id}/").data
    assert d["attention"] is None and d["attention_summary"] is None and d["tile"]["attention"] is None
    assert all(e["type"] != "tab_hidden" for e in d["timeline"])


def test_report_files_generate_scoped_and_formula_safe(ran):
    run = ran["run"]
    owner_c = ran["owner"][0]
    url = f"{base(ran)}/runs/{run.id}"
    d = owner_c.get(f"{url}/report/").data
    p = d["participation"]
    assert (p["enrolled"], p["started"], p["finished"], p["passed"]) == (2, 2, 2, 1)
    assert d["scores"]["avg"] == 0.6 and d["missed_concepts"][0]["misses"] == 1 and d["attention"]
    assert d["help_topics"][0]["count"] == 1
    pdf = owner_c.get(f"{url}/report.pdf")
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    pptx = owner_c.get(f"{url}/report.pptx")
    assert pptx.status_code == 200 and pptx.content[:2] == b"PK"
    assert any(n.startswith("ppt/slides/slide") for n in zipfile.ZipFile(io.BytesIO(pptx.content)).namelist())
    res = owner_c.get(f"{url}/report.csv")
    assert res.status_code == 200 and res["Content-Type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(res.content.decode("utf-8-sig"))))
    assert rows[0][:4] == ["Name", "Roll no", "Email", "Status"] and "Attention %" in rows[0]
    names = [r[0] for r in rows[1:]]
    assert "'=HYPERLINK(evil)" in names and "கவின்" in names  # formula-safe, Tamil kept
    assert not any(cell[:1] in "=+-@" for r in rows for cell in r if cell)
    # A teacher's report covers their class only.
    ta_rows = list(csv.reader(io.StringIO(ran["ta"][0].get(f"{url}/report.csv").content.decode("utf-8-sig"))))
    assert [r[0] for r in ta_rows[1:]] == ["'=HYPERLINK(evil)"]
    assert ran["ta"][0].get(f"{url}/report/").data["participation"]["enrolled"] == 1
    assert ran["ka"][0].get(f"{url}/report.pdf").status_code == 403
    ran["org"].features = {"workshops": False}
    ran["org"].save()
    assert owner_c.get(f"{url}/report.csv").status_code == 403


def test_report_without_proctoring_has_no_attention(ran):
    WorkshopRun.objects.filter(pk=ran["run"].id).update(proctoring="off")
    d = ran["owner"][0].get(f"{base(ran)}/runs/{ran['run'].id}/report/").data
    assert d["attention"] is None and "focus_losses" not in d["students"][0]
    assert ran["owner"][0].get(f"{base(ran)}/runs/{ran['run'].id}/report.pdf").status_code == 200


# ── Notice ───────────────────────────────────────────────────────────


def test_org_run_notice_in_session_and_not_on_public_runs(school):
    run = WorkshopRun.objects.get(pk=create(school).data["id"])
    s = _start_session(run, school["ka"][1])
    out = school["ka"][0].get(f"/api/workshops/sessions/{s.id}/").data
    assert out["institution_notice"] == (
        "Your institution can see your progress, answers, scores and help summaries during this workshop."
    )
    assert out["institution_sees"] == ["progress", "answers", "scores", "help_summaries"]
    pub = WorkshopRun.objects.create(
        workshop=run.workshop, audience="public", starts_at=timezone.now(), status="live"
    )
    e = WorkshopEnrollment.objects.create(run=pub, user=school["kc"][1])
    ps = WorkshopSession.objects.create(enrollment=e, user=school["kc"][1], run=pub)
    assert school["kc"][0].get(f"/api/workshops/sessions/{ps.id}/").data["institution_notice"] is None
    assert not WorkshopEvent.objects.filter(session=ps).exists()


def test_org_detail_exposes_workshops_feature(school):
    owner_c = school["owner"][0]
    assert owner_c.get(f"/api/orgs/{school['slug']}/").data["features"] == {"workshops": True}
    school["org"].features = {}  # never touched: on by default
    school["org"].save()
    assert owner_c.get(f"/api/orgs/{school['slug']}/").data["features"] == {"workshops": True}
    school["org"].features = {"workshops": False}
    school["org"].save()
    assert owner_c.get(f"/api/orgs/{school['slug']}/").data["features"] == {"workshops": False}
    assert school["ta"][0].get(f"/api/orgs/{school['slug']}/").data["features"]["workshops"] is False
