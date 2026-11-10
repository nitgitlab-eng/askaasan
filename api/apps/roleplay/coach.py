"""Live coach for role-play (M10 rpx): a per-turn competence tracker, Kili's private hint tutor and a gentle
fact check against the scenario's hard facts. Every AI call is charged against a per-user daily allowance."""

import logging
import re

from django.conf import settings
from django.db import transaction

from llm.prompts.curriculum import LANG_RULE
from llm.prompts.roleplay import (
    FACTS_SYSTEM,
    HINT_SYSTEM,
    TRACK_SYSTEM,
    Hint,
    ScenarioFacts,
    TurnTrack,
    transcript_text,
)
from llm.structured import complete_json_sync

from .models import RolePlaySession, RolePlayTurn, Scenario
from .services import _norm

log = logging.getLogger(__name__)

METRIC = "roleplay_coach"
HINTS_PER_SESSION = 3
MIN_CONFIDENCE = 0.85  # only clear mismatches are flagged
MAX_FACTS = 8
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


class HintLimit(Exception):
    pass


def daily_limit() -> int:
    return int(getattr(settings, "ROLEPLAY_COACH_DAILY", 200))


def _charge(user):
    """Raises apps.providers.services.BudgetExceeded once the learner's daily coach allowance is used up."""
    from apps.providers.services import charge

    charge(user, METRIC, 1, daily_limit())


def _lang(session) -> str:
    return LANG_RULE.get(session.language, LANG_RULE["en"])


def _context(sc: Scenario) -> str:
    objectives = "\n".join(f"{i + 1}. {o}" for i, o in enumerate(sc.objectives))
    rubric = "\n".join(f"{i + 1}. {c['name']}: {c['description']}" for i, c in enumerate(sc.competencies))
    return (
        f"Scenario: {sc.title}\nSetting: {sc.setting}\nLearner's role: {sc.learner_role}\n"
        f"Character: {sc.character['name']} ({sc.character['persona']})\nObjectives:\n{objectives}\nCompetencies:\n{rubric}"
    )


# ── Scenario facts (extracted once, cached on the scenario) ─────────


def scenario_facts(user, sc: Scenario) -> list[str]:
    if sc.facts is not None:
        return list(sc.facts)
    _charge(user)
    # The character's private goal is left out on purpose: corrections must never reveal it.
    source = (
        f"Title: {sc.title}\nSummary: {sc.summary}\nSetting: {sc.setting}\nLearner's role: {sc.learner_role}\n"
        f"Character: {sc.character['name']}, {sc.character['persona']}\nOpening line: {sc.opening_line}"
    )
    out = complete_json_sync("suggest", FACTS_SYSTEM, source, ScenarioFacts, max_tokens=800)
    facts = [f.text.strip()[:200] for f in out.facts if f.text.strip()][:MAX_FACTS]
    Scenario.objects.filter(pk=sc.pk, facts__isnull=True).update(facts=facts)
    sc.facts = facts
    return facts


def _numbers(s: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in _NUM.findall(s)}


def verified_checks(raw, facts: list[str], line: str) -> list[dict]:
    """Keep only high-confidence mismatches whose quote really is in the learner's line and whose numbers really
    differ from the fact's — the model may not invent or misread a contradiction."""
    nline = _norm(line)
    out, seen = [], set()
    for c in raw:
        if c.confidence < MIN_CONFIDENCE or not 0 <= c.fact_index < len(facts) or c.fact_index in seen:
            continue
        quote = c.learner_quote.strip()
        nq = _norm(quote)
        if len(nq) < 2 or nq not in nline:
            continue
        fact_nums, quote_nums = _numbers(facts[c.fact_index]), _numbers(quote)
        if fact_nums and (not quote_nums or quote_nums <= fact_nums):
            continue  # a number fact needs a different number to be a contradiction
        if not fact_nums and c.confidence < 0.9:
            continue
        seen.add(c.fact_index)
        out.append({"fact": facts[c.fact_index], "said": quote[:120], "note": c.correction.strip()[:200]})
    return out[:2]


# ── Per-turn tracker ────────────────────────────────────────────────


def _clamp(n) -> int:
    try:
        return max(0, min(3, int(n)))
    except (TypeError, ValueError):
        return 0


def _scores(items, n: int) -> list[dict]:
    return [
        {"score": _clamp(items[i].score), "reason": items[i].reason.strip()[:160]}
        if i < len(items)
        else {"score": 0, "reason": ""}
        for i in range(n)
    ]


def track_latest(session: RolePlaySession) -> RolePlayTurn | None:
    """Score the latest learner turn (idempotent: a turn is scored once). Returns the scored turn, or None if the
    learner hasn't spoken yet."""
    turns = list(session.turns.all())
    learner = [t for t in turns if t.role == RolePlayTurn.Role.LEARNER]
    if not learner:
        return None
    latest = learner[-1]
    if latest.coach is not None:
        return latest
    sc = session.scenario
    facts = scenario_facts(session.user, sc)
    _charge(session.user)
    prev = next((t.coach for t in reversed(learner[:-1]) if t.coach), None)
    fact_block = "\n".join(f"[{i}] {f}" for i, f in enumerate(facts)) or "(none)"
    upto = [t for t in turns if t.id <= latest.id]
    user = (
        f"{_context(sc)}\nFACTS:\n{fact_block}\n\nTranscript so far:\n{transcript_text(upto)}\n\n"
        f"LEARNER'S LATEST LINE:\n{latest.text}"
    )
    out = complete_json_sync(
        "suggest", TRACK_SYSTEM.format(lang_rule=_lang(session)), user, TurnTrack, max_tokens=1200
    )
    objectives = _scores(out.objectives, len(sc.objectives))
    if prev:  # an objective, once achieved, stays achieved
        for i, o in enumerate(objectives):
            if i < len(prev.get("objectives", [])) and prev["objectives"][i]["score"] > o["score"]:
                objectives[i] = prev["objectives"][i]
    coach = {
        "objectives": objectives,
        "competencies": _scores(out.competencies, len(sc.competencies)),
        "checks": verified_checks(out.contradictions, facts, latest.text) if facts else [],
    }
    RolePlayTurn.objects.filter(pk=latest.pk, coach__isnull=True).update(coach=coach)
    latest.refresh_from_db(fields=["coach"])
    return latest


# ── Kili's hint tutor ───────────────────────────────────────────────


def give_hint(session: RolePlaySession) -> dict:
    if len(session.hints) >= HINTS_PER_SESSION:
        raise HintLimit()
    _charge(session.user)
    sc = session.scenario
    turns = list(session.turns.all())
    latest = next((t.coach for t in reversed(turns) if t.coach), None)
    progress = ""
    if latest:
        progress = "\nProgress so far (0-3):\n" + "\n".join(
            f"- {o}: {latest['objectives'][i]['score']}"
            for i, o in enumerate(sc.objectives)
            if i < len(latest["objectives"])
        )
    user = f"{_context(sc)}{progress}\n\nTranscript so far:\n{transcript_text(turns)}"
    from apps.accounts.companion import as_companion

    system = as_companion(HINT_SYSTEM.format(lang_rule=_lang(session)), session.user)
    text = complete_json_sync("suggest", system, user, Hint, max_tokens=400).hint.strip()[:400]
    with transaction.atomic():
        s = RolePlaySession.objects.select_for_update().get(pk=session.pk)
        if len(s.hints) >= HINTS_PER_SESSION:  # a parallel request took the last one
            raise HintLimit()
        hint = {"text": text, "after_turn": sum(1 for t in turns if t.role == RolePlayTurn.Role.LEARNER)}
        s.hints = [*s.hints, hint]
        s.save(update_fields=["hints"])
    session.hints = s.hints
    return hint


# ── State for the player / final report ─────────────────────────────


def state(session: RolePlaySession) -> dict:
    sc = session.scenario
    scored = [t for t in session.turns.all() if t.role == RolePlayTurn.Role.LEARNER and t.coach]
    latest = scored[-1].coach if scored else None

    def items(names, key):
        return [
            {"text": n, **(latest[key][i] if latest and i < len(latest[key]) else {"score": 0, "reason": ""})}
            for i, n in enumerate(names)
        ]

    return {
        "objectives": items(sc.objectives, "objectives"),
        "competencies": items([c["name"] for c in sc.competencies], "competencies"),
        "checks": [{**c, "turn_id": t.id} for t in scored for c in t.coach.get("checks", [])],
        "progression": [
            {
                "turn_id": t.id,
                "objectives": [o["score"] for o in t.coach["objectives"]],
                "competencies": [c["score"] for c in t.coach["competencies"]],
            }
            for t in scored
        ],
        "hints": session.hints,
        "hints_used": len(session.hints),
        "hints_left": max(0, HINTS_PER_SESSION - len(session.hints)),
    }


def summary(session: RolePlaySession) -> dict:
    """What the final report shows about the live coach: progression per turn, fact checks and hints used."""
    st = state(session)
    return {"progression": st["progression"], "checks": st["checks"], "hints_used": st["hints_used"]}
