"""Pure scheduling + knowledge-tracing maths (unit-tested in isolation)."""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

AGAIN, HARD, GOOD = 0, 2, 3
AUTO_GRADED = {
    "quiz",
    "diagram",
    "fill_blank",
    "sequencing",
    "categorization",
    "matching",
    "slides",
    "concept_map",
    "viz",
    "decision_tree",
}


def rating_for(score: float) -> int:
    if score >= 0.999:
        return GOOD
    if score >= 0.7:
        return HARD
    return AGAIN


@dataclass
class CardState:
    stability_days: float = 0.0  # FSRS stability S: days until recall probability falls to 90%
    ease: float = 2.5  # legacy SM-2 field, kept for old rows
    reps: int = 0
    lapses: int = 0
    difficulty: float = 0.0  # FSRS difficulty D in [1, 10]; 0 = not yet initialised
    elapsed_days: float = 0.0  # since the last review (filled by the caller)


# FSRS-5 default parameters (open-spaced-repetition). Ratings: 1 again, 2 hard, 3 good, 4 easy.
W = (
    0.40255,
    1.18385,
    3.173,
    15.69105,
    7.1949,
    0.5345,
    1.4604,
    0.0046,
    1.54575,
    0.1192,
    1.01925,
    1.9395,
    0.11,
    0.29605,
    2.2698,
    0.2315,
    2.9898,
    0.51655,
    0.6621,
)
DECAY, FACTOR = -0.5, 19 / 81
RETENTION = 0.9
MAX_DAYS = 180.0
_FSRS_GRADE = {AGAIN: 1, HARD: 2, GOOD: 3}


def retrievability(elapsed_days: float, stability: float) -> float:
    return (1 + FACTOR * elapsed_days / max(stability, 0.01)) ** DECAY


def _d0(g: int) -> float:
    return min(10.0, max(1.0, W[4] - math.exp(W[5] * (g - 1)) + 1))


def _next_d(d: float, g: int) -> float:
    d2 = d + (-W[6] * (g - 3)) * (10 - d) / 9
    return min(10.0, max(1.0, W[7] * _d0(4) + (1 - W[7]) * d2))


def _interval(stability: float) -> float:
    return stability / FACTOR * (RETENTION ** (1 / DECAY) - 1)


def schedule(state: CardState, rating: int, now: datetime) -> tuple[CardState, datetime]:
    """FSRS-5. A wrong answer comes back in 10 minutes (short-term relearning); otherwise the next review is
    set where predicted recall drops to 90%."""
    s = CardState(**vars(state))
    g = _FSRS_GRADE.get(rating, 3)
    if s.reps == 0 and s.lapses == 0 and s.stability_days <= 0:  # brand-new card
        s.stability_days, s.difficulty = W[g - 1], _d0(g)
    else:
        if s.difficulty <= 0:  # migrated SM-2 card
            s.difficulty, s.stability_days = _d0(3), max(s.stability_days, 0.5)
        r = retrievability(s.elapsed_days, s.stability_days)
        if s.elapsed_days < 1:  # reviewed again the same day
            new_s = s.stability_days * math.exp(W[17] * (g - 3 + W[18]))
        elif g == 1:
            new_s = min(
                s.stability_days,
                W[11]
                * s.difficulty ** -W[12]
                * ((s.stability_days + 1) ** W[13] - 1)
                * math.exp(W[14] * (1 - r)),
            )
        else:
            hard = W[15] if g == 2 else 1.0
            new_s = s.stability_days * (
                math.exp(W[8])
                * (11 - s.difficulty)
                * s.stability_days ** -W[9]
                * (math.exp(W[10] * (1 - r)) - 1)
                * hard
                + 1
            )
        s.difficulty = _next_d(s.difficulty, g)
        s.stability_days = max(0.1, new_s)
    if g == 1:
        s.lapses += 1
        s.reps = 0
        return s, now + timedelta(minutes=10)
    s.reps += 1
    days = min(MAX_DAYS, max(1.0, round(_interval(s.stability_days))))
    return s, now + timedelta(days=days)


# ── Bayesian Knowledge Tracing ────────────────────────────────────────
P_LEARN, P_SLIP = 0.15, 0.1


def guess_for(activity_type: str, options: int = 0) -> float:
    if activity_type in ("quiz", "diagram") and options:
        return min(0.5, 1 / options)
    return 0.05 if activity_type in ("fill_blank", "open_input", "code", "task", "concept_map") else 0.15


def bkt_update(p_known: float, correct: bool, p_guess: float) -> float:
    if correct:
        post = p_known * (1 - P_SLIP) / (p_known * (1 - P_SLIP) + (1 - p_known) * p_guess)
    else:
        post = p_known * P_SLIP / (p_known * P_SLIP + (1 - p_known) * (1 - p_guess))
    return min(0.999, post + (1 - post) * P_LEARN)
