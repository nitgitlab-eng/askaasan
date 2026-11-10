"""Match a spoken answer to one of several choices (decision-tree voice mode).

Fast path is deterministic and free (ordinals in English/Tamil, letters, word overlap); the AI is only asked
when the speech is genuinely ambiguous."""

import re
import unicodedata

from pydantic import BaseModel

# Ordinal words win over everything ("the second one" must not match "one").
ORDINALS = {
    0: ["first", "1st", "முதல்", "முதலாவது", "முதலாவதாக", "pehla", "pehle"],
    1: ["second", "2nd", "இரண்டாவது", "ரெண்டாவது", "doosra", "dusra"],
    2: ["third", "3rd", "மூன்றாவது", "மூணாவது", "teesra"],
    3: ["fourth", "4th", "நான்காவது", "நாலாவது", "chautha"],
}
# Bare numbers/letters count only alone or after "option"/"number" ("option B", "number 2", "two").
CARDINALS = {
    0: ["one", "1", "a", "ஒன்று", "ஒண்ணு", "ek"],
    1: ["two", "2", "b", "இரண்டு", "ரெண்டு", "do"],
    2: ["three", "3", "c", "மூன்று", "மூணு", "teen"],
    3: ["four", "4", "d", "நான்கு", "நாலு", "char"],
}
FILLER = {
    "the",
    "one",
    "option",
    "i",
    "choose",
    "pick",
    "will",
    "go",
    "with",
    "want",
    "answer",
    "is",
    "it",
    "a",
    "an",
    "to",
    "my",
    "please",
    "number",
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).casefold()
    return re.sub(r"[^\w\s\u0B80-\u0BFF]+", " ", s).strip()


def _words(s: str) -> set[str]:
    return {w for w in _norm(s).split() if w not in FILLER and len(w) > 1}


def local_match(spoken: str, options: list[str]) -> int | None:
    said = _norm(spoken)
    if not said:
        return None
    tokens = said.split()
    for idx, words in ORDINALS.items():
        if idx < len(options) and any(w in tokens for w in words):
            return idx
    for idx, words in CARDINALS.items():
        if idx >= len(options):
            continue
        for w in words:
            if (
                said == w
                or said in (f"option {w}", f"number {w}")
                or f"option {w}" in said
                or f"number {w}" in said
            ):
                return idx
    # Word overlap with each option's text
    sw = _words(spoken)
    if not sw:
        return None
    scores = [len(sw & _words(o)) / max(1, len(_words(o))) for o in options]
    best = max(range(len(options)), key=lambda i: scores[i])
    ranked = sorted(scores, reverse=True)
    if ranked[0] >= 0.5 and (len(ranked) == 1 or ranked[0] - ranked[1] >= 0.25):
        return best
    return None


class Pick(BaseModel):
    index: int  # -1 if none fits
    confident: bool


MATCH_SYSTEM = """[[TASK:match_spoken_choice]]
A learner answered a multiple-choice story by voice. Decide which option they meant.
The speech may be English, Tamil or Tanglish and may be imperfectly transcribed.
Return the zero-based index, or -1 if it matches none. confident=false if you are guessing."""


def ai_match(spoken: str, options: list[str]) -> int | None:
    from llm.structured import complete_json_sync

    listing = "\n".join(f"{i}. {o}" for i, o in enumerate(options))
    r = complete_json_sync(
        "suggest", MATCH_SYSTEM, f"Options:\n{listing}\n\nLearner said: {spoken[:300]}", Pick, max_tokens=200
    )
    return r.index if r.confident and 0 <= r.index < len(options) else None
