"""Aasan Companion browser extension: pairing, device tokens scoped to /api/ext/, task list, screenshot submit."""

import base64
import io
import json
from datetime import timedelta

import pytest
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.extension.models import ExtensionPairing, ExtensionToken
from apps.learning import activities as acts
from apps.learning.models import (
    Activity,
    ActivityAttempt,
    Curriculum,
    Enrollment,
    Section,
    Subsection,
    UserSubsectionState,
)
from apps.providers.models import UsageCounter

pytestmark = pytest.mark.django_db
PW = "Learner#2026pass"
TASK = {
    "type": "browser_task",
    "title": "Sum it",
    "prompt": "Make a sheet with a SUM",
    "steps": ["Open Sheets", "Type =SUM(A1:A3)"],
    "link": "https://chatgpt.com",
    "proof": "the SUM result",
    "rubric": ["SECRET-RUBRIC"],
    "model_answer": "SECRET-MODEL",
}


def jwt_client(email):
    u = User.objects.create_user(email, PW)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def png_data_url():
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (20, 140, 90)).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def pair(c):
    code = c.post("/api/ext/pair/start/").data["code"]
    r = APIClient().post(
        "/api/ext/pair/claim/",
        {"code": code},
        format="json",
        HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0) Chrome/130 Edg/130",
    )
    assert r.status_code == 200, r.data
    ext = APIClient()
    ext.credentials(HTTP_AUTHORIZATION=f"AasanExt {r.data['token']}")
    return ext, r.data


@pytest.fixture
def course():
    _, owner = jwt_client("teacher@aasan.test")
    cur = Curriculum.objects.create(
        owner=owner,
        kind=Curriculum.Kind.AUTHORED,
        goal="Sheets",
        title="Spreadsheets",
        status="ready",
        visibility="link",
        published_at=timezone.now(),
    )
    sec = Section.objects.create(curriculum=cur, order=0, title="Basics")
    sub = Subsection.objects.create(
        section=sec, order=0, title="Formulas", objective="Use SUM", lesson_status="ready"
    )
    payload, key = acts.build(TASK, seed=1)
    a = Activity.objects.create(
        subsection=sub,
        order=0,
        type="browser_task",
        title=TASK["title"],
        payload=payload,
        key=key,
        source=dict(TASK),
    )
    return cur, sub, a


@pytest.fixture
def learner(course):
    cur, sub, _ = course
    c, u = jwt_client("kid@aasan.test")
    Enrollment.objects.create(user=u, curriculum=cur)
    UserSubsectionState.objects.create(
        user=u, subsection=sub, status="in_progress", started_at=timezone.now()
    )
    return c, u


def test_pairing_code_single_use_and_expiry(learner):
    c, u = learner
    r = c.post("/api/ext/pair/start/")
    assert r.status_code == 201 and len(r.data["code"]) == 6 and r.data["code"].isdigit()
    code = r.data["code"]
    anon = APIClient()
    ok = anon.post("/api/ext/pair/claim/", {"code": code}, format="json")
    assert ok.status_code == 200 and ok.data["user"]["display_name"] and len(ok.data["token"]) > 30
    assert anon.post("/api/ext/pair/claim/", {"code": code}, format="json").status_code == 400  # single use
    tok = ExtensionToken.objects.get(user=u)
    assert tok.token_hash != ok.data["token"] and len(tok.token_hash) == 64  # only the hash is stored
    # Expired codes are refused.
    code2 = c.post("/api/ext/pair/start/").data["code"]
    ExtensionPairing.objects.filter(code=code2).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert anon.post("/api/ext/pair/claim/", {"code": code2}, format="json").status_code == 400
    # A new code replaces the previous live one.
    first = c.post("/api/ext/pair/start/").data["code"]
    c.post("/api/ext/pair/start/")
    assert anon.post("/api/ext/pair/claim/", {"code": first}, format="json").status_code == 400
    assert anon.post("/api/ext/pair/claim/", {"code": "abc"}, format="json").status_code == 400
    assert APIClient().post("/api/ext/pair/start/").status_code == 401  # needs a signed-in user


def test_token_only_works_on_ext_routes_and_revocation(learner):
    c, _ = learner
    ext, _ = pair(c)
    assert ext.get("/api/ext/tasks/").status_code == 200
    for path in ("/api/users/me/", "/api/learn/curriculums/", "/api/ext/devices/"):
        assert ext.get(path).status_code in (401, 403), path
    assert ext.post("/api/ext/pair/start/").status_code in (401, 403)
    # A normal JWT session can't use the extension-only routes either.
    from apps.accounts.tokens import issue_tokens

    web = APIClient()
    web.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(learner[1])['access']}")
    assert web.get("/api/users/me/").status_code == 200
    assert web.get("/api/ext/tasks/").status_code in (401, 403)
    devices = c.get("/api/ext/devices/").data
    assert len(devices) == 1 and devices[0]["name"] == "Edge on Windows"
    other, _ = jwt_client("other@aasan.test")
    assert other.delete(f"/api/ext/devices/{devices[0]['id']}/").status_code == 404
    assert c.delete(f"/api/ext/devices/{devices[0]['id']}/").status_code == 204
    assert ext.get("/api/ext/tasks/").status_code == 401
    assert c.get("/api/ext/devices/").data == []
    ext3, _ = pair(c)
    assert ext3.post("/api/ext/disconnect/").status_code == 204
    assert ext3.get("/api/ext/tasks/").status_code == 401
    bad = APIClient()
    bad.credentials(HTTP_AUTHORIZATION="AasanExt not-a-real-token")
    assert bad.get("/api/ext/tasks/").status_code == 401


def test_tasks_list_scoped_and_without_key(course, learner):
    cur, sub, a = course
    c, u = learner
    ext, _ = pair(c)
    data = ext.get("/api/ext/tasks/").data["tasks"]
    assert [t["id"] for t in data] == [a.id]
    t = data[0]
    assert (
        t["course_title"] == "Spreadsheets"
        and t["lesson_title"] == "Formulas"
        and t["lesson_path"] == f"/learn/{cur.id}/lesson/{sub.id}"
    )
    assert t["hint_host"] == "chatgpt.com" and t["steps"] == TASK["steps"]
    blob = json.dumps(data)
    assert "SECRET-RUBRIC" not in blob and "SECRET-MODEL" not in blob
    # Another learner who hasn't started the lesson (or isn't enrolled) sees nothing of it.
    c2, u2 = jwt_client("someone@aasan.test")
    ext2, _ = pair(c2)
    assert ext2.get("/api/ext/tasks/").data["tasks"] == []
    UserSubsectionState.objects.create(
        user=u2, subsection=sub, status="in_progress", started_at=timezone.now()
    )
    assert ext2.get("/api/ext/tasks/").data["tasks"] == []  # not enrolled → not viewable
    assert (
        ext2.post(
            f"/api/ext/tasks/{a.id}/submit/",
            {"url": "https://chatgpt.com/", "image": png_data_url()},
            format="json",
        ).status_code
        == 404
    )
    # Passed tasks drop off the list.
    ActivityAttempt.objects.create(user=u, activity=a, answer={}, score=1.0, correct=True)
    assert ext.get("/api/ext/tasks/").data["tasks"] == []


def test_submit_grades_records_and_never_stores_image(course, learner):
    _, _, a = course
    c, u = learner
    ext, _ = pair(c)
    r = ext.post(
        f"/api/ext/tasks/{a.id}/submit/",
        {"url": "https://chatgpt.com/c/123", "title": "My sheet", "image": png_data_url()},
        format="json",
    )
    assert r.status_code == 200, r.data
    assert r.data["score"] == 0.9 and r.data["correct"] and r.data["feedback"]
    att = ActivityAttempt.objects.get(user=u, activity=a)
    assert (
        att.answer["image"] == "[screenshot not stored]"
        and att.answer["via"] == "extension"
        and att.answer["url"] == "https://chatgpt.com/c/123"
    )
    assert "base64" not in json.dumps(att.answer)
    assert UsageCounter.objects.get(user=u, metric="ai_grades").amount == 1


@pytest.mark.parametrize(
    "image",
    [
        "data:image/png;base64," + base64.b64encode(b"GIF89a not really an image").decode(),
        "data:image/gif;base64," + base64.b64encode(b"GIF89a").decode(),
        "not a data url",
        "data:image/jpeg;base64,"
        + base64.b64encode(b"\xff\xd8\xff" + b"0" * 2_100_000).decode(),  # over the size cap
    ],
)
def test_submit_rejects_bad_images(course, learner, image):
    _, _, a = course
    c, u = learner
    ext, _ = pair(c)
    r = ext.post(
        f"/api/ext/tasks/{a.id}/submit/", {"url": "https://chatgpt.com/", "image": image}, format="json"
    )
    assert r.status_code == 400 and r.data["code"] == "bad_image"
    assert not ActivityAttempt.objects.filter(user=u).exists()
    assert not UsageCounter.objects.filter(user=u, metric="ai_grades").exists()


def test_submit_enforces_site_rules_before_ai(course, learner):
    _, _, a = course
    a.source = {**a.source, "target_host": "*.google.com"}
    a.save()
    c, u = learner
    ext, _ = pair(c)
    assert ext.get("/api/ext/tasks/").data["tasks"][0]["target_host"] == "*.google.com"
    r = ext.post(
        f"/api/ext/tasks/{a.id}/submit/",
        {"url": "https://evil-google.com/", "image": png_data_url()},
        format="json",
    )
    assert r.status_code == 422 and r.data["code"] == "wrong_site"
    assert (
        ext.post(
            f"/api/ext/tasks/{a.id}/submit/",
            {"url": "javascript:alert(1)", "image": png_data_url()},
            format="json",
        ).status_code
        == 400
    )
    assert not UsageCounter.objects.filter(user=u, metric="ai_grades").exists()
    ok = ext.post(
        f"/api/ext/tasks/{a.id}/submit/",
        {"url": "https://docs.google.com/spreadsheets/d/x", "image": png_data_url()},
        format="json",
    )
    assert ok.status_code == 200 and ok.data["score"] == 0.9
