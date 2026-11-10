from pydantic import BaseModel, Field

from llm.base import LLMError
from llm.prompts.curriculum import LANG_RULE
from llm.prompts.live import SUMMARY_SYSTEM
from llm.structured import complete_json_sync

from .models import LiveSession


class LiveSummary(BaseModel):
    title: str = Field(max_length=120)
    covered: list[str] = Field(max_length=5)
    mistakes: list[str] = Field(max_length=3)
    next_steps: list[str] = Field(max_length=3)


def summarise(session: LiveSession) -> dict:
    """Recap from the transcript (never images). Too-short classes get no summary."""
    if session.summary:
        return session.summary
    turns = list(session.turns.all())
    if sum(1 for t in turns if t.role == "user") < 2:
        return {}
    from apps.learning.services import content_language
    from llm.usage import current_user_id

    current_user_id.set(session.user_id)  # attribute the recap's AI usage to the learner

    from apps.accounts.companion import as_companion, companion

    name = companion(session.user)["name"]
    transcript = "\n".join(f"{'Learner' if t.role == 'user' else name}: {t.text}" for t in turns[-60:])
    try:
        out = complete_json_sync(
            "suggest",
            as_companion(
                SUMMARY_SYSTEM.format(lang_rule=LANG_RULE[content_language(session.user)]), session.user
            ),
            f"Topic: {session.topic or 'not set'}\n\n{transcript}",
            LiveSummary,
            max_tokens=1200,
        )
    except LLMError:
        return {}
    session.summary = out.model_dump()
    session.save(update_fields=["summary"])
    return session.summary
