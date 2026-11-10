"""The companion registry is the single source of truth, on both sides of the app."""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.accounts.companion import DEFAULT_NAMES, PERSONA, as_companion, companion
from apps.accounts.companions import COMPANIONS, DEFAULT_CHARACTER
from apps.accounts.preferences import MASCOTS, MascotPrefs

WEB_REGISTRY = Path(__file__).resolve().parents[2] / "web" / "src" / "mascot" / "companions.ts"


def test_backend_and_web_registries_list_the_same_companions():
    web_ids = re.findall(r'\{\s*id:\s*"([a-z0-9_]+)"', WEB_REGISTRY.read_text())
    assert web_ids, "could not read web/src/mascot/companions.ts"
    assert sorted(web_ids) == sorted(COMPANIONS)


def test_registry_shape_and_derived_tables():
    assert DEFAULT_CHARACTER in COMPANIONS
    assert MASCOTS == tuple(COMPANIONS)
    for cid, c in COMPANIONS.items():
        assert re.fullmatch(r"[a-z0-9_]{1,12}", cid)  # stored in prefs and the 12-char hint persona column
        assert c["name"] and c["persona"]
        assert DEFAULT_NAMES[cid] == c["name"] and PERSONA[cid] == c["persona"]


@pytest.mark.django_db
@pytest.mark.parametrize("cid", list(COMPANIONS))
def test_every_registered_companion_can_be_chosen_and_speaks_as_itself(cid):
    from apps.accounts.models import User

    MascotPrefs.model_validate({"character": cid})  # accepted by the preferences schema
    u = User.objects.create_user(email=f"{cid}@example.com", password="x-Strong-pass-123")
    u.preferences.data = {
        **u.preferences.data,
        "mascot": {**u.preferences.data.get("mascot", {}), "character": cid, "name": "Kili"},
    }
    u.preferences.save()
    c = companion(u)
    assert (
        c["character"] == cid and c["name"] == COMPANIONS[cid]["name"]
    )  # a default name follows the companion
    assert as_companion("You are Kili, a tutor.", u).startswith(
        f"You are {COMPANIONS[cid]['name']}, {COMPANIONS[cid]['persona']}"
    )


def test_unknown_companion_is_refused():
    with pytest.raises(ValidationError):
        MascotPrefs.model_validate({"character": "dragon"})
