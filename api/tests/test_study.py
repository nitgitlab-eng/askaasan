"""Milestone 3: lesson translation, hint ladder, explain, Today stations, planner blocks/pauses/buddies, progress + ask."""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.game.models import XPEvent
from apps.game.services import award, stats_for
from apps.learning import activities as acts
from apps.learning.models import Activity, ActivityAttempt, Curriculum, Section, Subsection
from apps.review.models import MasteryRecord, ReviewCard
from apps.study.models import ActivityHint, LessonTranslation, StudyBlock

pytestmark = pytest.mark.django_db


def client_for(email):
    u = User.objects.create_user(email, "Study#2026pass")
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def _lesson(u):
    cur = Curriculum.objects.create(
        owner=u, goal="SQL basics", title="SQL from zero", status="ready", skills=["SQL"], language="en"
    )
    sec = Section.objects.create(curriculum=cur, order=0, title="Start")
    sub = Subsection.objects.create(
        section=sec,
        order=0,
        title="What is a table?",
        objective="Know rows and columns",
        skills=["SQL"],
        lesson_status="ready",
        explanation_md="A **table** has rows and columns.\n\n```sql\nSELECT * FROM t;\n```",
        key_points=["Rows are records"],
    )
    specs = [
        {
            "type": "quiz",
            "title": "Q",
            "prompt": "What is a row?",
            "options": ["A record", "A column"],
            "correct": [0],
            "explanation": "A row is one record.",
        },
        {
            "type": "fill_blank",
            "title": "F",
            "prompt": "Fill",
            "text": "A table has rows and [[b0]].",
            "blanks": [{"id": "b0", "answers": ["columns"]}],
            "explanation": "Columns.",
        },
        {
            "type": "categorization",
            "title": "C",
            "prompt": "Sort",
            "categories": ["Row", "Column"],
            "items": [
                {"text": "One customer", "category": "Row"},
                {"text": "Email field", "category": "Column"},
            ],
            "explanation": "Sorted.",
        },
    ]
    out = []
    for i, s in enumerate(specs):
        payload, key = acts.build(s, i)
        out.append(
            Activity.objects.create(
                subsection=sub, order=i, type=s["type"], title=s["title"], payload=payload, key=key
            )
        )
    return cur, sub, out


def test_translation_overlays_text_keeps_ids_and_grades_in_original(django_capture_on_commit_callbacks):
    c, u = client_for("tr@x.in")
    cur, sub, (quiz, fill, cat) = _lesson(u)
    with django_capture_on_commit_callbacks(execute=True):
        first = c.get(f"/api/learn/subsections/{sub.id}/?lang=hi").data
    assert first["translation"]["status"] in ("translating", "ready")
    d = c.get(f"/api/learn/subsections/{sub.id}/?lang=hi").data
    assert d["translation"] == {
        "lang": "hi",
        "status": "ready",
        "available": list(d["translation"]["available"]),
        "source": "en",
    }
    assert (
        d["title"].startswith("«T»")
        and d["explanation_md"].startswith("«T»")
        and "```sql" in d["explanation_md"]
    )
    assert d["section"]["title"] == "«T» Start" and all(a["title"].startswith("«T»") for a in d["activities"])
    q = next(a for a in d["activities"] if a["id"] == quiz.id)
    assert q["payload"]["options"][0].startswith("«T»") and "correct" not in q["payload"]  # keys never leak
    f = next(a for a in d["activities"] if a["id"] == fill.id)
    assert "[[b0]]" in f["payload"]["text"] and f["payload"]["blank_ids"] == ["b0"]
    # Original language and unknown languages are served untouched, without creating rows.
    assert c.get(f"/api/learn/subsections/{sub.id}/?lang=en").data["title"] == "What is a table?"
    assert c.get(f"/api/learn/subsections/{sub.id}/?lang=xx").data["title"] == "What is a table?"
    assert LessonTranslation.objects.count() == 1
    # Grading: translated category names and blank answers map back to the original key.
    ct = next(a for a in d["activities"] if a["id"] == cat.id)["payload"]
    row_t, col_t = ct["categories"]
    items = {i["text"]: i["id"] for i in ct["items"]}
    assign = {items["«T» One customer"]: row_t, items["«T» Email field"]: col_t}
    r = c.post(
        f"/api/learn/activities/{cat.id}/attempt/",
        {"answer": {"assign": assign}, "lang": "hi"},
        format="json",
    ).data
    assert r["score"] == 1.0 and r["feedback"].startswith("«T»")
    r = c.post(
        f"/api/learn/activities/{fill.id}/attempt/",
        {"answer": {"blanks": {"b0": "«T» columns"}}, "lang": "hi"},
        format="json",
    ).data
    assert r["score"] == 1.0
    assert Activity.objects.get(id=fill.id).key["blanks"] == {"b0": ["columns"]}  # stored key unchanged


def test_translation_retranslates_after_edit_and_budget(django_capture_on_commit_callbacks):
    from apps.study import translation

    c, u = client_for("tr2@x.in")
    _, sub, _ = _lesson(u)
    with django_capture_on_commit_callbacks(execute=True):
        c.get(f"/api/learn/subsections/{sub.id}/?lang=ta")
    sub.explanation_md = "Edited text"
    sub.save()
    with django_capture_on_commit_callbacks(execute=True):
        c.get(f"/api/learn/subsections/{sub.id}/?lang=ta")
    assert LessonTranslation.objects.get(subsection=sub, lang="ta").explanation_md == "«T» Edited text"
    translation.TRANSLATIONS_PER_DAY = 2  # two already charged today (0 would mean unlimited)
    try:
        sub2 = Subsection.objects.create(
            section=sub.section, order=1, title="Next", lesson_status="ready", explanation_md="x"
        )
        assert c.get(f"/api/learn/subsections/{sub2.id}/?lang=te").data["translation"]["status"] == "budget"
    finally:
        translation.TRANSLATIONS_PER_DAY = 30


def test_hint_ladder_order_cost_and_cache():
    c, u = client_for("hint@x.in")
    _, sub, (quiz, *_rest) = _lesson(u)
    assert (
        c.post(f"/api/study/activities/{quiz.id}/hint/", {"level": 2}, format="json").data["code"]
        == "previous_level_first"
    )
    r = c.post(f"/api/study/activities/{quiz.id}/hint/", {"level": 1}, format="json").data
    assert r["cost"] == 0 and r["text"] and r["next_cost"] == 2
    assert (
        c.post(f"/api/study/activities/{quiz.id}/hint/", {"level": 2}, format="json").status_code == 402
    )  # no coins yet
    s = stats_for(u)
    s.coins = 10
    s.save()
    r = c.post(f"/api/study/activities/{quiz.id}/hint/", {"level": 2}, format="json").data
    assert r["cost"] == 2 and r["coins"] == 8
    assert (
        c.post(f"/api/study/activities/{quiz.id}/hint/", {"level": 2}, format="json").data["cost"] == 0
    )  # repeat is free
    assert c.get(f"/api/study/activities/{quiz.id}/hints/").data["used"] == [1, 2]
    other, _ = client_for("hint2@x.in")
    assert (
        other.post(f"/api/study/activities/{quiz.id}/hint/", {"level": 1}, format="json").status_code == 404
    )  # not their course
    assert ActivityHint.objects.filter(activity=quiz).count() == 2


def test_explain_selection():
    c, u = client_for("ex@x.in")
    _, sub, _ = _lesson(u)
    assert c.post(
        "/api/study/explain/", {"text": "rows and columns", "subsection_id": sub.id}, format="json"
    ).data["text"]
    assert (
        c.post("/api/study/explain/", {"text": "x", "subsection_id": sub.id}, format="json").status_code
        == 400
    )
    assert (
        c.post("/api/study/explain/", {"text": "rows", "subsection_id": "abc"}, format="json").status_code
        == 400
    )


def test_today_stations_swap_focus_done_and_board():
    c, u = client_for("today@x.in")
    _, sub, (quiz, fill, cat) = _lesson(u)
    for a in (quiz, fill, cat):
        ReviewCard.objects.create(user=u, activity=a, due=timezone.now() - timedelta(hours=1))
    MasteryRecord.objects.create(user=u, subsection=sub, p_known=0.3)
    d = c.get("/api/study/today/").data
    keys = [s["key"] for s in d["stations"]]
    assert {"review", "weak", "quiz"} <= set(keys)
    assert c.post("/api/study/today/swap/", {"key": "review"}, format="json").status_code == 400
    assert c.post("/api/study/today/swap/", {"key": "weak"}, format="json").data["swaps_left"] == 9
    assert c.post("/api/study/today/focus/", {"focus": "nope"}, format="json").status_code == 400
    assert c.post("/api/study/today/focus/", {"focus": "sql"}, format="json").data["focus"] == "sql"
    ReviewCard.objects.filter(user=u).update(due=timezone.now() + timedelta(days=3))
    d = c.get("/api/study/today/").data
    assert next(s for s in d["stations"] if s["key"] == "review")["done"]  # auto-done when nothing is due
    for s in d["stations"]:
        r = c.post("/api/study/today/done/", {"key": s["key"]}, format="json").data
    assert r["done"] == r["total"] and r["reward"]["xp"] == 20
    q = c.get("/api/review/session/?mode=quick").data
    assert q["mode"] == "quick" and 1 <= len(q["cards"]) <= 5
    board = c.get("/api/study/revision-board/").data
    assert board["me"]["stations"] >= 3


def test_planner_blocks_skip_replan_move_custom():
    c, u = client_for("plan@x.in")
    prefs = u.preferences
    prefs.data = {
        **prefs.data,
        "learning": {
            "study_days": [0, 1, 2, 3, 4, 5, 6],
            "daily_goal_minutes": 20,
            "reminder_times": ["18:30"],
        },
    }
    prefs.save()
    d = c.get("/api/study/blocks/").data
    today = timezone.localdate()
    todays = [b for b in d["blocks"] if b["date"] == today]
    assert (
        [b["kind"] for b in todays] == ["today", "lesson"]
        and todays[0]["start"] == "18:30"
        and todays[1]["start"] == "18:35"
    )
    again = c.get("/api/study/blocks/").data
    assert len(again["blocks"]) == len(d["blocks"])  # idempotent
    main = todays[1]
    r = c.post(f"/api/study/blocks/{main['id']}/", {"action": "skip"}, format="json").data
    assert r["moved_to"] == today + timedelta(days=1)
    moved = StudyBlock.objects.get(user=u, moved_from=today)
    assert moved.date == today + timedelta(days=1) and moved.start >= "18:30"
    assert (
        c.post(f"/api/study/blocks/{main['id']}/", {"action": "delete"}, format="json").data["code"]
        == "skip_instead"
    )
    r = c.post(
        "/api/study/blocks/",
        {"date": str(today), "start": "07:00", "minutes": 30, "title": "Revise SQL notes"},
        format="json",
    )
    assert r.status_code == 201
    custom = StudyBlock.objects.get(user=u, kind="custom")
    c.post(
        f"/api/study/blocks/{custom.id}/",
        {"action": "move", "date": str(today + timedelta(days=2)), "start": "08:00"},
        format="json",
    )
    custom.refresh_from_db()
    assert custom.moved_from == today and custom.start == "08:00"
    assert (
        c.post(
            f"/api/study/blocks/{custom.id}/",
            {"action": "move", "date": str(today + timedelta(days=400))},
            format="json",
        ).status_code
        == 400
    )
    other, _ = client_for("plan2@x.in")
    assert other.post(f"/api/study/blocks/{custom.id}/", {"action": "done"}, format="json").status_code == 404
    ics = c.get("/api/game/plan.ics").content.decode()
    assert "Revise SQL notes" in ics


def test_pause_protects_streak_mutes_reminders_and_clears_blocks():
    from apps.accounts.study_reminders import send_due
    from apps.game.services import _touch_streak

    c, u = client_for("pause@x.in")
    today = timezone.localdate()
    c.get(
        f"/api/study/blocks/?week={today + timedelta(days=1)}"
    )  # the week holding tomorrow (on Sundays that's next week)
    assert StudyBlock.objects.filter(user=u, date=today + timedelta(days=1)).exists()
    r = c.post(
        "/api/study/pauses/",
        {"start": str(today), "end": str(today + timedelta(days=3)), "reason": "exams"},
        format="json",
    )
    assert r.status_code == 200 and r.data[0]["active"]
    assert not StudyBlock.objects.filter(user=u, auto=True, date=today + timedelta(days=1)).exists()
    assert (
        c.post(
            "/api/study/pauses/", {"start": str(today), "end": str(today + timedelta(days=90))}, format="json"
        ).status_code
        == 400
    )
    # Streak: a gap fully covered by the pause keeps the streak.
    s = stats_for(u)
    s.streak, s.last_active = 5, today - timedelta(days=1)
    _touch_streak(s, today + timedelta(days=4))
    assert s.streak == 6
    s.streak, s.last_active = 5, today - timedelta(days=3)  # gap includes an un-paused day → resets
    _touch_streak(s, today + timedelta(days=1))
    assert s.streak == 1
    # Reminder at the learner's time is skipped while paused.
    now = timezone.localtime().replace(second=0, microsecond=0)
    p = u.preferences
    p.data = {**p.data, "learning": {"reminder_times": [now.strftime("%H:%M")], "study_days": list(range(7))}}
    p.save()
    assert send_due(now) == 0
    pid = r.data[0]["id"]
    assert c.delete(f"/api/study/pauses/{pid}/").status_code == 204
    assert send_due(now) == 1


def test_buddies_invite_accept_view_remove():
    a, ua = client_for("a@x.in")
    b, ub = client_for("b@x.in")
    r = a.post("/api/study/buddies/", format="json")
    link = r.data["pending"][0]["link"]
    token = link.rsplit("/", 1)[1]
    assert a.post(f"/api/study/buddy/{token}/", format="json").data["code"] == "own_invite"
    assert b.get(f"/api/study/buddy/{token}/").data["accepted"] is False
    assert b.post(f"/api/study/buddy/{token}/", format="json").data["ok"]
    cc, _ = client_for("c@x.in")
    assert cc.post(f"/api/study/buddy/{token}/", format="json").status_code == 409  # single use
    award(ub, "lesson_complete", ref="x")
    rows = a.get("/api/study/buddies/").data["buddies"]
    assert rows[0]["streak"] == 1 and rows[0]["studied_days"]
    assert b.get("/api/study/buddies/").data["buddies"][0]["name"]  # mutual
    assert cc.delete(f"/api/study/buddies/{rows[0]['id']}/").status_code == 404
    assert a.delete(f"/api/study/buddies/{rows[0]['id']}/").status_code == 204


def test_progress_dashboard_insights_and_ask():
    c, u = client_for("prog@x.in")
    _, sub, (quiz, fill, cat) = _lesson(u)
    now = timezone.now()
    for i, a in enumerate((quiz, fill, cat)):
        at = ActivityAttempt.objects.create(
            user=u, activity=a, answer={}, score=1.0 if i else 0.0, correct=bool(i), feedback=""
        )
        ActivityAttempt.objects.filter(id=at.id).update(created_at=now - timedelta(minutes=10 - 4 * i))
    MasteryRecord.objects.create(user=u, subsection=sub, p_known=0.6)
    XPEvent.objects.create(user=u, kind="lesson", xp=30, day=timezone.localdate())
    d = c.get("/api/study/progress/?days=14").data
    assert d["totals"]["xp"] == 30 and d["totals"]["sessions"] == 1 and d["totals"]["minutes"] >= 8
    assert d["totals"]["first_try_accuracy"] == 67 and len(d["minutes"]) == 14
    assert any(n["type"] == "skill" for n in d["graph"]["nodes"]) and d["graph"]["edges"]
    assert {r["type"] for r in d["efficiency"]} == {"quiz", "fill_blank", "categorization"}
    ins = c.post("/api/study/progress/insights/").data
    assert (
        ins["headline"]
        and ins["cached"] is False
        and c.post("/api/study/progress/insights/").data["cached"] is True
    )
    ask = c.post(
        "/api/study/progress/ask/", {"question": "How much XP did I earn each day?"}, format="json"
    ).data
    assert (
        ask["supported"]
        and ask["metric"] == "xp"
        and ask["group_by"] == "day"
        and sum(r["value"] for r in ask["data"]) == 30
    )
    assert c.post("/api/study/progress/ask/", {"question": "x"}, format="json").status_code == 400
    # Whitelist enforced server-side even for odd combos.
    from apps.study.progress import compute

    assert compute(u, "mastery", "day", 30)[0]["label"]  # falls back to an allowed grouping
    assert compute(u, "DROP TABLE", "day", 30)  # unknown metric → xp


def test_progress_pins_preference_validation():
    c, _ = client_for("pins@x.in")
    assert (
        c.patch(
            "/api/users/preferences/", {"learning": {"progress_pins": ["minutes", "skills"]}}, format="json"
        ).status_code
        == 200
    )
    assert (
        c.patch(
            "/api/users/preferences/", {"learning": {"progress_pins": ["evil"]}}, format="json"
        ).status_code
        == 400
    )
    assert (
        c.patch("/api/users/preferences/", {"learning": {"lesson_language": "hi"}}, format="json").status_code
        == 200
    )
    assert (
        c.patch("/api/users/preferences/", {"learning": {"lesson_language": "fr"}}, format="json").status_code
        == 400
    )
