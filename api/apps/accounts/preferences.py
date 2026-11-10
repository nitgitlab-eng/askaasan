"""Schema + defaults for UserPreferences.data. Bump SCHEMA_VERSION and add a
migration step in `upgrade()` whenever the shape changes."""

from copy import deepcopy

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .companions import COMPANIONS, DEFAULT_CHARACTER

SCHEMA_VERSION = 2

MASCOTS = tuple(COMPANIONS)  # from the companion registry (companions.py)
PERSONALITIES = ("anna_akka", "strict_teacher", "funny_buddy", "calm_guru")
# "system" follows the device (prefers-color-scheme); the client resolves it to light or dark.
# "system" follows the device (prefers-color-scheme); the client resolves it to light or dark.
THEMES = ("light", "dark", "kolam", "temple", "ocean", "night_study", "system")
EXAMPLE_STYLES = ("cricket", "cinema", "farming", "coding", "daily_life")
REPLY_LANGUAGES = ("auto", "en", "ta", "tanglish")
# v1 stored an int slider; map it onto v2 reply_language. 0 was the untouched
# default (not a deliberate choice), so it becomes "auto" in the English-first model.
_V1_LANGUAGE_MIX = {0: "auto", 1: "tanglish", 2: "en"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MascotPrefs(_Strict):
    character: str = Field(DEFAULT_CHARACTER, pattern="^(" + "|".join(MASCOTS) + ")$")
    name: str = Field(COMPANIONS[DEFAULT_CHARACTER]["name"], max_length=24)
    color: str = Field("#22c55e", pattern=r"^#[0-9a-fA-F]{6}$")
    outfit: str = "none"
    accessories: list[str] = []
    enabled: bool = True
    position: str = Field("bottom-right", pattern="^(bottom-right|bottom-left|docked)$")
    voice: bool = False
    chattiness: int = Field(2, ge=0, le=3)  # 0 = silent, 3 = very talkative


class MentorPrefs(_Strict):
    personality: str = Field("anna_akka", pattern="^(" + "|".join(PERSONALITIES) + ")$")
    depth: str = Field("simple", pattern="^(simple|detailed)$")
    # "auto" mirrors whatever language the learner writes in each message.
    reply_language: str = Field("auto", pattern="^(" + "|".join(REPLY_LANGUAGES) + ")$")
    example_style: str = Field("daily_life", pattern="^(" + "|".join(EXAMPLE_STYLES) + ")$")


class AppearancePrefs(_Strict):
    theme: str = Field("light", pattern="^(" + "|".join(THEMES) + ")$")
    accent: str = Field("#f97316", pattern=r"^#[0-9a-fA-F]{6}$")
    font: str = Field("mukta", pattern="^(mukta|noto|catamaran|dyslexic)$")
    font_scale: float = Field(1.0, ge=0.8, le=1.6)
    reduced_motion: bool = False
    sound_effects: bool = True
    study_music: bool = False


class LearningPrefs(_Strict):
    daily_goal_minutes: int = Field(15, ge=5, le=240)
    pace: str = Field("steady", pattern="^(relaxed|steady|intense)$")
    difficulty: str = Field("auto", pattern="^(auto|easy|medium|hard)$")
    reminder_times: list[str] = ["19:00"]
    study_days: list[int] = [0, 1, 2, 3, 4, 5, 6]
    dashboard_widgets: list[str] = ["streak", "continue", "daily_goal", "review", "quest_map"]
    adaptive: bool = True  # "For you" recommendations adapt to mastery, followed skills and feedback
    lesson_language: str = Field(
        "", pattern="^(|en|ta|hi|te|kn|ml|bn|mr|gu)$"
    )  # "" = the course's own language
    progress_pins: list[str] = Field([], max_length=4)  # charts pinned to Home
    tours_done: list[str] = Field([], max_length=20)  # guided tours finished or skipped
    # Course page layout: the dashboard map or the classic quest path.
    course_view: str = Field("map", pattern="^(map|path)$")

    @field_validator("progress_pins")
    @classmethod
    def _pins(cls, v):
        allowed = {"minutes", "xp", "accuracy", "skills", "weekday"}
        if not set(v) <= allowed:
            raise ValueError("unknown chart")
        return list(dict.fromkeys(v))


class NotificationPrefs(_Strict):
    email_study: bool = True  # daily study reminder emails (at learning.reminder_times on study_days)
    email_plan: bool = True  # "your plan ends soon / has ended"
    email_workshops: bool = True  # public workshop announcements, reminders and changes
    kili_nudges: bool = True  # Kili's in-app tips (reviews due, streak at risk…)
    email_winback: bool = (
        True  # "we miss you" emails after a few days away, and a comeback offer after a plan ends
    )
    # Web push, per kind (only sent to devices where the learner turned push on).
    push_study: bool = True  # the daily study reminder and "we miss you"
    push_streak: bool = True  # streak at risk (evening)
    push_reviews: bool = True  # review cards piling up (evening)
    push_workshops: bool = True  # workshop reminders and changes
    push_teacher: bool = True  # nudges from a teacher
    push_plan: bool = True  # plan ending / ended


class VoicePrefs(_Strict):
    # Live AI workshop voice: "tap" = tap to talk, one turn per tap (default); "handsfree" = mic stays open between
    # turns (headphones advised; recognition pauses while the host speaks).
    workshop_mode: str = Field("tap", pattern="^(tap|handsfree)$")
    # Ask Aasan voice, same two modes (tap to talk by default).
    mentor_mode: str = Field("tap", pattern="^(tap|handsfree)$")
    # Ask Aasan: speak the replies once the learner has used voice (remembered when they switch it off).
    mentor_read_aloud: bool = True
    # The language the learner speaks to Ask Aasan (browser listens in it): "" = not chosen yet, so ask on first use.
    mentor_lang: str = Field("", pattern="^(|en|ta)$")


class Preferences(_Strict):
    version: int = SCHEMA_VERSION
    mascot: MascotPrefs = MascotPrefs()
    mentor: MentorPrefs = MentorPrefs()
    appearance: AppearancePrefs = AppearancePrefs()
    learning: LearningPrefs = LearningPrefs()
    notifications: NotificationPrefs = NotificationPrefs()
    voice: VoicePrefs = VoicePrefs()


_DEFAULT = Preferences().model_dump()


def default_preferences() -> dict:
    return deepcopy(_DEFAULT)


def deep_merge(base: dict, patch: dict) -> dict:
    out = deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def upgrade(data: dict) -> dict:
    """Bring stored prefs up to SCHEMA_VERSION, filling new defaults."""
    data = deepcopy(data)
    if data.get("version", 1) < 2:
        mentor = data.get("mentor", {})
        if "language_mix" in mentor:
            mentor["reply_language"] = _V1_LANGUAGE_MIX.get(mentor.pop("language_mix"), "auto")
    return deep_merge(default_preferences(), {**data, "version": SCHEMA_VERSION})
