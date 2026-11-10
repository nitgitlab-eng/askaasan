"""Milestone 9 — 'Set up with Kili': a short admin chat about the organisation that proposes concrete setup actions
(description, groups, units, target roles, feature switches, a first course template). Nothing changes until an
org admin accepts a proposal; each one is applied at most once."""

import json

from django.db import transaction
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from llm.fence import defang, fence

from .models import Group, OrgSetupChat, SubUnit
from .perms import require

MAX_USER_TURNS = 8
PROPOSAL_TEXT_MAX = 600  # what the approval list shows in full: nothing beyond it is stored or applied
CHATS_PER_DAY = 40
FEATURES = ("mentor", "live", "roleplay", "leaderboard", "shop")


def _current(org) -> str:
    return json.dumps(
        {
            "name": org.display_name or org.name,
            "kind": org.kind,
            "description": org.description[:600],
            "groups": list(org.groups.exclude(name="Everyone").values_list("name", flat=True)[:30]),
            "units": list(org.units.values_list("name", flat=True)[:30]),
            "target_roles": org.target_roles,
            "features": {k: (org.features or {}).get(k, True) for k in FEATURES},
        },
        ensure_ascii=False,
    )


def _out(chat) -> dict:
    turns = sum(1 for m in chat.messages if m["role"] == "user")
    return {"messages": chat.messages, "turns": turns, "max_turns": MAX_USER_TURNS}


@api_view(["GET", "POST", "DELETE"])
def setup_chat(request, slug):
    from apps.learning.services import content_language
    from apps.paths.models import CareerPath
    from apps.providers.services import BudgetExceeded, charge
    from llm.base import LLMError
    from llm.prompts.curriculum import LANG_RULE
    from llm.prompts.orgs import SETUP_CHAT_SYSTEM, SetupChatOut
    from llm.structured import complete_json_sync

    me = require(request.user, slug, "admin")
    org = me.org
    chat, _ = OrgSetupChat.objects.get_or_create(org=org)
    if request.method == "GET":
        return Response(_out(chat))
    if request.method == "DELETE":  # start over
        with transaction.atomic():
            chat = OrgSetupChat.objects.select_for_update().get(pk=chat.pk)
            chat.messages = []
            chat.save()
        return Response(_out(chat))
    text = str(request.data.get("message") or "").strip()
    if not 1 <= len(text) <= 1500:
        return Response({"code": "bad_message"}, status=status.HTTP_400_BAD_REQUEST)
    if _out(chat)["turns"] >= MAX_USER_TURNS:
        return Response({"code": "chat_full"}, status=status.HTTP_409_CONFLICT)
    try:
        charge(request.user, "org_setup_chat", 1, CHATS_PER_DAY)
    except BudgetExceeded:
        return Response({"code": "daily_limit"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    roles = (
        ", ".join(CareerPath.objects.filter(published=True).values_list("slug", flat=True)[:80]) or "(none)"
    )
    history = "\n".join(f"{m['role']}: {m['content'][:600]}" for m in chat.messages[-12:])
    system = SETUP_CHAT_SYSTEM.format(
        kind=org.kind,
        roles=roles,
        current=defang(_current(org), "current_setup"),
        lang_rule=LANG_RULE[content_language(request.user)],
    )
    from apps.accounts.companion import as_companion

    system = as_companion(system, request.user)
    try:
        out = complete_json_sync(
            "suggest",
            system,
            f"EARLIER:\n{defang(history, 'message')}\n\nADMIN: {fence('message', text)}",
            SetupChatOut,
            max_tokens=3000,
        )
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    proposals = [{**p.model_dump(), "text": p.text[:PROPOSAL_TEXT_MAX]} for p in out.proposals[:8]]
    with (
        transaction.atomic()
    ):  # re-read under a row lock: an apply (or another turn) during the AI call is never overwritten
        chat = OrgSetupChat.objects.select_for_update().get(pk=chat.pk)
        if _out(chat)["turns"] >= MAX_USER_TURNS:
            return Response({"code": "chat_full"}, status=status.HTTP_409_CONFLICT)
        # Append only (never trim): turn indexes stay stable for apply; the turn cap bounds the size.
        chat.messages = [
            *chat.messages,
            {"role": "user", "content": text},
            {
                "role": "assistant",
                "content": out.reply[:2000],
                "proposals": proposals,
                "applied": [],
                "rejected": [],
                "errors": {},
            },
        ]
        chat.save()
    return Response(_out(chat))


def apply_proposal(org, user, p: dict) -> str:
    """Execute one accepted proposal. Returns "" or a short error code. All input is re-validated here."""
    from apps.learning.models import Curriculum
    from apps.paths.models import CareerPath

    op, title, text = p.get("op"), str(p.get("title") or "").strip(), str(p.get("text") or "").strip()
    if op == "set_description":
        if not text:
            return "empty"
        org.description = text[:PROPOSAL_TEXT_MAX]
        org.save(update_fields=["description"])
    elif op == "add_group":
        if not title or title == "Everyone":
            return "missing_title"
        if org.groups.filter(name__iexact=title[:80]).exists():
            return "exists"
        Group.objects.create(org=org, name=title[:80])
    elif op == "add_unit":
        if not title:
            return "missing_title"
        if org.units.filter(name__iexact=title[:80]).exists():
            return "exists"
        if org.units.count() >= 50:
            return "too_many_units"
        SubUnit.objects.create(org=org, name=title[:80], description=text[:300])
    elif op == "set_target_roles":
        wanted = [str(r)[:80] for r in p.get("roles") or []][:5]
        ok = set(CareerPath.objects.filter(slug__in=wanted, published=True).values_list("slug", flat=True))
        roles = [r for r in wanted if r in ok]
        if not roles:
            return "unknown_role"
        org.target_roles = roles
        org.career_slug = org.career_slug or roles[0]  # the competency heat-map follows the first role
        org.save(update_fields=["target_roles", "career_slug"])
    elif op == "set_feature":
        if p.get("feature") not in FEATURES:
            return "unknown_feature"
        org.features = {**(org.features or {}), p["feature"]: bool(p.get("on"))}
        org.save(update_fields=["features"])
    elif op == "course_idea":
        if not title:
            return "missing_title"
        # A draft course shared as an org template; the admin builds it in the Creator Lab.
        Curriculum.objects.create(
            owner=user,
            goal=(text or title)[:300],
            title=title[:200],
            description=text[:PROPOSAL_TEXT_MAX],
            kind="authored",
            status="ready",
            language="en",
            template_scope="org",
            template_org=org,
        )
    else:
        return "unknown_op"
    return ""


class ApplyIn(serializers.Serializer):
    turn = serializers.IntegerField(min_value=0)
    accept = serializers.ListField(child=serializers.IntegerField(min_value=0), max_length=8)
    reject = serializers.ListField(child=serializers.IntegerField(min_value=0), max_length=8, required=False)


@api_view(["POST"])
def setup_chat_apply(request, slug):
    me = require(request.user, slug, "admin")
    ser = ApplyIn(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    with transaction.atomic():
        chat = OrgSetupChat.objects.select_for_update().filter(org=me.org).first()
        if not chat or d["turn"] >= len(chat.messages) or chat.messages[d["turn"]].get("role") != "assistant":
            return Response({"code": "bad_turn"}, status=status.HTTP_400_BAD_REQUEST)
        msgs = list(chat.messages)
        turn = dict(msgs[d["turn"]])
        props = turn.get("proposals") or []
        done = (
            set(turn.get("applied") or [])
            | set(turn.get("rejected") or [])
            | {int(k) for k in (turn.get("errors") or {})}
        )
        results = {}
        for i in sorted(set(d["accept"])):
            if i < len(props) and i not in done:
                results[i] = apply_proposal(me.org, request.user, props[i])
        applied = [i for i, e in results.items() if not e]
        turn["applied"] = sorted(set(turn.get("applied") or []) | set(applied))
        rej = {i for i in (d.get("reject") or []) if i < len(props) and i not in done}
        turn["rejected"] = sorted((set(turn.get("rejected") or []) | rej) - set(turn["applied"]))
        turn["errors"] = {**(turn.get("errors") or {}), **{str(i): e for i, e in results.items() if e}}
        msgs[d["turn"]] = turn
        chat.messages = msgs
        chat.save()
    return Response({**_out(chat), "results": results})
