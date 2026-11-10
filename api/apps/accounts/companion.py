"""The learner's companion (any entry in the registry, companions.py — or the name they gave it).

AI prompts that speak *as* the companion are written with "You are Kili, …"; `as_companion` swaps in the
learner's own companion and its personality, so "Learn with …", hints, check-ins and explanations all come from
the mascot the learner chose."""

from .companions import COMPANIONS, DEFAULT_CHARACTER
from .preferences import upgrade

PERSONA = {cid: c["persona"] for cid, c in COMPANIONS.items()}
DEFAULT_NAMES = {cid: c["name"] for cid, c in COMPANIONS.items()}


def companion(user) -> dict:
    """{character, name, persona} for this user (defaults to Kili)."""
    m = (
        upgrade(user.preferences.data)["mascot"]
        if user and getattr(user, "is_authenticated", False) and hasattr(user, "preferences")
        else {}
    )
    character = m.get("character") if m.get("character") in PERSONA else DEFAULT_CHARACTER
    name = (m.get("name") or "").strip()[:24] or DEFAULT_NAMES[character]
    if name.lower() in {n.lower() for n in DEFAULT_NAMES.values()}:
        name = DEFAULT_NAMES[character]  # a default name follows the chosen character
    return {"character": character, "name": name, "persona": PERSONA[character]}


def as_companion(system: str, user) -> str:
    """Rewrite a "You are Kili, …" system prompt so it speaks as the learner's own companion."""
    c = companion(user)
    intro = f"You are {c['name']}, {c['persona']} — "
    if "You are Kili, " in system:
        system = system.replace("You are Kili, ", intro, 1)
    return system.replace("Kili", c["name"])
