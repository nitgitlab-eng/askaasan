from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from apps.review.models import MasteryRecord, ReviewCard
from apps.review.scheduling import AGAIN, GOOD, HARD, CardState, bkt_update, rating_for, schedule

NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)


# ── pure maths ────────────────────────────────────────────────────────


def test_rating_thresholds():
    assert [rating_for(s) for s in (0.0, 0.69, 0.7, 0.99, 1.0)] == [AGAIN, AGAIN, HARD, HARD, GOOD]


def test_fsrs_schedule_grows_and_resets():
    s, due = schedule(CardState(), GOOD, NOW)
    assert 2 <= (due - NOW).days <= 4 and 1 <= s.difficulty <= 10  # FSRS-5 first "good" ≈ 3 days
    first = (due - NOW).days
    s.elapsed_days = first
    s, due2 = schedule(s, GOOD, NOW)
    assert (due2 - NOW).days > first  # intervals grow when you keep remembering
    s.elapsed_days = (due2 - NOW).days
    hard, _ = schedule(s, HARD, NOW)
    good, _ = schedule(s, GOOD, NOW)
    assert hard.stability_days < good.stability_days and hard.difficulty > good.difficulty
    s, due = schedule(s, AGAIN, NOW)
    assert s.lapses == 1 and s.reps == 0 and due == NOW + timedelta(minutes=10)


def test_fsrs_migrates_old_sm2_cards():
    old = CardState(stability_days=6.0, ease=2.5, reps=3, lapses=0, difficulty=0.0, elapsed_days=6.0)
    s, due = schedule(old, GOOD, NOW)
    assert s.difficulty > 0 and s.stability_days > 6.0 and (due - NOW).days > 6


def test_bkt_moves_the_right_way():
    p = 0.2
    up = bkt_update(p, True, 0.25)
    down = bkt_update(p, False, 0.25)
    assert up > p and down < up
    for _ in range(6):
        p = bkt_update(p, True, 0.25)
    assert p > 0.9


# ── API ───────────────────────────────────────────────────────────────

pytestmark_db = pytest.mark.django_db


@pytest.fixture
def lesson(auth):
    client, _ = auth
    cid = client.post("/api/learn/curriculums/", {"goal": "AI basics"}, format="json").data["id"]
    d = client.get(f"/api/learn/curriculums/{cid}/").data
    sub = d["sections"][0]["subsections"][0]["id"]
    return client, cid, client.post(f"/api/learn/subsections/{sub}/start/").data


def _quiz(lesson):
    return next(a for a in lesson["activities"] if a["type"] == "quiz")


@pytest.mark.django_db
def test_attempt_creates_card_and_mastery(lesson):
    client, cid, l = lesson
    q = _quiz(l)
    client.post(
        f"/api/learn/activities/{q['id']}/attempt/", {"answer": {"selected": [0]}}, format="json"
    )  # wrong
    card = ReviewCard.objects.get(activity_id=q["id"])
    assert card.lapses == 1 and card.due <= timezone.now() + timedelta(minutes=11)
    m = MasteryRecord.objects.get(subsection_id=l["id"])
    assert m.observations == 1 and m.p_known < 0.2 + 0.15
    # outline skills keep only real course skills
    d = client.get(f"/api/review/mastery/{cid}/").data
    assert d["nodes"][0]["skills"] == ["AI concepts"]


@pytest.mark.django_db
def test_review_session_flow(lesson):
    client, _, l = lesson
    q = _quiz(l)
    client.post(f"/api/learn/activities/{q['id']}/attempt/", {"answer": {"selected": [0]}}, format="json")
    ReviewCard.objects.update(due=timezone.now() - timedelta(minutes=1))
    ov = client.get("/api/review/overview/").data
    assert ov["due"] == 1 and ov["by_course"][0]["due"] == 1
    sess = client.get("/api/review/session/").data
    assert len(sess["cards"]) == 1 and "correct" not in str(sess["cards"][0]["activity"]["payload"])
    card_id = sess["cards"][0]["card_id"]
    r = client.post(f"/api/review/cards/{card_id}/answer/", {"answer": {"selected": [1]}}, format="json").data
    assert r["correct"] and r["rating"] == GOOD
    assert client.get("/api/review/overview/").data["due"] == 0


@pytest.mark.django_db
def test_section_checkpoint_includes_unattempted(lesson):
    client, cid, l = lesson
    sec = client.get(f"/api/learn/curriculums/{cid}/").data["sections"][0]["id"]
    sess = client.get(f"/api/review/session/?mode=section&section={sec}").data
    types = {c["activity"]["type"] for c in sess["cards"]}
    assert len(sess["cards"]) >= 4 and types <= {
        "quiz",
        "fill_blank",
        "sequencing",
        "categorization",
        "matching",
        "diagram",
    }
    assert client.get("/api/review/session/?mode=section").status_code == 400


@pytest.mark.django_db
def test_practice_set_is_separate_from_lesson(lesson):
    client, _, l = lesson
    p = client.post(f"/api/learn/subsections/{l['id']}/practice/").data
    assert p["status"] == "ready" and [a["type"] for a in p["activities"]] == ["quiz", "matching"]
    again = client.get(f"/api/learn/subsections/{l['id']}/").data
    assert len(again["activities"]) == len(l["activities"])  # practice not mixed into lesson
    recap = client.post(f"/api/learn/subsections/{l['id']}/complete/").data
    assert recap["total"] == len(l["activities"])


@pytest.mark.django_db
def test_mastery_graph_and_isolation(lesson):
    from apps.accounts.models import User

    client, cid, l = lesson
    q = _quiz(l)
    for _ in range(3):
        client.post(f"/api/learn/activities/{q['id']}/attempt/", {"answer": {"selected": [1]}}, format="json")
    g = client.get(f"/api/review/mastery/{cid}/").data
    first = g["nodes"][0]
    assert first["mastery"] > 0.6 and first["level"] in ("practicing", "mastered")
    assert len(g["edges"]) == len(g["nodes"]) - 1 and g["overall"] > 0
    assert next(s for s in g["skills"] if s["name"] == "AI concepts")["mastery"] > 0.6
    client.force_authenticate(User.objects.create_user("o@example.com", "Other#2026pass"))
    assert client.get(f"/api/review/mastery/{cid}/").status_code == 404
    assert (
        client.post(
            f"/api/review/cards/{ReviewCard.objects.first().id}/answer/", {"answer": {}}, format="json"
        ).status_code
        == 404
    )
