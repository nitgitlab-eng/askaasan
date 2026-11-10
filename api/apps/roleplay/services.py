import re
import unicodedata

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.learning.services import content_language
from llm.prompts.curriculum import LANG_RULE
from llm.prompts.roleplay import EVAL_SYSTEM, SCENARIO_SYSTEM, Evaluation, ScenarioDraft, transcript_text
from llm.structured import complete_json_sync

from .models import RolePlaySession, RolePlayTurn, Scenario

MIN_TURNS_FOR_EVAL = 2
REWARD_MIN_SCORE = 50  # a role-play only pays XP/coins when the evaluator scores it at least this
AI_METRIC = "roleplay_ai"  # character replies, end-of-session evaluations and scenario generation share one daily budget


def rewards_per_day() -> int:
    return int(getattr(settings, "ROLEPLAY_REWARDS_PER_DAY", 5))


def ai_daily_limit() -> int:
    return int(getattr(settings, "ROLEPLAY_AI_DAILY", 150))


def charge_ai(user):
    """Raises apps.providers.services.BudgetExceeded once the learner's daily role-play AI allowance is used up."""
    from apps.providers.services import charge

    charge(user, AI_METRIC, 1, ai_daily_limit())


class NotAllowed(Exception):
    pass


def generate_scenario(user, goal: str, difficulty: str) -> Scenario:
    lang = content_language(user)
    draft = complete_json_sync(
        "author",
        SCENARIO_SYSTEM.format(lang_rule=LANG_RULE[lang]),
        f"Learner's goal: {goal}\nDifficulty: {difficulty}",
        ScenarioDraft,
        max_tokens=3000,
        effort="medium",
    )
    if not draft.allowed or len(draft.competencies) < 2 or not draft.opening_line.strip():
        raise NotAllowed()
    return Scenario.objects.create(
        source=Scenario.Source.CUSTOM,
        owner=user,
        emoji=(draft.emoji or "🎭")[:8],
        title=draft.title[:160],
        summary=draft.summary[:400],
        learner_role=draft.learner_role[:300],
        character=draft.character.model_dump(),
        setting=draft.setting[:400],
        objectives=draft.objectives[:3],
        competencies=[c.model_dump() for c in draft.competencies[:4]],
        opening_line=draft.opening_line[:600],
        difficulty=difficulty,
    )


def scenario_from_brief(user, brief: dict) -> Scenario:
    """A lesson's role-play activity already carries a validated brief: no extra AI call needed."""
    objectives = [o[:200] for o in brief["objectives"][:3]]
    competencies = [{"name": " ".join(o.split()[:4])[:40], "description": o} for o in objectives]
    if len(competencies) < 2:
        competencies.append(
            {"name": "Clear communication", "description": "Speaks clearly and politely, and stays on goal."}
        )
    return Scenario.objects.create(
        source=Scenario.Source.CUSTOM,
        owner=user,
        emoji="🎭",
        title=brief["title"][:160],
        summary=brief["goal"][:400],
        learner_role=brief["learner_role"][:300],
        setting=brief["setting"][:400],
        objectives=objectives,
        competencies=competencies,
        character={
            "name": brief["character_name"][:60],
            "persona": brief["character_persona"][:300],
            "goal": brief["goal"][:300],
            "style": "natural, everyday Indian conversation",
        },
        opening_line=brief["opening_line"][:600],
        difficulty="easy",
        max_turns=6,
    )


def start_session(user, scenario: Scenario, activity=None, assignment=None) -> RolePlaySession:
    s = RolePlaySession.objects.create(
        user=user,
        scenario=scenario,
        language=content_language(user),
        activity=activity,
        assignment=assignment,
    )
    RolePlayTurn.objects.create(session=s, role=RolePlayTurn.Role.CHARACTER, text=scenario.opening_line)
    return s


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).casefold()
    return re.sub(r"[\s\"'“”‘’.,!?…]+", " ", s).strip()


def verify_quotes(evaluation: dict, learner_lines: list[str]) -> dict:
    """Keep only evidence that really appears in what the learner said — the
    model may not invent or paraphrase quotes."""
    corpus = [_norm(x) for x in learner_lines]

    def real(q):
        nq = _norm(q)
        return len(nq) >= 3 and any(nq in line for line in corpus)

    for comp in evaluation["competencies"]:
        comp["evidence"] = [q for q in comp["evidence"] if real(q)][:2]
    evaluation["better_phrasing"] = [b for b in evaluation["better_phrasing"] if real(b["learner_said"])][:3]
    return evaluation


def evaluate(session: RolePlaySession) -> dict:
    sc = session.scenario
    turns = list(session.turns.all())
    learner_lines = [t.text for t in turns if t.role == RolePlayTurn.Role.LEARNER]
    rubric = "\n".join(f"- {c['name']}: {c['description']}" for c in sc.competencies)
    objectives = "\n".join(f"- {o}" for o in sc.objectives)
    user = (
        f"Scenario: {sc.title}\nLearner's role: {sc.learner_role}\nCharacter: {sc.character['name']} ({sc.character['persona']})\n"
        f"Competencies:\n{rubric}\nObjectives:\n{objectives}\n\nTranscript:\n{transcript_text(turns)}"
    )
    ev = complete_json_sync(
        "author",
        EVAL_SYSTEM.format(lang_rule=LANG_RULE.get(session.language, LANG_RULE["en"])),
        user,
        Evaluation,
        max_tokens=4000,
        effort="medium",
    ).model_dump()
    # Normalise to the scenario's rubric no matter what the model returned.
    by_name = {c["name"].casefold(): c for c in ev["competencies"]}
    ev["competencies"] = [
        {
            **(by_name.get(c["name"].casefold()) or {"evidence": [], "comment": ""}),
            "name": c["name"],
            "score": max(1, min(5, int((by_name.get(c["name"].casefold()) or {}).get("score", 1)))),
        }
        for c in sc.competencies
    ]
    ev["objectives"] = [
        {"text": o, "met": bool(ev["objectives_met"][i]) if i < len(ev["objectives_met"]) else False}
        for i, o in enumerate(sc.objectives)
    ]
    del ev["objectives_met"]
    ev["overall"] = max(0, min(100, int(ev["overall"])))
    ev = verify_quotes(ev, learner_lines)
    return ev


def finish(session: RolePlaySession) -> tuple[dict, dict]:
    from apps.game.services import grant_badge

    from .coach import summary

    result = evaluate(session)
    result["coach"] = summary(session)  # live tracker progression, fact checks and hints used
    session.result = result
    session.status = RolePlaySession.Status.COMPLETED
    session.ended_at = timezone.now()
    session.save()
    from apps.integrations.hooks import on_roleplay_done

    on_roleplay_done(session.id)  # assigned practice: training record + webhook
    reward = _reward(session, result["overall"])
    if result["overall"] >= 80 and grant_badge(session.user, "roleplay_star"):
        reward.setdefault("badges", []).append("roleplay_star")
    return result, reward


def _reward(session: RolePlaySession, overall: int) -> dict:
    """XP/coins only for a passing score, and only for the first few role-plays a day (sessions are unlimited)."""
    from apps.game.models import PlayerStats, XPEvent
    from apps.game.services import award, stats_for

    with transaction.atomic():
        PlayerStats.objects.select_for_update().filter(
            pk=stats_for(session.user).pk
        ).first()  # serialise the cap check
        paid_today = XPEvent.objects.filter(
            user=session.user, kind="roleplay_complete", day=timezone.localdate(), xp__gt=0
        ).count()
        earns = overall >= REWARD_MIN_SCORE and paid_today < rewards_per_day()
        return award(
            session.user,
            "roleplay_complete",
            ref=f"roleplay:{session.id}",
            xp=40 + overall // 4 if earns else 0,
            coins=15 if earns else 0,
        )
