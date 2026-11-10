"""Phase 11 activity types: map, image hotspot, video, browser task (vision-graded), mini role-play; lesson images."""

import base64
import io
import json

import pytest
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.learning import activities as acts
from apps.learning.models import Activity, ActivityAttempt, Curriculum, Enrollment, Section, Subsection
from apps.learning.services import _valid
from apps.media.models import MediaAsset
from apps.roleplay.models import RolePlaySession
from llm.prompts.curriculum import FlatActivity, to_typed

pytestmark = pytest.mark.django_db
PW = "Creator#2026pass"


def client_for(email, creator=False):
    u = User.objects.create_user(email, PW, is_creator=creator)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def png_bytes(color=(10, 120, 200), size=(64, 48), exif=False):
    buf = io.BytesIO()
    img = Image.new("RGB", size, color)
    if exif:
        ex = Image.Exif()
        ex[0x8825] = {2: (13, 5, 0)}  # GPSInfo
        img.save(buf, "JPEG", exif=ex.tobytes())
    else:
        img.save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def lesson():
    c, u = client_for("teacher@aasan.test", creator=True)
    cur = Curriculum.objects.create(
        owner=u, kind=Curriculum.Kind.AUTHORED, goal="Geography", title="Geography", status="ready"
    )
    sec = Section.objects.create(curriculum=cur, order=0, title="India")
    sub = Subsection.objects.create(
        section=sec, order=0, title="Rivers", objective="Locate rivers", lesson_status="ready"
    )
    return c, u, cur, sub


def add(sub, typed):
    payload, key = acts.build(typed, seed=1)
    return Activity.objects.create(
        subsection=sub,
        order=sub.activities.count(),
        type=typed["type"],
        title=typed["title"],
        payload=payload,
        key=key,
        source=typed,
    )


# ── map ───────────────────────────────────────────────────────────────

MAP = {
    "type": "map",
    "title": "Find the cities",
    "prompt": "Find them",
    "region": "india",
    "explanation": "",
    "places": [
        {"name": "Chennai", "lat": 13.08, "lon": 80.27, "hint": ""},
        {"name": "Delhi", "lat": 28.61, "lon": 77.21, "hint": ""},
    ],
}


def test_map_from_flat_llm_output_and_validity():
    flat = FlatActivity(
        type="map",
        title="t",
        prompt="p",
        explanation="e",
        extra=json.dumps({"region": "india", "places": MAP["places"]}),
    )
    typed = to_typed(flat)
    assert typed and typed["region"] == "india" and _valid(typed)
    bad = {
        **typed,
        "places": [{"name": "Nowhere", "lat": 51.5, "lon": -0.1, "hint": ""}, MAP["places"][0]],
    }  # London is not in India
    assert not _valid(bad)


def test_map_grading_by_distance_and_coords_hidden(lesson):
    _, _, _, sub = lesson
    a = add(sub, MAP)
    assert "lat" not in json.dumps(a.payload)
    g = acts.grade(
        a, {"points": {"p0": {"lat": 13.1, "lon": 80.3}, "p1": {"lat": 19.07, "lon": 72.87}}}, "en"
    )  # Delhi clicked on Mumbai
    assert g.score == 0.5 and g.reveal["km"]["p0"] < 10 and g.reveal["km"]["p1"] > 1000


# ── hotspot ───────────────────────────────────────────────────────────


def test_hotspot_grading(lesson):
    _, u, _, sub = lesson
    m = MediaAsset.objects.create(owner=u, name="a" * 32 + ".webp")
    typed = {
        "type": "hotspot",
        "title": "Parts",
        "prompt": "Label",
        "image": m.url,
        "explanation": "",
        "targets": [
            {"label": "Input", "x": 20, "y": 50, "r": 8},
            {"label": "Output", "x": 80, "y": 50, "r": 8},
        ],
    }
    assert _valid(typed)
    assert not _valid({**typed, "image": "https://evil.example/x.png"})
    a = add(sub, typed)
    assert "x" not in json.dumps(a.payload["labels"])
    ids = {lb["label"]: lb["id"] for lb in a.payload["labels"]}
    g = acts.grade(a, {"points": {ids["Input"]: {"x": 22, "y": 49}, ids["Output"]: {"x": 20, "y": 50}}}, "en")
    assert g.score == 0.5


# ── video (creator-only) ──────────────────────────────────────────────

VIDEO = {
    "type": "video",
    "title": "Watch",
    "prompt": "Watch and answer",
    "video_id": "dQw4w9WgXcQ",
    "start": 10,
    "end": 120,
    "explanation": "",
    "checkpoints": [
        {"at": 30, "question": "Q1", "options": ["a", "b"], "correct": [1]},
        {"at": 90, "question": "Q2", "options": ["a", "b", "c"], "correct": [0]},
    ],
}


def test_video_needs_handmade_source_and_grades(lesson):
    c, _, _, sub = lesson
    assert (
        c.post(f"/api/lab/subsections/{sub.id}/activities/", {"type": "video"}, format="json").data["code"]
        == "needs_source"
    )
    bad = c.post(
        f"/api/lab/subsections/{sub.id}/activities/",
        {"type": "video", "source": {**VIDEO, "video_id": "not a video"}},
        format="json",
    )
    assert bad.status_code == 400
    r = c.post(
        f"/api/lab/subsections/{sub.id}/activities/", {"type": "video", "source": VIDEO}, format="json"
    )
    assert r.status_code == 201
    a = Activity.objects.get(pk=r.data["id"])
    assert "correct" not in json.dumps(a.payload)
    g = acts.grade(a, {"answers": {"v0": [1], "v1": [2]}}, "en")
    assert g.score == 0.5


def test_ai_drafts_video_questions(lesson):
    c, _, _, sub = lesson
    r = c.post(
        f"/api/lab/subsections/{sub.id}/video-questions/",
        {"notes": "0:45 a model learns from many examples of data"},
        format="json",
    )
    assert r.status_code == 200 and r.data["checkpoints"][0]["at"] == 45


# ── browser task: screenshot graded by vision, never stored ──────────


def test_browser_task_screenshot_graded_and_not_stored(lesson):
    _, _, cur, sub = lesson
    a = add(
        sub,
        {
            "type": "browser_task",
            "title": "Prompt it",
            "prompt": "Ask a chatbot",
            "steps": ["Open", "Ask"],
            "link": "https://claude.ai",
            "proof": "the chatbot's answer",
            "rubric": ["shows answer"],
            "model_answer": "an answer",
        },
    )
    learner, lu = client_for("kid@aasan.test")
    Enrollment.objects.create(user=lu, curriculum=cur)
    cur.visibility, cur.published_at = "link", timezone.now()
    cur.save()
    shot = "data:image/png;base64," + base64.b64encode(png_bytes()).decode()
    assert (
        learner.post(
            f"/api/learn/activities/{a.id}/attempt/", {"answer": {"text": "no picture"}}, format="json"
        ).data["score"]
        == 0
    )
    r = learner.post(
        f"/api/learn/activities/{a.id}/attempt/", {"answer": {"image": shot, "text": "done"}}, format="json"
    )
    assert r.status_code == 200 and r.data["score"] == 0.9
    stored = ActivityAttempt.objects.filter(activity=a).order_by("-id").first().answer
    assert stored["image"] == "[screenshot not stored]" and "base64" not in json.dumps(stored)


# ── mini role-play ────────────────────────────────────────────────────


def test_roleplay_activity_flow(lesson):
    _, _, cur, sub = lesson
    flat = FlatActivity(
        type="roleplay",
        title="Ask for directions",
        prompt="Practise",
        extra=json.dumps(
            {
                "character_name": "Murugan",
                "character_persona": "a friendly auto driver",
                "learner_role": "a tourist",
                "setting": "Chennai Central",
                "goal": "get to Marina Beach",
                "opening_line": "Vanakkam! Where to?",
                "objectives": ["Ask politely", "Agree a fare"],
            }
        ),
    )
    typed = to_typed(flat)
    assert typed and _valid(typed)
    a = add(sub, typed)
    learner, lu = client_for("kid2@aasan.test")
    Enrollment.objects.create(user=lu, curriculum=cur)
    cur.visibility, cur.published_at = "link", timezone.now()
    cur.save()
    sid = learner.post(f"/api/learn/activities/{a.id}/roleplay/").data["session_id"]
    assert (
        learner.post(f"/api/learn/activities/{a.id}/roleplay/").data["session_id"] == sid
    )  # resumes, no duplicate
    s = RolePlaySession.objects.get(pk=sid)
    assert s.scenario.character["name"] == "Murugan" and s.turns.first().text == "Vanakkam! Where to?"
    assert learner.get(f"/api/roleplay/sessions/{sid}/").data["lesson"]["activity_id"] == a.id
    assert (
        learner.post(f"/api/learn/activities/{a.id}/attempt/", {"answer": {}}, format="json").data["score"]
        == 0
    )
    s.status, s.result = "completed", {"overall": 80, "summary": "Polite and clear."}
    s.save()
    r = learner.post(f"/api/learn/activities/{a.id}/attempt/", {"answer": {}}, format="json")
    assert r.data["score"] == 0.8 and r.data["feedback"] == "Polite and clear."
    other, _ = client_for("other@aasan.test")
    assert other.post(f"/api/learn/activities/{a.id}/roleplay/").status_code == 404


# ── lesson images ─────────────────────────────────────────────────────


def test_upload_strips_metadata_and_serves_safely(lesson, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    c, _, _, _ = lesson
    from django.core.files.uploadedfile import SimpleUploadedFile

    r = c.post(
        "/api/media/upload/",
        {"file": SimpleUploadedFile("p.jpg", png_bytes(exif=True), "image/jpeg")},
        format="multipart",
    )
    assert r.status_code == 201 and r.data["url"].endswith(".webp")
    got = APIClient().get(r.data["url"])  # public by unguessable name
    assert (
        got.status_code == 200 and got["Content-Type"] == "image/webp" and "immutable" in got["Cache-Control"]
    )
    body = b"".join(got.streaming_content)
    assert b"Exif" not in body and Image.open(io.BytesIO(body)).format == "WEBP"
    fake = c.post(
        "/api/media/upload/",
        {"file": SimpleUploadedFile("x.png", b"<?php evil ?>", "image/png")},
        format="multipart",
    )
    assert fake.status_code == 400 and fake.data["code"] == "bad_image"
    assert APIClient().get("/api/media/../../etc/passwd").status_code == 404
    assert APIClient().get("/api/media/" + "b" * 32 + ".webp").status_code == 404


def test_generate_image_creator_only(lesson, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    c, _, _, _ = lesson
    r = c.post("/api/media/generate/", {"prompt": "a river delta from above"}, format="json")
    assert r.status_code == 201 and r.data["kind"] == "generated"
    learner, _ = client_for("kid3@aasan.test")
    assert learner.post("/api/media/generate/", {"prompt": "a river delta"}, format="json").status_code == 403
    assert len(c.get("/api/media/mine/").data) == 1


def test_activity_image_must_be_our_media(lesson):
    _, u, _, sub = lesson
    m = MediaAsset.objects.create(owner=u, name="c" * 32 + ".webp")
    quiz = {
        "type": "quiz",
        "title": "Q",
        "prompt": "What is this?",
        "options": ["a", "b"],
        "correct": [0],
        "multiple": False,
        "explanation": "",
    }
    assert add(sub, {**quiz, "image": m.url}).payload["image"] == m.url
    assert "image" not in add(sub, {**quiz, "image": "https://tracker.example/pixel.gif"}).payload
