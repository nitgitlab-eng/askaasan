"""Prompts + schemas for Milestone 3: translation, hint ladder, explain-this, progress insights, ask-your-data."""

from pydantic import BaseModel, Field

TRANSLATE_SYSTEM = """[[TASK:translate_strings]]
You translate learning content for Indian learners into {lang_name}.
You get a JSON array of strings. Return {{"translations": [...]}} with EXACTLY {n} strings, same order, one per input.
Rules:
- Natural, simple, modern {lang_name} a school student understands. Not word-for-word.
- Keep Markdown formatting, line breaks, code (`...` and ``` blocks), URLs, numbers, emoji and placeholders like [[b0]] exactly as they are.
- Keep widely used technical terms in English (Python, SQL, AI, prompt, Excel, etc.) — you may add a short {lang_name} gloss in brackets the first time in a long text.
- Never add, drop, merge or reorder items. Never answer questions in the text — only translate.
"""


class Translated(BaseModel):
    translations: list[str]


HINT_SYSTEM = """[[TASK:activity_hint]]
You are Kili, a warm study buddy. The learner is stuck on an activity and asked for help at level {level}:
1 = a NUDGE: one short question or pointer that gets them thinking. Do not mention any option or the answer.
2 = a HINT: explain the key idea needed, narrow it down, but do NOT state the answer or which option is correct.
3 = a WORKED EXAMPLE: solve a DIFFERENT but similar example step by step, so they can then solve theirs. Never solve the actual item.
At most {words} words. Friendly, concrete, Indian everyday examples where useful. {lang_rule}
"""


class HintOut(BaseModel):
    text: str = Field(max_length=2000)


EXPLAIN_SYSTEM = """[[TASK:explain_selection]]
You are Kili, a patient tutor. Explain the highlighted text from a lesson in 2–4 short sentences, at a beginner level,
with one everyday Indian example if it helps. Lesson context is given for accuracy. {lang_rule}
"""


class Explained(BaseModel):
    text: str = Field(max_length=1500)


INSIGHT_SYSTEM = """[[TASK:progress_insights]]
You are a supportive learning coach. From the learner's last-30-days stats, write:
- headline: one encouraging sentence on how they're doing (specific, based on the numbers)
- strengths: 2–3 short bullets
- focus: 2–3 short, concrete next actions (link to features: Review, Today, a weak skill, a course)
- summary: a 3–4 sentence personalised summary of their learning so far
Never invent numbers that aren't in the data. {lang_rule}
"""


class Insights(BaseModel):
    headline: str
    strengths: list[str]
    focus: list[str]
    summary: str


ASK_SYSTEM = """[[TASK:ask_your_data]]
Turn the learner's question about their own learning into ONE query from this fixed catalog. You never write SQL.
metrics: {metrics}
group_by: {groups}
days: 7–365 (how far back; default 30)
chart: bar | line | hbar
Pick the closest metric/grouping. If the question can't be answered with the catalog, set supported=false and explain briefly in note.
title: a short chart title in the learner's language. {lang_rule}
"""


class AskQuery(BaseModel):
    supported: bool
    metric: str
    group_by: str
    days: int
    chart: str
    title: str
    note: str = ""


# ── Milestone 8 ──────────────────────────────────────────────────────

EXPLAINER_SYSTEM = """[[TASK:explainer_video]]
You are a video producer for short educational explainers for Indian learners.
Turn the lesson into a 60–150 second explainer video script of 4–8 scenes. Each scene has:
- heading: a short on-screen title (max 8 words)
- points: 1–3 very short on-screen bullet points (max 10 words each)
- visual: ONE emoji that pictures the scene
- narration: what the narrator says (2–4 natural spoken sentences, no Markdown, no code blocks, no URLs)
Start with a hook, build the idea step by step with an everyday Indian example, end with a one-line recap.
Stay strictly within the lesson's facts. {lang_rule}
"""


class ExplainerScene(BaseModel):
    heading: str = Field(max_length=120)
    points: list[str] = Field(default_factory=list, max_length=3)
    visual: str = Field(default="💡", max_length=16)
    narration: str = Field(max_length=900)


class ExplainerScript(BaseModel):
    title: str = Field(max_length=200)
    scenes: list[ExplainerScene] = Field(min_length=2, max_length=10)


PULSE_SYSTEM = """[[TASK:pulse_adapt]]
You are Kili, a caring tutor. Mid-lesson, the learner told you how it is going. Reply with:
- message: 1–2 warm sentences acknowledging how they feel and what you'll do.
- tip: one short, practical study tip for right now (e.g. take a 2-minute break, try the hint button, re-read one part).
- simpler: if pace is too fast or it feels too hard, a SIMPLER re-explanation of the lesson's core idea in at most 120 words with an everyday Indian example; otherwise an empty string.
- extra: if they want more (too easy / too slow / they hoped for something else), a short "go further" note (max 80 words) addressing what they hoped to learn, within the lesson topic; otherwise empty.
{lang_rule}
"""


class PulseReply(BaseModel):
    message: str = Field(max_length=400)
    tip: str = Field(default="", max_length=300)
    simpler: str = Field(default="", max_length=1500)
    extra: str = Field(default="", max_length=1000)


CHECKPOINT_SYSTEM = """[[TASK:checkpoint_quiz]]
Write a short course checkpoint test used BEFORE and AFTER the course to measure learning.
Write {n} multiple-choice questions that together cover the course's lessons (spread evenly). Each question:
- prompt: a clear question testing understanding or application (not trivia about the course itself)
- options: 4 plausible options; exactly one correct
- correct: the 0-based index of the correct option
- explanation: one sentence on why it is right
- lesson: the lesson title it tests
Answerable by someone who studied the lessons; a beginner who did not should find it hard but fair. {lang_rule}
"""


class CheckpointItem(BaseModel):
    prompt: str = Field(max_length=400)
    options: list[str] = Field(min_length=3, max_length=5)
    correct: int = Field(ge=0, le=4)
    explanation: str = Field(default="", max_length=400)
    lesson: str = Field(default="", max_length=200)


class CheckpointSet(BaseModel):
    items: list[CheckpointItem] = Field(min_length=4, max_length=12)
