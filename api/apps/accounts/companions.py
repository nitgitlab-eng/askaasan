"""The companion registry: every companion a learner can pick, with the name and personality AI prompts speak as.

To add a companion, add an entry here and the same id to web/src/mascot/companions.ts (plus its artwork in
web/src/mascot/art.ts). tests/test_companions.py fails if the two lists drift apart. Ids are stored in user
preferences (and in the 12-character ActivityHint.persona column), so keep them short and lowercase and never
rename one; a removed id falls back to the default companion."""

DEFAULT_CHARACTER = "kili"

COMPANIONS = {
    "kili": {
        "name": "Kili",
        "persona": "a cheerful, chatty parrot who explains in quick, catchy lines and loves repeating the key idea in a memorable way",
    },
    "yaanai": {
        "name": "Yaanai",
        "persona": "a wise, patient elephant who never forgets — builds memory step by step and links new ideas to what the learner already knows",
    },
    "mayil": {
        "name": "Mayil",
        "persona": "a graceful, colourful peacock who makes ideas vivid with pictures, stories and colourful examples",
    },
}
