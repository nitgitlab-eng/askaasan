"""Companion voice catalog: full coverage (moment × language × personality), matching ids and placeholders between
English and Tamil, length limits, skipping variants whose placeholders are missing, rotation, companion emoji and
name, personality fallback, Tamil, and pick() never raising."""

import itertools
import re

import pytest

from apps.accounts import voice
from apps.accounts.companions import COMPANIONS
from apps.accounts.models import ReminderState, User
from apps.accounts.preferences import PERSONALITIES

TAMIL = re.compile(r"[஀-௿]")
LONG = {
    "name": "Meenakshi",
    "companion": "Yaanai",
    "emoji": "🐘",
    "n": 365,
    "hours": 72,
    "minutes": 240,
    "course": "C" * 40,
}
THREE = {"study", "streak_risk", "reviews", "streak_lost_1"}


def _user(email="v@example.com", name="Meena Kumar", lang="en", personality="anna_akka", character="kili"):
    u = User.objects.create_user(email, "Voice#Test2026pw")
    u.profile.display_name = name
    u.profile.language = lang
    u.profile.save()
    p = u.preferences
    p.data = {
        **p.data,
        "mentor": {**p.data["mentor"], "personality": personality},
        "mascot": {**p.data["mascot"], "character": character, "name": COMPANIONS[character]["name"]},
    }
    p.save()
    return u


def test_catalog_covers_every_moment_language_and_personality():
    assert set(voice.PERSONALITIES) == set(PERSONALITIES)
    assert set(voice.EMOJI) == set(COMPANIONS)
    assert set(voice.MOMENTS) == set(voice.GUARANTEED)
    for moment in voice.MOMENTS:
        for lang in voice.LANGS:
            for pers in PERSONALITIES:
                variants = voice.CATALOG[moment][lang][pers]
                assert len(variants) == (3 if moment in THREE else 2), (moment, lang, pers)


def test_english_and_tamil_share_ids_and_placeholders():
    for moment in voice.MOMENTS:
        for pers in PERSONALITIES:
            en, ta = voice.CATALOG[moment]["en"][pers], voice.CATALOG[moment]["ta"][pers]
            assert [v.id for v in en] == [v.id for v in ta]
            for a, b in zip(en, ta, strict=True):
                assert voice.fields(a) == voice.fields(b), a.id
                assert voice.fields(a) <= voice.PLACEHOLDERS, a.id
                assert TAMIL.search(b.title + b.body), b.id  # hand-written Tamil, not a copy
                assert not TAMIL.search(a.title + a.body), a.id
            # Variant 0 only needs what the moment always has, so there is always something to send.
            assert voice.fields(en[0]) <= voice.GUARANTEED[moment], en[0].id


def test_lengths_fit_a_lock_screen():
    for moment in voice.MOMENTS:
        for lang in voice.LANGS:
            for pers in PERSONALITIES:
                for v in voice.CATALOG[moment][lang][pers]:
                    t, b = v.title.format(**LONG), v.body.format(**LONG)
                    assert len(t) <= voice.TITLE_MAX, (v.id, lang, len(t))
                    assert len(b) <= voice.BODY_MAX, (v.id, lang, len(b))


@pytest.mark.django_db
def test_pick_skips_variants_with_missing_placeholders():
    u = _user(name="")
    seen = {voice.pick(u, "study").variant for _ in range(6)}
    # No first name and no course in progress: only the variants that need neither.
    assert seen == {"study.anna_akka.0", "study.anna_akka.2"}
    msgs = [voice.pick(u, "study", course="Excel basics") for _ in range(3)]
    assert any("Excel basics" in m.body for m in msgs) is False  # course variant also needs {name}
    named = _user("named@example.com")
    bodies = [voice.pick(named, "study", course="Excel basics").body for _ in range(3)]
    assert any("Excel basics" in b for b in bodies)


@pytest.mark.django_db
def test_rotation_starts_from_the_user_id_and_never_repeats_twice_running():
    u = _user()
    first = voice.pick(u, "reviews", n=7)
    assert first.variant == f"reviews.anna_akka.{u.id % 3}"
    picks = [first.variant] + [voice.pick(u, "reviews", n=7).variant for _ in range(5)]
    assert all(a != b for a, b in itertools.pairwise(picks))
    assert len(set(picks)) == 3
    assert ReminderState.objects.get(user=u).last_variants["reviews"] == picks[-1]


@pytest.mark.django_db
@pytest.mark.parametrize(("character", "emoji"), [("kili", "🦜"), ("yaanai", "🐘"), ("mayil", "🦚")])
def test_companion_emoji_and_name(character, emoji):
    u = _user(character=character)
    msgs = [voice.pick(u, "winback_7") for _ in range(2)]
    text = " ".join(m.title + m.body for m in msgs)
    assert emoji in text
    ReminderState.objects.filter(user=u).update(last_variants={"study": "study.anna_akka.1"})
    m = voice.pick(u, "study")  # variant 2 names the companion
    assert m.variant == "study.anna_akka.2" and COMPANIONS[character]["name"] in m.title


@pytest.mark.django_db
def test_personality_and_tamil():
    u = _user(lang="ta", personality="strict_teacher")
    m = voice.pick(u, "streak_risk", n=12)
    assert (
        m.variant.startswith("streak_risk.strict_teacher.")
        and TAMIL.search(m.title)
        and "12" in m.title + m.body
    )
    other = _user("hi@example.com", lang="hi", personality="calm_guru")
    m = voice.pick(other, "missed_day")
    assert m.variant.startswith("missed_day.calm_guru.") and not TAMIL.search(m.title + m.body)
    # An unknown personality falls back to anna_akka.
    p = other.preferences
    p.data = {**p.data, "mentor": {**p.data["mentor"], "personality": "pirate"}}
    p.save()
    assert voice.pick(other, "study").variant.startswith("study.anna_akka.")


@pytest.mark.django_db
def test_pick_never_raises(monkeypatch):
    u = _user()

    def boom(*a, **k):
        raise ValueError("bad prefs")

    monkeypatch.setattr("apps.accounts.preferences.upgrade", boom)
    m = voice.pick(u, "streak_lost_2", n=9, hours=20)
    assert m.variant == "streak_lost_2.anna_akka.0" and "20" in m.title and "9" in m.body
    assert voice.pick(u, "no_such_moment").variant == "study.anna_akka.0"


def test_first_name_moved_from_winback():
    from apps.accounts import winback

    class P:
        display_name = "  Arun Raj "

    class U:
        profile = P()

    assert winback._first_name(U()) == "Arun" and voice.first_name(U(), "") == "Arun"
    U.profile = None
    assert winback._first_name(U()) == "Hi" and voice.first_name(U(), "") == ""
