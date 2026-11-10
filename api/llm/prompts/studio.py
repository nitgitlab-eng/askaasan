"""Prompts + schemas for Milestone 4: Kili authoring chat, lecture segmentation, quarterly review."""

from typing import Literal

from pydantic import BaseModel

OPS = (
    "edit_course",
    "add_section",
    "rename_section",
    "delete_section",
    "add_lesson",
    "edit_lesson",
    "write_lesson",
    "generate_lesson",
    "add_activity",
    "delete_lesson",
)

CHAT_SYSTEM = """[[TASK:authoring_chat]]
You are Kili, co-authoring a course with a teacher in the Creator Lab. Talk briefly and warmly, then PROPOSE concrete
changes the teacher can accept or reject one by one. Never claim a change is done — it is only proposed.
Operations (use the ids from the outline below; never invent ids):
- edit_course(title, text=description) — rename the course and/or change its description
- add_section(title, text=summary)
- rename_section(section_id, title, text=summary)
- delete_section(section_id)
- add_lesson(section_id OR ref=index of an add_section op in THIS list, title, text=objective)
- edit_lesson(lesson_id, title, text=objective)
- write_lesson(lesson_id, text=lesson explanation in Markdown, key_points)
- generate_lesson(lesson_id) — let the AI write the whole lesson with activities
- add_activity(lesson_id, activity_type, instructions) — activity_type one of: {types}
- delete_lesson(lesson_id)
Leave unused fields empty ("" / [] / 0 / -1). Propose at most 12 changes per reply; zero changes is fine for questions.
Course language for learner-facing text: {lang_rule}
"""


class Change(BaseModel):
    op: Literal[OPS]  # type: ignore[valid-type]
    section_id: int = 0
    lesson_id: int = 0
    ref: int = -1
    title: str = ""
    text: str = ""
    key_points: list[str] = []
    activity_type: str = ""
    instructions: str = ""
    why: str = ""


class ChatOut(BaseModel):
    reply: str
    changes: list[Change]


SEGMENT_SYSTEM = """[[TASK:lecture_segments]]
Split a recorded lecture into 2–8 self-contained segments for an online lesson. Use the transcript timestamps
(seconds). Each segment: start, end (seconds, within 0..{duration}), a short title, a one-line summary, and 1–2
multiple-choice checkpoint questions asked at the END of the segment (at = end - 2), answerable from that segment only.
{lang_rule}
"""


class SegCheckpoint(BaseModel):
    at: int
    question: str
    options: list[str]
    correct: list[int]


class Segment(BaseModel):
    start: int
    end: int
    title: str
    summary: str
    checkpoints: list[SegCheckpoint]


class SegmentPlan(BaseModel):
    segments: list[Segment]


REVIEW_SYSTEM = """[[TASK:quarterly_review]]
Write a learner's quarterly learning review from their stats. Sections:
- title: e.g. "Your July–September learning review"
- overview: 3–4 sentences, warm and specific
- covered: courses/topics covered (bullets)
- mastered: what they now know well (bullets, only if mastery data supports it)
- growth: 2–3 areas to strengthen
- next_quarter: 3 concrete goals for the next 3 months
Never invent numbers or courses that aren't in the data. {lang_rule}
"""


class Review(BaseModel):
    title: str
    overview: str
    covered: list[str]
    mastered: list[str]
    growth: list[str]
    next_quarter: list[str]


PRESET_RULE = "Author's house style: tone={tone}. {instructions}{types}"
