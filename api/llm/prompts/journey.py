"""Milestone 9 learner prompts: two-host lesson podcasts, fast-track checks, and journey-order suggestions."""

from typing import Literal

from pydantic import BaseModel, Field

PODCAST_SYSTEM = """[[TASK:podcast_episode]]
You write short educational podcast episodes for Indian learners. Turn the lesson into a natural two-host conversation
that takes 3–6 minutes to listen to (about 450–900 spoken words, 14–40 turns).
- Host A is a curious learner: asks the questions a beginner would ask, sometimes guesses wrong, reacts honestly.
- Host B is a friendly expert: explains simply, with everyday Indian examples (chai stalls, cricket, UPI, trains, festivals).
- Give each host a short, common Indian first name (host_a, host_b).
- Every turn: speaker "A" or "B" and text = what they say (1–4 natural spoken sentences; no Markdown, no code blocks,
  no URLs, no stage directions, no sound effects).
- Open with a warm hook, build the idea step by step, end with B's two-line recap and A saying what they'll try next.
Stay strictly within the lesson's facts. {lang_rule}
"""


class PodcastTurn(BaseModel):
    speaker: Literal["A", "B"]
    text: str = Field(
        max_length=4000
    )  # generous: build_podcast splits turns over 700 characters at sentence ends


class PodcastScript(BaseModel):
    title: str = Field(max_length=200)
    host_a: str = Field(default="Meera", max_length=40)
    host_b: str = Field(default="Arjun", max_length=40)
    turns: list[PodcastTurn] = Field(min_length=4, max_length=60)


FAST_TRACK_SYSTEM = """[[TASK:fast_track_check]]
A learner says they already know this lesson and want to skip it. Write {n} HARDER multiple-choice questions that
only someone who truly meets the lesson objective can answer: application, tricky cases and "why" questions —
never recall of wording. Each question:
- prompt: a clear question (max 300 characters)
- options: 4 plausible options; exactly one correct
- correct: the 0-based index of the correct option
- explanation: one sentence on why it is right
{lang_rule}
"""


class FastTrackQ(BaseModel):
    prompt: str = Field(max_length=400)
    options: list[str] = Field(min_length=3, max_length=5)
    correct: int = Field(ge=0, le=4)
    explanation: str = Field(default="", max_length=400)


class FastTrackSet(BaseModel):
    questions: list[FastTrackQ] = Field(min_length=2, max_length=4)


ORDER_SYSTEM = """[[TASK:course_order_suggest]]
You are Aasan's study planner. The learner has several active courses. Propose the best order to take them in,
considering their goals, the skills they follow, prerequisites between topics, and how far along each course is
(finishing something nearly done is often wise). Return:
- order: every course id exactly once, first = do next
- reasons: for each course id, one short sentence (max 20 words) on why it sits there
- note: one friendly sentence summarising the plan
{lang_rule}
"""


class OrderReason(BaseModel):
    id: int
    reason: str = Field(default="", max_length=240)


class OrderSuggestion(BaseModel):
    order: list[int] = Field(max_length=60)
    reasons: list[OrderReason] = Field(default_factory=list, max_length=60)
    note: str = Field(default="", max_length=400)
