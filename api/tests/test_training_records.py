"""C3 compliance training records: one row per completion kind (course, role-play, workshop, knowledge test) with its
values, certificate attached once, append-only, deduplicated, CSV / Excel / PDF exports (formula-safe), teacher scope,
the learner's own record, backfill (idempotent) and anonymisation on account deletion."""

import csv
import io
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.credentials.models import Certificate
from apps.orgs.models import Assignment, Group, Membership, Organization, Survey, TrainingRecord
from apps.roleplay.models import RolePlaySession, Scenario
from tests.test_cred_certificates import complete, course

pytestmark = pytest.mark.django_db
PW = "Rec#2026passwd"


def user(email, name):
    u = User.objects.create_user(email, PW, email_verified=True)
    u.profile.display_name = name
    u.profile.save()
    c = APIClient()
    c.force_authenticate(u)
    return c, u


@pytest.fixture
def org():
    owner_c, owner = user("owner@acme.in", "Meena")
    o = Organization.objects.create(name="Acme Training", slug="acme")
    Membership.objects.create(org=o, user=owner, role="owner")
    ga, gb = Group.objects.create(org=o, name="A"), Group.objects.create(org=o, name="B")
    t_c, t = user("teach@acme.in", "Bala")
    ga.members.add(Membership.objects.create(org=o, user=t, role="manager"))
    k_c, k = user("kavya@acme.in", "=HYPERLINK(evil)")  # formula-looking name stays text in exports
    ga.members.add(Membership.objects.create(org=o, user=k, role="learner"))
    j_c, j = user("john@acme.in", "John")
    gb.members.add(Membership.objects.create(org=o, user=j, role="learner"))
    return {
        "org": o,
        "owner": owner_c,
        "teacher": t_c,
        "kavya": (k_c, k),
        "john": (j_c, j),
        "ga": ga,
        "gb": gb,
    }


def _course_done(org, who=("kavya",)):
    cur, subs = course(org["org"].memberships.get(role="owner").user, title="Fire safety", approved=False)
    a = Assignment.objects.create(org=org["org"], curriculum=cur)
    for name in who:
        c, u = org[name]
        from apps.learning.models import Enrollment

        Enrollment.objects.get_or_create(user=u, curriculum=cur)
        complete(c, subs)
    return cur, subs, a


def test_course_completion_writes_one_record_with_values_and_certificate(org):
    cur, subs, a = _course_done(org)
    k = org["kavya"][1]
    rec = TrainingRecord.objects.get(user=k)
    assert (rec.kind, rec.title, rec.org_name, rec.curriculum_id, rec.assignment_id) == (
        "course",
        "Fire safety",
        "Acme Training",
        cur.id,
        a.id,
    )
    assert rec.learner_email == "kavya@acme.in" and rec.learner_name == "=HYPERLINK(evil)"
    assert rec.score == 1.0 and rec.minutes and rec.assigned_at == a.created_at and rec.completed_at
    cert = Certificate.objects.get(user=k, kind="course")  # issued by the organisation that assigned it
    assert rec.certificate_id == cert.id and rec.certificate_code == cert.code
    assert rec.verify_url.endswith(f"/verify/{cert.code}") and not rec.backfilled
    complete(org["kavya"][0], subs[:1])  # finishing a lesson again: still one record
    assert TrainingRecord.objects.filter(user=k).count() == 1


def test_partial_course_or_unassigned_course_writes_nothing(org):
    owner, k = org["org"].memberships.get(role="owner").user, org["kavya"][1]
    cur, subs = course(owner, title="Not assigned", approved=False, learner=k)
    complete(org["kavya"][0], subs)
    cur2, subs2 = course(owner, title="Half", approved=False, learner=k)
    Assignment.objects.create(org=org["org"], curriculum=cur2)
    complete(org["kavya"][0], subs2[:1])
    assert not TrainingRecord.objects.exists()


def test_records_are_append_only(org):
    _course_done(org)
    rec = TrainingRecord.objects.get()
    rec.title = "Rewritten"
    with pytest.raises(ValueError):
        rec.save()
    with pytest.raises(ValueError):
        rec.delete()
    assert TrainingRecord.objects.get().title == "Fire safety"


def test_certificate_attaches_once(org):
    _course_done(org)
    rec = TrainingRecord.objects.get()
    other = Certificate.objects.create(
        user=org["kavya"][1], kind="course", title="x", learner_name="K", issuer_name="Aasan", dedupe="other"
    )
    assert TrainingRecord.attach_certificate(rec.pk, other) is False  # already filled at completion
    assert TrainingRecord.objects.get().certificate_code != other.code


def test_certificate_issued_later_is_attached(org):
    c, k = org["kavya"]
    cur, subs = course(
        org["org"].memberships.get(role="owner").user, title="Late cert", approved=False, learner=k
    )
    Assignment.objects.create(org=org["org"], curriculum=cur)
    complete(c, subs, attempt=False)  # no graded attempts → no automatic certificate
    rec = TrainingRecord.objects.get()
    assert rec.certificate_id is None
    from apps.credentials.services import issue

    cert, _ = issue(k, "course", cur, org=org["org"])
    rec = TrainingRecord.objects.get()
    assert rec.certificate_id == cert.id and rec.certificate_code == cert.code


def test_roleplay_finish_writes_a_scenario_record(org, monkeypatch):
    from apps.roleplay import coach, services

    sc = Scenario.objects.create(
        title="Angry customer",
        summary="s",
        learner_role="agent",
        character={},
        setting="shop",
        opening_line="Hi",
    )
    a = Assignment.objects.create(org=org["org"], scenario=sc)
    k = org["kavya"][1]
    s = RolePlaySession.objects.create(user=k, scenario=sc, assignment=a)
    RolePlaySession.objects.filter(pk=s.pk).update(started_at=timezone.now() - timedelta(minutes=12))
    monkeypatch.setattr(services, "evaluate", lambda session: {"overall": 82, "competencies": []})
    monkeypatch.setattr(coach, "summary", lambda session: {})
    services.finish(RolePlaySession.objects.get(pk=s.pk))
    rec = TrainingRecord.objects.get(user=k)
    assert (rec.kind, rec.title, rec.scenario_id, rec.score, rec.assignment_id) == (
        "scenario",
        "Angry customer",
        sc.id,
        0.82,
        a.id,
    )
    assert 11 <= rec.minutes <= 13
    personal = RolePlaySession.objects.create(user=org["john"][1], scenario=sc)
    services.finish(personal)  # practice outside an assignment: no organisation record
    assert TrainingRecord.objects.count() == 1


def test_knowledge_test_pass_writes_a_test_record(org):
    s = Survey.objects.create(
        org=org["org"],
        title="Fire test",
        kind="test",
        anonymous=False,
        status="open",
        pass_mark=50,
        max_attempts=0,
        questions=[{"id": "q1", "type": "choice", "text": "Exit?", "options": ["a", "b"], "correct": "a"}],
    )
    jc, j = org["john"]
    assert (
        jc.post(f"/api/orgs/surveys/{s.id}/respond/", {"answers": {"q1": "b"}}, format="json").status_code
        == 201
    )
    assert not TrainingRecord.objects.exists()  # failed attempt
    assert (
        jc.post(f"/api/orgs/surveys/{s.id}/respond/", {"answers": {"q1": "a"}}, format="json").status_code
        == 201
    )
    rec = TrainingRecord.objects.get()
    assert (rec.kind, rec.survey_id, rec.score, rec.user_id) == ("test", s.id, 1.0, j.id)


def pass_org_workshop(org):
    """Owner schedules an organisation run for class A; Kavya passes the final through the API."""
    from apps.workshops.content import seed
    from apps.workshops.models import WorkshopRun
    from tests.test_workshops_org import _start_session

    seed()
    o = org["org"]
    o.features, o.workshop_seats = {"workshops": True}, 10
    o.save()
    r = org["owner"].post(
        f"/api/orgs/{o.slug}/workshops/runs/",
        {
            "workshop_slug": "quick-check",
            "starts_at": (timezone.now() + timedelta(days=1)).isoformat(),
            "groups": [org["ga"].id],
        },
        format="json",
    )
    assert r.status_code == 201, r.data
    run = WorkshopRun.objects.get(pk=r.data["id"])
    run.starts_at = timezone.now() - timedelta(minutes=1)
    run.save()
    kc, k = org["kavya"]
    s = _start_session(run, k)
    w = run.workshop
    idx = next(i for i, st in enumerate(w.agenda) if st["kind"] == "assessment")
    type(s).objects.filter(pk=s.pk).update(stage_index=idx)
    answers = {str(i): m["answer"] for i, m in enumerate(w.final["mcqs"])}
    res = kc.post(
        f"/api/workshops/sessions/{s.id}/final/", {"answers": answers, "practical": "x y z"}, format="json"
    )
    assert res.status_code == 200 and res.data["passed"] is True
    return run, res


def test_org_workshop_pass_writes_a_workshop_record_with_certificate(org):
    run, res = pass_org_workshop(org)
    k = org["kavya"][1]
    rec = TrainingRecord.objects.get(kind="workshop")
    cert = Certificate.objects.get(user=k, kind="workshop")
    assert rec.workshop_run_id == run.id and rec.title == run.workshop.title and rec.certificate_id == cert.id
    assert rec.score == pytest.approx(res.data["score"]) and rec.minutes


# ── Reading and exports ──────────────────────────────────────────────


def test_org_list_csv_xlsx_pdf_and_formula_safety(org):
    _course_done(org)
    url = "/api/orgs/acme/training-records/"
    r = org["owner"].get(url)
    assert r.status_code == 200 and r.data["count"] == 1
    row = r.data["results"][0]
    assert row["learner"] == "=HYPERLINK(evil)" and row["score"] == 100 and row["kind"] == "course"
    assert org["owner"].get(url, {"kind": "test"}).data["count"] == 0
    assert org["owner"].get(url, {"from": "2999-01-01"}).data["count"] == 0
    assert org["owner"].get(url, {"from": "2026-02-31"}).data["count"] == 1  # impossible date: ignored
    body = org["owner"].get(url, {"export": "csv"}).content.decode()
    rows = list(csv.DictReader(io.StringIO(body)))
    assert rows[0]["learner"] == "'=HYPERLINK(evil)"  # formula injection neutralised
    x = org["owner"].get("/api/orgs/acme/training-records.xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"
    from openpyxl import load_workbook

    ws = load_workbook(io.BytesIO(x.content)).active
    assert ws.cell(2, 1).value == "=HYPERLINK(evil)" and ws.cell(2, 1).data_type == "s"
    p = org["owner"].get("/api/orgs/acme/training-records.pdf")
    assert p.status_code == 200 and p.content[:4] == b"%PDF" and p["Content-Type"] == "application/pdf"


def test_pdf_escapes_markup_in_titles():
    from apps.orgs.records import HEADER
    from apps.studio.exports import records_pdf

    evil = '<img src="http://evil.example/x.png"/><b>x'
    pdf = records_pdf(evil, HEADER, [[evil] * len(HEADER)])
    assert pdf[:4] == b"%PDF"


def test_scope_teacher_learner_and_own_record(org):
    _course_done(org, who=("kavya", "john"))
    assert org["owner"].get("/api/orgs/acme/training-records/").data["count"] == 2
    t = org["teacher"].get("/api/orgs/acme/training-records/")  # class A teacher: only class A learners
    assert t.status_code == 200 and [r["email"] for r in t.data["results"]] == ["kavya@acme.in"]
    kc, k = org["kavya"]
    assert kc.get("/api/orgs/acme/training-records/").status_code == 403
    assert kc.get("/api/orgs/acme/training-records.xlsx").status_code == 403
    mine = kc.get("/api/orgs/me/training-record/")
    assert mine.status_code == 200 and len(mine.data) == 1 and mine.data[0]["title"] == "Fire safety"
    assert kc.get("/api/orgs/me/training-record.pdf").content[:4] == b"%PDF"
    assert kc.get("/api/orgs/me/training-record.xlsx").content[:2] == b"PK"
    assert APIClient().get("/api/orgs/me/training-record/").status_code == 401
    outsider_c, _ = user("x@else.in", "X")
    assert outsider_c.get("/api/orgs/acme/training-records/").status_code == 404


def test_backfill_is_idempotent_and_marks_rows(org):
    _course_done(org, who=("kavya", "john"))
    TrainingRecord.objects.all().delete()  # pretend they predate records
    call_command("backfill_training_records")
    assert TrainingRecord.objects.filter(backfilled=True).count() == 2
    call_command("backfill_training_records", org="acme")
    assert TrainingRecord.objects.count() == 2


def test_account_deletion_anonymises_records(org):
    _course_done(org)
    org["kavya"][1].delete()
    rec = TrainingRecord.objects.get()
    assert rec.user_id is None and rec.learner_name == "Deleted learner" and rec.learner_email == ""
    assert rec.title == "Fire safety"  # the organisation keeps the fact of the training
