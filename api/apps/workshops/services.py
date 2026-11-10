"""The workshop engine: a server-owned, learner-paced state machine.

Nothing here ever advances the learner or submits for them: the cursor moves only on the learner's Next, a DIY step
is ticked only by the learner, and the final is graded only when they send it. Time is a pacing guide; once past
the planned end the session is labelled in_grace / overtime, and only a generous daily safety cap pauses AI turns.

Each learner action returns an `Out`: an error code, whether progress changed, and (optionally) a director note
for the next streamed AI turn. The consumer streams it and calls `after_turn`."""

import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import WorkshopEvent, WorkshopSession, WorkshopTurn

log = logging.getLogger(__name__)

PASS = 0.7  # same bar as the lesson tutor (apps/learning/tutor.py)
MAX_TRIES = 3
HISTORY = 12  # turns of transcript sent with each AI turn
READY_TURNS = 10  # turns replayed on (re)connect
HOST_MAX_TOKENS = 1500  # room for Tamil script; the prompt still asks for ≤90 words a turn
CHECK_MAX_TOKENS = 400
HELP_MAX_TOKENS = 1200
FINAL_ATTEMPTS = 3
RAISE_HAND_GAP = timedelta(seconds=10)
DIY_KINDS = ("diy", "build", "agent_build")  # agent_build: DIY steps plus the agent builder panel (agent.py)
ITEM_KEY = {"teach": "concepts", "check": "questions", **dict.fromkeys(DIY_KINDS, "steps")}
ATTENTION = {
    "hidden": "tab_hidden",
    "visible": "tab_visible",
    "blur": "blur",
    "focus": "focus",
    "idle": "idle",
    "active": "active",
    "fs_exit": "fs_exit",
}
# A `build` stage's graded task: one of these lesson activity types.
BUILD_TYPES = ("code", "open_input", "artifact_check")
BUILD_ATTEMPTS = 5  # graded hand-ins per build stage
BUILD_MAX_TOKENS = 1500  # what one AI-graded hand-in costs against the session budget
BUILD_ANSWER_MAX = {"code": 6000, "stdout": 1000, "text": 6000, "url": 500}
GRACE_MESSAGE = "Your timeline is over — you're in a grace period."
OVERTIME_MESSAGE = "You're over time. Take your time and carry on."
# Suggested replies: a fixed allow-list of chip ids (the client maps each to a translated label and a message), so
# no model text ever becomes a button.
CHIPS = ("yes_next", "not_yet", "not_sure", "example", "tamil", "english", "done", "stuck", "continue")
MAX_CHIPS = 3
# A short typed or spoken consent ("yes", "ok next", "சரி") moves on when the learner is ready_to_move.
CONSENT_WORDS = frozenset(
    [
        "yes",
        "yeah",
        "yep",
        "ya",
        "yup",
        "ok",
        "okay",
        "k",
        "sure",
        "next",
        "continue",
        "sari",
        "seri",
        "aama",
        "aamaa",
        "aduthu",
        "போகலாம்",
        "சரி",
        "ஆமா",
        "ஆமாம்",
        "அடுத்து",
    ]
)
CONSENT_FILLER = frozenset(
    [
        "move",
        "on",
        "go",
        "ahead",
        "please",
        "pls",
        "let",
        "lets",
        "s",
        "sir",
        "madam",
        "mam",
        "da",
        "ma",
        "now",
    ]
)
CONSENT_PHRASES = (("move", "on"), ("go", "ahead"), ("go", "on"), ("let", "go"), ("lets", "go"))
CONSENT_MAX_WORDS = 4


def now() -> datetime:
    """The engine's clock (tests freeze it)."""
    return timezone.now()


@dataclass
class Out:
    error: str | None = None
    progress: bool = False
    note: str | None = None
    after: tuple | None = None  # applied once the AI turn finishes, e.g. ("explained", stage, item)
    paused: str | None = None
    instr: str = ""  # the bare instruction behind `note` (so a reply can combine it with an answer)


# ── State helpers ────────────────────────────────────────────────────


def agenda(s) -> list[dict]:
    return s.run.workshop.agenda or []


def stage(s, i: int | None = None) -> dict | None:
    a = agenda(s)
    i = s.stage_index if i is None else i
    return a[i] if 0 <= i < len(a) else None


def item_texts(st: dict) -> list[str]:
    key = ITEM_KEY.get(st.get("kind"))
    if not key:
        return []
    return [q["q"] if isinstance(q, dict) else str(q) for q in st.get(key) or []]


def state(s, i: int | None = None) -> dict:
    """This stage's {cursor, items}, created on first use."""
    i = s.stage_index if i is None else i
    st = stage(s, i) or {}
    cur = s.stage_state.get(str(i))
    n = len(item_texts(st))
    if not cur or len(cur.get("items", [])) != n:
        cur = {
            "cursor": 0,
            "items": [
                {
                    "explained": False,
                    "done": False,
                    "tries": 0,
                    "score": None,
                    "skipped": False,
                    "ready_to_move": False,
                }
                for _ in range(n)
            ],
        }
        s.stage_state[str(i)] = cur
    return cur


def lang(s) -> str:
    from apps.learning.services import content_language

    return s.stage_state.get("_lang") or content_language(s.user)


def event(s, type_: str, **data) -> WorkshopEvent:
    return WorkshopEvent.objects.create(session=s, type=type_, stage=s.stage_index, data=data)


def turn(s, role: str, text: str, cancelled: bool = False):
    if text:
        WorkshopTurn.objects.create(
            session=s, role=role, text=text[:8000], stage=s.stage_index, cancelled=cancelled
        )


def ready_to_move(s, i: int | None = None) -> bool:
    """Whether the learner on stage `i` (default: the current one) has finished its current item, so the host asks
    "Shall we move on?" and a yes moves them on: the item passed its check, used its tries or was ticked done. A stage
    with no items is ready at once; the final assessment never is."""
    i = s.stage_index if i is None else i
    if not s.started_at or s.status == WorkshopSession.Status.SUBMITTED:
        return False
    st = stage(s, i) or {}
    if st.get("kind") == "assessment":
        return False
    cur = state(s, i)
    c = cur["cursor"]
    if c >= len(cur["items"]):
        return True
    return bool(cur["items"][c].get("ready_to_move"))


def is_consent(text: str) -> bool:
    """A short "yes, move on" in English, Tanglish or Tamil (≤ 4 words, nothing but consent and filler words)."""
    words = re.sub(r"[^\w\s\u0B80-\u0BFF]", " ", (text or "").lower()).split()
    if not words or len(words) > CONSENT_MAX_WORDS:
        return False
    if any(w not in CONSENT_WORDS and w not in CONSENT_FILLER for w in words):
        return False
    return any(w in CONSENT_WORDS for w in words) or any(set(p) <= set(words) for p in CONSENT_PHRASES)


def locked(session_id) -> WorkshopSession:
    return (
        WorkshopSession.objects.select_for_update(of=("self",))
        .select_related("run__workshop", "user")
        .get(pk=session_id)
    )


def load(session_id) -> WorkshopSession:
    return WorkshopSession.objects.select_related("run__workshop", "user").get(pk=session_id)


# ── Clock ────────────────────────────────────────────────────────────


def label(s, at: datetime | None = None) -> str:
    """prereq | active | in_grace | overtime | submitted (labels only: they never block anything)."""
    if s.status == WorkshopSession.Status.SUBMITTED:
        return s.status
    if not s.started_at:
        return WorkshopSession.Status.PREREQ
    at = at or now()
    if at >= s.grace_end:
        return WorkshopSession.Status.OVERTIME
    if at >= s.planned_end:
        return WorkshopSession.Status.IN_GRACE
    return WorkshopSession.Status.ACTIVE


def pace(s, at: datetime | None = None) -> dict | None:
    """{status: on_track|behind|in_grace|overtime|submitted, minutes_left, message}. minutes_left counts to the
    planned end (on_track/behind), to the end of the grace period (in_grace), and is 0 when over time."""
    if not s.started_at:
        return None
    at = at or now()
    lab = label(s, at)
    if lab == WorkshopSession.Status.SUBMITTED:
        return {"status": "submitted", "minutes_left": 0, "message": ""}
    if lab == WorkshopSession.Status.OVERTIME:
        return {"status": "overtime", "minutes_left": 0, "message": OVERTIME_MESSAGE}
    if lab == WorkshopSession.Status.IN_GRACE:
        left = math.ceil((s.grace_end - at).total_seconds() / 60)
        return {"status": "in_grace", "minutes_left": left, "message": GRACE_MESSAGE}
    a = agenda(s)
    planned = sum(int(x.get("minutes") or 0) for x in a[: s.stage_index + 1])
    elapsed = (at - s.started_at).total_seconds() / 60
    left = math.ceil((s.planned_end - at).total_seconds() / 60)
    behind = elapsed > planned
    msg = "We're a little behind the plan. Take your time, or tap Next when you're ready." if behind else ""
    return {"status": "behind" if behind else "on_track", "minutes_left": left, "message": msg}


def tick(session_id) -> tuple[dict | None, bool]:
    """Clock tick: store the status label; → (pace, announce_grace). The grace announcement is claimed only once."""
    with transaction.atomic():
        s = locked(session_id)
        at = now()
        p = pace(s, at)
        lab = label(s, at)
        fields = []
        if s.status != lab:
            s.status = lab
            fields.append("status")
        announce = lab in (WorkshopSession.Status.IN_GRACE, WorkshopSession.Status.OVERTIME) and not (
            s.grace_announced
        )
        if fields:
            s.save(update_fields=fields)
        return p, announce


def claim_grace(session_id) -> bool:
    return (
        WorkshopSession.objects.filter(pk=session_id, grace_announced=False).update(grace_announced=True) == 1
    )


def cap_reason(s, at: datetime) -> str | None:
    """The safety cap: after WORKSHOP_CAP_MULTIPLIER × the planned duration in one day, AI turns pause until
    tomorrow ("continue tomorrow"). It never fails or blocks the learner."""
    if not s.started_at:
        return None
    raw = s.stage_state.get("_cap_from")
    anchor = datetime.fromisoformat(raw) if raw else s.started_at
    if timezone.localdate(anchor) < timezone.localdate(at):
        anchor = at
        s.stage_state["_cap_from"] = at.isoformat()
        s.save(update_fields=["stage_state"])
    cap = timedelta(minutes=s.run.workshop.duration_minutes * settings.WORKSHOP_CAP_MULTIPLIER)
    return "cap" if at - anchor >= cap else None


def ai_paused(s, at: datetime | None = None) -> str | None:
    from apps.providers.services import ai_units

    if s.ai_units + ai_units(CHECK_MAX_TOKENS) > settings.WORKSHOP_SESSION_AI_UNITS:
        return "budget"
    return cap_reason(s, at or now())


def spend(session_id, max_tokens: int, *, exempt: bool = False) -> str | None:
    """Charge one AI call (providers.charge, weighted by max_tokens) against the session budget.
    → None when allowed, else the pause reason ("budget" | "cap"). `exempt` (final grading) never pauses."""
    from apps.providers.services import ai_units, charge

    units = ai_units(max_tokens)
    with transaction.atomic():
        s = locked(session_id)
        if not exempt:
            if reason := cap_reason(s, now()):
                return reason
            if s.ai_units + units > settings.WORKSHOP_SESSION_AI_UNITS:
                return "budget"
        charge(s.user, "workshop_ai", 1, 0, max_tokens=max_tokens)
        WorkshopSession.objects.filter(pk=s.pk).update(ai_units=s.ai_units + units)
    return None


# ── Session object ───────────────────────────────────────────────────


def certificate_out(cert) -> dict | None:
    if not cert:
        return None
    from apps.credentials.services import verify_url

    return {
        "id": cert.id,
        "code": cert.code,
        "url": verify_url(cert),
        "pdf_url": f"/api/credentials/{cert.id}/pdf/",
    }


def final_public(w) -> dict:
    """The final form as the learner sees it: never the answer keys."""
    f = w.final or {}
    return {
        "mcqs": [{"q": m["q"], "options": list(m["options"])} for m in f.get("mcqs", [])],
        "practical": {"prompt": (f.get("practical") or {}).get("prompt", "")},
        "agent_tests": len(f.get("agent_tests") or []),  # how many hidden tests the saved agent will face
    }


def session_out(s) -> dict:
    w = s.run.workshop
    stages = []
    for i, st in enumerate(w.agenda or []):
        state_i = state(s, i)
        items = [
            {"text": t, "done": it["done"], "explained": it["explained"]}
            for t, it in zip(item_texts(st), state_i["items"], strict=False)
        ]
        kind = st.get("kind")
        stages.append(
            {
                "key": st.get("key", str(i)),
                "kind": kind,
                "title": st.get("title", ""),
                "minutes": st.get("minutes") or 0,
                "concepts": items if kind in ("teach", "check") else [],
                "steps": items if kind in DIY_KINDS else [],
                "cursor": state_i["cursor"],
                "ready_to_move": ready_to_move(s, i),
                "task": build_out(st, state_i),
            }
        )
    prereqs = [
        {
            "key": p["key"],
            "label": p.get("label", ""),
            "how_to_md": p.get("how_to_md", ""),
            "done": p["key"] in s.prereqs_done,
        }
        for p in w.prerequisites or []
    ]
    cur = stage(s)
    return {
        "id": s.id,
        "status": label(s),
        "workshop": {
            "slug": w.slug,
            "title": w.title,
            "summary": w.summary,
            "duration_minutes": w.duration_minutes,
            "grace_minutes": w.grace_minutes,
            "proctoring": s.run.effective_proctoring,
            "pass_mark": w.pass_mark,
        },
        "prerequisites": prereqs,
        "ready": all(p["done"] for p in prereqs),
        "started_at": s.started_at,
        "planned_end": s.planned_end,
        "grace_end": s.grace_end,
        "stage_index": s.stage_index,
        "stage_kind": (cur or {}).get("kind"),
        "stages": stages,
        "scores": s.scores,
        "final_score": s.final_score,
        "final_attempts": s.final_attempts,
        "attempts_left": max(0, FINAL_ATTEMPTS - s.final_attempts) if not s.passed else 0,
        "final": final_public(w) if s.started_at else None,
        "passed": s.passed,
        "certificate": certificate_out(s.certificate),
        "proctoring": s.run.effective_proctoring,
        "proctor_notice_seen": s.proctor_notice_at is not None,
        "institution_notice": institution_notice(s.run),  # org runs: what the institution's dashboard shows
        "institution_sees": institution_sees(s.run),
        "language": s.stage_state.get("_lang") or "",
        "pace": pace(s),
        "paused": ai_paused(s) if s.started_at else None,
        "agent_score": ((s.agent or {}).get("final_tests") or {}).get("score"),
        "agent_tests": ((s.agent or {}).get("final_tests") or {}).get("tests") or [],
    }


def institution_notice(run):
    from .org import institution_notice as notice

    return notice(run)


def institution_sees(run):
    from .org import institution_sees as sees

    return sees(run)


def recent_turns(s, n: int = READY_TURNS) -> list[dict]:
    rows = list(WorkshopTurn.objects.filter(session=s).order_by("-created_at", "-id")[:n])[::-1]
    return [turn_out(t) for t in rows]


def turn_out(t) -> dict:
    return {"role": t.role, "text": t.text, "stage": t.stage, "ts": t.created_at, "cancelled": t.cancelled}


# ── REST actions ─────────────────────────────────────────────────────


def tick_prereq(s, key: str, done: bool) -> bool:
    keys = [p["key"] for p in s.run.workshop.prerequisites or []]
    if key not in keys:
        return False
    if done:
        s.prereqs_done.setdefault(key, now().isoformat())
    else:
        s.prereqs_done.pop(key, None)
    all_done = all(k in s.prereqs_done for k in keys)
    if not s.started_at:
        s.ready_at = (s.ready_at or now()) if all_done else None
    s.save(update_fields=["prereqs_done", "ready_at"])
    return True


def start(s) -> str | None:
    """Prerequisites first: → error code, or None once started (idempotent)."""
    if s.started_at:
        return None
    keys = [p["key"] for p in s.run.workshop.prerequisites or []]
    if not all(k in s.prereqs_done for k in keys):
        return "prereqs_incomplete"
    at = now()
    w = s.run.workshop
    s.started_at = at
    s.planned_end = at + timedelta(minutes=w.duration_minutes)
    s.grace_end = s.planned_end + timedelta(minutes=w.grace_minutes)
    s.ready_at = s.ready_at or at
    s.proctor_notice_at = s.proctor_notice_at or at
    s.status = WorkshopSession.Status.ACTIVE
    s.last_activity_at = at
    s.stage_index = 0
    s.save()
    event(s, "stage_start", key=(stage(s) or {}).get("key", "0"))
    return None


# ── Socket actions ───────────────────────────────────────────────────


def _ctx(s) -> str:
    from llm.prompts.workshop import _ctx as ctx

    return ctx(s.run.workshop.title, stage(s) or {}, lang(s))


def _intro(s) -> Out:
    """The note that opens the current item (or stage) — used on entering it and on first connect."""
    from llm.prompts import workshop as P

    st = stage(s) or {}
    kind = st.get("kind")
    if kind == "assessment":
        return Out(progress=True, note=P.note(_ctx(s), P.ASSESSMENT_INTRO))
    texts = item_texts(st)
    if not texts:
        return Out(progress=True, note=P.note(_ctx(s), P.STAGE_INTRO))
    cur = state(s)
    i = min(cur["cursor"], len(texts) - 1)
    if kind == "teach":
        instr = P.explain_concept(i, len(texts), texts[i])
    elif kind == "check":
        instr = P.ask_question(i, len(texts), texts[i])
    else:
        instr = P.explain_step(i, len(texts), texts[i], st.get("task", ""))
    return Out(progress=True, note=P.note(_ctx(s), instr), after=("explained", s.stage_index, i), instr=instr)


def opening(session_id) -> Out:
    """On (re)connect after start: if the current item was never explained, explain it now (this starts the item
    the learner is on; it never moves them on). A reconnect mid-item says nothing."""
    with transaction.atomic():
        s = locked(session_id)
        if not s.started_at or s.status == WorkshopSession.Status.SUBMITTED:
            return Out()
        st = stage(s) or {}
        cur = state(s)
        items = cur["items"]
        if st.get("kind") == "assessment":
            seen = WorkshopTurn.objects.filter(session=s, stage=s.stage_index, role="assistant").exists()
            return Out() if seen else _intro(s)
        if items and cur["cursor"] < len(items) and not items[cur["cursor"]]["explained"]:
            s.save(update_fields=["stage_state"])
            return _intro(s)
        return Out()


def after_turn(session_id, reply: str, after: tuple | None, cancelled: bool = False) -> bool:
    """Save the host's reply and apply its effect. → whether progress changed (an item became explained).
    A reply interrupted before it finished is saved flagged `cancelled` and has no effect: it doesn't explain the item
    and isn't the check question the next answer is assessed against."""
    with transaction.atomic():
        s = locked(session_id)
        turn(s, "assistant", reply, cancelled=cancelled)
        if cancelled:
            event(s, "ai_turn", chars=len(reply), cancelled=True)
            return False
        changed = False
        if after and reply.strip() and after[0] == "explained":
            _, si, ii = after
            cur = state(s, si)
            if ii < len(cur["items"]) and not cur["items"][ii]["explained"]:
                cur["items"][ii]["explained"] = True
                changed = True
        if after and reply.strip():  # the host's latest check question, for assessing the next answer
            state(s, after[1])["last_q"] = reply[-1500:]
        event(s, "ai_turn", chars=len(reply))
        s.save(update_fields=["stage_state"])
        return changed


def host_context(session_id, exclude_last_user: bool) -> tuple[str, list]:
    """(system, history) for a host turn: the learner's tutor prompt + workshop rules, and recent turns as text."""
    from apps.accounts.preferences import upgrade
    from llm.base import ChatMessage
    from llm.prompts.tutor import build_tutor_system
    from llm.prompts.workshop import host_system

    s = load(session_id)
    prefs = upgrade(s.user.preferences.data)
    system = host_system(
        build_tutor_system(s.user.profile, prefs, prefs["mascot"]["name"]),
        s.user,
        s.user.profile.display_name,
    )
    # Interrupted host replies stay out of the context: the model never builds on a half-said sentence.
    turns = WorkshopTurn.objects.filter(session=s, cancelled=False)
    rows = list(turns.order_by("-created_at", "-id")[: HISTORY + 1])[::-1]
    if exclude_last_user and rows and rows[-1].role == "user":
        rows = rows[:-1]
    # One message per turn: consecutive learner turns stay separate (all our providers accept repeated roles).
    msgs: list = [
        ChatMessage("assistant" if t.role == "assistant" else "user", t.text) for t in rows[-HISTORY:]
    ]
    while msgs and msgs[0].role == "assistant":  # a conversation opens with the user
        msgs.pop(0)
    if msgs and msgs[-1].role == "user":  # the director note follows as the next user message
        msgs.append(ChatMessage("assistant", "…"))
    return system, msgs


def _assess(s, concept: str, last_q: str, text: str):
    from llm.prompts.workshop import CHECK_SYSTEM, WorkshopCheck, check_user
    from llm.structured import complete_json_sync

    return complete_json_sync(
        "tutor", CHECK_SYSTEM, check_user(concept, last_q, text), WorkshopCheck, max_tokens=CHECK_MAX_TOKENS
    )


def on_say(session_id, text: str) -> Out:
    from llm.prompts import workshop as P

    with transaction.atomic():
        s = locked(session_id)
        turn(s, "user", text)
        s.last_activity_at = now()
        s.save(update_fields=["last_activity_at"])
        consent = is_consent(text) and ready_to_move(s)
    if consent:  # "yes" / "next" / "சரி" when the host has asked "Shall we move on?"
        return on_next(session_id, consent=True)
    with transaction.atomic():
        s = locked(session_id)
        if not s.started_at:
            return Out(note=P.note(_ctx(s), P.prereq_help(s.run.workshop.prerequisites or []), text))
        st = stage(s) or {}
        kind = st.get("kind")
        texts = item_texts(st)
        cur = state(s)
        i = cur["cursor"]
        item = cur["items"][i] if i < len(texts) else {}
        if (
            kind in ("teach", "check", *DIY_KINDS)
            and i < len(texts)
            and not item.get("explained")
            and not item.get("done")
            and not item.get("awaiting_seen")
        ):
            # The item was never fully explained (the learner interrupted it, or spoke first): answer them briefly,
            # then explain it, so the item can be checked and the learner offered chips. Seen in the e2e run: an
            # interrupted opening left the learner with no explanation, no chips and no way on.
            intro = _intro(s)
            return Out(  # no state changes until the reply finishes (after_turn marks the item explained)
                note=P.note(_ctx(s), f"{P.ANSWER_THEN_EXPLAIN} {intro.instr}", text),
                after=intro.after,
            )
        if kind in ("teach", "check") and i < len(texts):
            it = cur["items"][i]
            if it["explained"] and not it["done"]:
                needs_check = (i, s.stage_index, texts[i], cur.get("last_q", ""))
            else:
                return Out(note=P.note(_ctx(s), _general(s), text))
        elif kind in DIY_KINDS and i < len(texts) and cur["items"][i].get("awaiting_seen"):
            cur["items"][i]["awaiting_seen"] = False
            s.save(update_fields=["stage_state"])
            event(s, "answer", item=i, diy=True)
            return Out(note=P.note(_ctx(s), P.STEP_SEEN, text))
        else:
            return Out(note=P.note(_ctx(s), _general(s), text))
    # A check answer: assess it (a charged AI call, outside the row lock), then record the result.
    i, si, concept, last_q = needs_check
    if reason := spend(session_id, CHECK_MAX_TOKENS):
        return Out(paused=reason)
    try:
        result = _assess(s, concept, last_q, text)
    except Exception:
        log.exception("workshop check failed for session %s", session_id)
        return Out(note=P.note(_ctx(s), P.GENERAL, text))
    raw = float(result.score)
    score = min(1.0, max(0.0, raw)) if math.isfinite(raw) else 0.0
    with transaction.atomic():
        s = locked(session_id)
        if s.stage_index != si:
            return Out()
        cur = state(s)
        it = cur["items"][i]
        if it["done"]:
            return Out(note=P.note(_ctx(s), P.GENERAL, text))
        if not result.answered:
            return Out(note=P.note(_ctx(s), P.answer_question(concept), text))
        it["tries"] += 1
        it["score"] = round(max(score, it["score"] or 0.0), 3)
        event(s, "answer", item=i, score=round(score, 2), tries=it["tries"])
        kind = (stage(s) or {}).get("kind")
        progress = False
        if score >= PASS:
            it["done"] = True
            instr = P.check_passed(concept, kind)
        elif it["tries"] >= MAX_TRIES:
            it["done"] = True
            instr = P.check_moved_on(concept, kind)
        else:
            instr = P.check_retry(concept, result.note)
        if it["done"]:
            progress = True
            it["ready_to_move"] = True  # the host now asks "Shall we move on?"
            event(s, "concept_done", item=i, score=it["score"])
        s.save(update_fields=["stage_state"])
        after = None if it["done"] else ("question", si, i)
        return Out(progress=progress, note=P.note(_ctx(s), instr, text), after=after)


def _general(s) -> str:
    from llm.prompts import workshop as P

    return f"{P.GENERAL} {P.READY_ASK}" if ready_to_move(s) else P.GENERAL


def _advance_stage(s) -> Out:
    st = stage(s) or {}
    items = state(s)["items"]
    scored = [it["score"] for it in items if it["score"] is not None]
    if scored:
        s.scores[st.get("key", str(s.stage_index))] = round(sum(scored) / len(scored), 3)
    if s.stage_index + 1 >= len(agenda(s)):
        return Out(error="no_next")
    s.stage_index += 1
    state(s)
    s.save(update_fields=["stage_index", "stage_state", "scores"])
    event(s, "stage_start", key=(stage(s) or {}).get("key", str(s.stage_index)))
    return _intro(s)


def on_next(session_id, consent: bool = False) -> Out:
    """The learner asks to move on: the current concept, step or question — or the stage when its items are done.
    Allowed once the current item has been explained or done (or when AI turns are paused, so a pause never traps
    the learner). `consent` is the learner's yes to the host's "Shall we move on?" (`yes_next`, or a spoken yes): it
    additionally needs the current item to be ready_to_move."""
    with transaction.atomic():
        s = locked(session_id)
        if not s.started_at:
            return Out(error="not_started")
        st = stage(s) or {}
        kind = st.get("kind")
        if kind == "assessment":
            return Out(error="at_final")
        if consent and not ready_to_move(s) and not ai_paused(s):
            return Out(error="not_ready")
        cur = state(s)
        items = cur["items"]
        i = cur["cursor"]
        if i < len(items):
            it = items[i]
            if not it["explained"] and not it["done"] and not ai_paused(s):
                return Out(error="not_explained")
            if not it["done"]:
                it["done"] = True
                it["skipped"] = True
                event(s, "step_skipped" if kind in DIY_KINDS else "concept_skipped", item=i)
            cur["cursor"] = i + 1
            s.last_activity_at = now()
            s.save(update_fields=["stage_state", "last_activity_at"])
            if cur["cursor"] < len(items):
                return _intro(s)
        return _advance_stage(s)


def on_step_done(session_id, step) -> Out:
    from llm.prompts import workshop as P

    with transaction.atomic():
        s = locked(session_id)
        st = stage(s) or {}
        if not s.started_at or st.get("kind") not in DIY_KINDS:
            return Out(error="not_diy")
        try:
            i = int(step)
        except (TypeError, ValueError):
            return Out(error="bad_step")
        cur = state(s)
        if not 0 <= i <= min(cur["cursor"], len(cur["items"]) - 1):
            return Out(error="bad_step")  # can't tick a step that hasn't been reached
        it = cur["items"][i]
        if it["done"]:
            return Out(progress=True)
        it["done"] = True
        it["awaiting_seen"] = True
        it["ready_to_move"] = True
        s.last_activity_at = now()
        s.save(update_fields=["stage_state", "last_activity_at"])
        event(s, "diy_step_done", item=i)
        return Out(progress=True, note=P.note(_ctx(s), P.step_done_check(item_texts(st)[i])))


def on_control(session_id, action: str) -> Out:
    """The learner's buttons (and suggestion chips): style requests (slower, again, example, not_sure, not_yet, stuck,
    continue), a language switch, or `yes_next`, the consent to move on."""
    from llm.prompts import workshop as P

    if action == "yes_next":
        return on_next(session_id, consent=True)
    with transaction.atomic():
        s = locked(session_id)
        if action in ("tamil", "english"):
            s.stage_state["_lang"] = "ta" if action == "tamil" else "en"
            s.save(update_fields=["stage_state"])
            return Out(progress=True, note=P.note(_ctx(s), P.LANGUAGE_SWITCH))
        if action not in P.STYLE:
            return Out(error="bad_control")
        if not s.started_at:
            return Out(
                note=P.note(_ctx(s), f"{P.STYLE[action]} {P.prereq_help(s.run.workshop.prerequisites)}")
            )
        st = stage(s) or {}
        kind = st.get("kind")
        texts = item_texts(st)
        cur = state(s)
        i = cur["cursor"]
        topic = texts[i] if i < len(texts) else st.get("title", "")
        style = P.STUCK_DIY if action == "stuck" and kind in DIY_KINDS else P.STYLE[action]
        if action == "continue" and ready_to_move(s):
            style = f"{style} {P.READY_ASK}"
        tag = "step" if kind in DIY_KINDS else "concept"
        instr = f"{style}\n{P.fence(tag, P.defang(topic, *P.UNTRUSTED))}"
        # A re-explanation of an item still being checked ends with a fresh question: assess the next answer
        # against it.
        open_check = kind in ("teach", "check") and i < len(texts) and not cur["items"][i]["done"]
        after = ("question", s.stage_index, i) if open_check and action != "continue" else None
        return Out(note=P.note(_ctx(s), instr), after=after)


def suggest(session_id, stop_reason: str | None = None) -> list[str]:
    """The 0–3 suggested replies for this moment (ids from CHIPS only, never model text)."""
    s = load(session_id)
    if not s.started_at or s.status == WorkshopSession.Status.SUBMITTED:
        return []
    st = stage(s) or {}
    kind = st.get("kind")
    if kind == "assessment":
        return []
    cur = state(s)
    i = cur["cursor"]
    items = cur["items"]
    chips: list[str] = []
    if ready_to_move(s):
        chips = ["yes_next", "not_yet"]
    elif kind in DIY_KINDS and i < len(items) and not items[i]["done"]:
        chips = ["done", "stuck"]
    elif kind in ("teach", "check") and i < len(items) and items[i]["explained"] and not items[i]["done"]:
        chips = ["not_sure", "example", "english" if lang(s) == "ta" else "tamil"]
    if stop_reason == "max_tokens":
        chips = ["continue", *chips]
    return [c for c in chips if c in CHIPS][:MAX_CHIPS]


def claim_check_in(session_id) -> str | None:
    """The quiet check-in ("Still with me?"), at most once per item: → the director note, or None when it was already
    said for this item, or the session isn't in a state to say it (not started, submitted, final, AI paused)."""
    from llm.prompts import workshop as P

    with transaction.atomic():
        s = locked(session_id)
        if not s.started_at or s.status == WorkshopSession.Status.SUBMITTED:
            return None
        if (stage(s) or {}).get("kind") == "assessment" or ai_paused(s):
            return None
        key = f"{s.stage_index}:{state(s)['cursor']}"
        if s.stage_state.get("_check_in") == key:
            return None
        s.stage_state["_check_in"] = key
        s.save(update_fields=["stage_state"])
        event(s, "check_in", key=key)
        return P.note(_ctx(s), P.CHECK_IN)


def on_raise_hand(session_id) -> Out:
    from llm.prompts import workshop as P

    with transaction.atomic():
        s = locked(session_id)
        last = (
            WorkshopEvent.objects.filter(session=s, type__in=("raise_hand", "hand_ack"))
            .order_by("-id")
            .first()
        )
        if last and last.type == "raise_hand" and timezone.now() - last.created_at < RAISE_HAND_GAP:
            return Out()  # the hand is already up (and unacknowledged): one event, not one per click
        event(s, "raise_hand")
        return Out(note=P.note(_ctx(s), P.RAISE_HAND))


def attention_allowed(s) -> bool:
    """Tab/focus events are collected only when proctoring is on, the session has started, and the current stage is
    not hands-on (switching tabs to do a DIY step is expected and never tracked)."""
    if (
        s.run.effective_proctoring == "off"
        or not s.started_at
        or s.status == WorkshopSession.Status.SUBMITTED
    ):
        return False
    return (stage(s) or {}).get("kind") not in DIY_KINDS


def on_attention(session_id, kind: str) -> Out:
    """Silently ignored unless allowed. Returns a welcome-back note after a long absence."""
    from llm.prompts import workshop as P

    if kind not in ATTENTION:
        return Out()
    with transaction.atomic():
        s = locked(session_id)
        if not attention_allowed(s):
            return Out()
        at = now()
        att = s.stage_state.setdefault("_att", {})
        event(s, ATTENTION[kind])
        fields = ["stage_state"]
        welcome = False
        if kind in ("hidden", "blur", "fs_exit"):
            s.focus_losses += 1
            fields.append("focus_losses")
        if kind == "hidden":
            att["hidden_at"] = at.isoformat()
        elif kind == "visible" and att.get("hidden_at"):
            secs = max(0, int((at - datetime.fromisoformat(att.pop("hidden_at"))).total_seconds()))
            s.hidden_seconds += secs
            fields.append("hidden_seconds")
            welcome = secs >= 60
        if kind == "idle":
            att["idle_at"] = at.isoformat()
        elif kind == "active" and att.get("idle_at"):
            s.idle_seconds += max(0, int((at - datetime.fromisoformat(att.pop("idle_at"))).total_seconds()))
            fields.append("idle_seconds")
        if s.started_at:
            spent = max(1.0, (at - s.started_at).total_seconds())
            s.attention_score = round(max(0.0, 1 - (s.hidden_seconds + s.idle_seconds) / spent), 3)
            fields.append("attention_score")
        s.save(update_fields=fields)
        return Out(note=P.note(_ctx(s), P.WELCOME_BACK)) if welcome else Out()


def grace_note(session_id) -> str:
    from llm.prompts import workshop as P

    return P.note(_ctx(load(session_id)), P.GRACE)


# ── Build stages (graded hand-in) ────────────────────────────────────


def build_task(st: dict | None) -> tuple[str, dict, dict] | None:
    """A `build` stage's graded task → (type, public payload, private key), split by the lesson activity builder
    (apps.learning.activities.build), or None when the stage has no (valid) task. The key (rubric, model answer or
    solution, expected checks) never leaves the server."""
    spec = (st or {}).get("build") if (st or {}).get("kind") == "build" else None
    if not isinstance(spec, dict) or spec.get("type") not in BUILD_TYPES:
        return None
    from apps.learning.activities import build

    try:
        payload, key = build(spec, 0)
    except (KeyError, TypeError, ValueError):
        log.warning("workshop build stage %s has an invalid task", st.get("key"))
        return None
    return spec["type"], payload, key


def build_out(st: dict, cur: dict) -> dict | None:
    """The build task as the learner sees it: {type, title, payload, attempt, attempts_left, best_score}."""
    task = build_task(st)
    if not task:
        return None
    b = cur.get("build") or {}
    return {
        "type": task[0],
        "title": st.get("title", ""),
        "payload": task[1],
        "attempt": b.get("last"),
        "attempts_left": max(0, BUILD_ATTEMPTS - int(b.get("attempts") or 0)),
        "best_score": b.get("best"),
    }


def clean_build_answer(kind: str, answer) -> dict | None:
    """Only the fields this task type grades, as trimmed strings within BUILD_ANSWER_MAX; None if malformed."""
    if not isinstance(answer, dict):
        return None
    fields = {"code": ("code", "stdout"), "open_input": ("text",), "artifact_check": ("url",)}[kind]
    out = {}
    for f in fields:
        v = answer.get(f)
        if v is None:
            continue
        if not isinstance(v, str) or len(v) > BUILD_ANSWER_MAX[f]:
            return None
        out[f] = v.strip()
    return out


def grade_build(session_id, answer: dict) -> dict:
    """Grade a hand-in for the current build stage with the lesson graders (apps.learning.activities.grade: the
    fenced rubric grader for code and open_input, the SSRF-safe page check for artifact_check). An attempt is claimed
    under the session lock first, so parallel hand-ins can't pass BUILD_ATTEMPTS. The best score becomes the stage
    score. → {score, passed, feedback, reveal, best_score, attempts_left} or {"error": code}."""
    from types import SimpleNamespace

    from apps.learning.activities import grade

    with transaction.atomic():
        s = locked(session_id)
        if not s.started_at:
            return {"error": "not_started"}
        if s.status == WorkshopSession.Status.SUBMITTED:
            return {"error": "submitted"}
        st = stage(s) or {}
        task = build_task(st)
        if not task:
            return {"error": "not_build"}
        kind, payload, key = task
        answer = clean_build_answer(kind, answer)
        if answer is None:
            return {"error": "bad_answer"}
        if not any(answer.values()):
            return {"error": "empty"}
        cur = state(s)
        b = cur.setdefault("build", {"attempts": 0, "best": None, "last": None})
        if b["attempts"] >= BUILD_ATTEMPTS:
            return {"error": "no_attempts_left"}
        b["attempts"] += 1
        attempt, si = b["attempts"], s.stage_index
        s.save(update_fields=["stage_state"])
    if kind != "artifact_check" and (reason := spend(session_id, BUILD_MAX_TOKENS)):
        _refund_build_attempt(session_id, si)
        return {"error": reason}
    try:
        g = grade(SimpleNamespace(type=kind, key=key, payload=payload), answer, lang(s), user=s.user)
    except Exception:
        _refund_build_attempt(session_id, si)
        raise
    score = round(min(1.0, max(0.0, float(g.score))), 3)
    reveal = dict(g.reveal or {})
    if attempt < BUILD_ATTEMPTS:
        reveal.pop("model_solution", None)  # the reference solution only once no tries are left
    result = {"score": score, "passed": score >= PASS, "feedback": g.feedback, "reveal": reveal}
    with transaction.atomic():
        s = locked(session_id)
        cur = state(s, si)
        b = cur.setdefault("build", {"attempts": attempt, "best": None, "last": None})
        b["best"] = round(max(score, b.get("best") or 0.0), 3)
        b["last"] = {**result, "answer": answer}
        s.scores[st.get("key", str(si))] = b["best"]
        s.last_activity_at = now()
        s.save(update_fields=["stage_state", "scores", "last_activity_at"])
        WorkshopEvent.objects.create(
            session=s, type="build_graded", stage=si, data={"score": score, "attempt": attempt, "type": kind}
        )
        left = max(0, BUILD_ATTEMPTS - b["attempts"])
    return {**result, "best_score": b["best"], "attempts_left": left}


def _refund_build_attempt(session_id, si: int) -> None:
    with transaction.atomic():
        s = locked(session_id)
        b = state(s, si).get("build")
        if b and b.get("attempts"):
            b["attempts"] -= 1
            s.save(update_fields=["stage_state"])


# ── Help (screenshot / error) ────────────────────────────────────────


def help_reply(s, image, error_text: str, note_text: str) -> dict:
    """One AI call; the image lives only in this call's memory. Only the ≤200-char summary is stored."""
    from llm.prompts.curriculum import LANG_RULE
    from llm.prompts.workshop import HELP_SYSTEM, WorkshopHelp, help_user
    from llm.structured import complete_json_sync

    st = stage(s) if s.started_at else None
    step = ""
    if st and st.get("kind") in DIY_KINDS:
        texts = item_texts(st)
        i = state(s)["cursor"]
        step = texts[min(i, len(texts) - 1)] if texts else ""
    system = HELP_SYSTEM.format(lang_rule=LANG_RULE.get(lang(s), LANG_RULE["en"]))
    user = help_user(s.run.workshop.title, st, step, error_text, note_text)
    result = complete_json_sync(
        "vision" if image else "tutor",
        system,
        user,
        WorkshopHelp,
        max_tokens=HELP_MAX_TOKENS,
        images=[image] if image else None,
    )
    summary = " ".join(result.summary.split())[:200]
    event(s, "help_screenshot" if image else "help_error", summary=summary)
    return {"reply_md": result.reply_md.strip(), "summary": summary}


# ── Final assessment ─────────────────────────────────────────────────


def grade_final(s, answers: dict, practical: str) -> dict:
    """MCQs graded here (keys never leave the server); the practical with the fenced rubric grader (activities._ai).
    Up to FINAL_ATTEMPTS; the best score is kept; passing issues the Aasan certificate (idempotently)."""

    # Claim the attempt under the row lock first (like grade_build), so parallel hand-ins can't pass FINAL_ATTEMPTS
    # or use the MCQ grading as an answer oracle; the attempt is given back if grading fails.
    with transaction.atomic():
        claimed = locked(s.id)
        if claimed.passed or claimed.final_attempts >= FINAL_ATTEMPTS:
            return {"error": "no_attempts_left"}
        claimed.final_attempts += 1
        claimed.save(update_fields=["final_attempts"])
        attempt = claimed.final_attempts
    try:
        return _grade_final(s, answers, practical, attempt)
    except Exception:
        with transaction.atomic():
            back = locked(s.id)
            if back.final_attempts:
                back.final_attempts -= 1
                back.save(update_fields=["final_attempts"])
        raise


def _grade_final(s, answers: dict, practical: str, attempt: int) -> dict:
    from apps.learning.activities import _ai

    w = s.run.workshop
    f = w.final or {}
    mcqs = f.get("mcqs", [])
    correct = 0
    for qi, m in enumerate(mcqs):
        given = answers.get(str(qi), answers.get(qi))
        try:
            correct += int(given) == int(m["answer"])
        except (TypeError, ValueError):
            pass
    mcq_score = correct / len(mcqs) if mcqs else 1.0
    from .agent import grade_agent_tests

    agent_result = grade_agent_tests(s)  # the saved agent runs on the hidden tests first (Aasan tools only)
    prac = f.get("practical") or {}
    feedback = ""
    prac_score = 1.0
    if prac.get("prompt"):
        spend(s.id, 1500, exempt=True)  # recorded, but grading the final never pauses for budget
        g = _ai(
            {"text": practical},
            {"rubric": prac.get("rubric", []), "model_answer": prac.get("model_answer", "")},
            {"prompt": prac["prompt"]},
            lang(s),
        )
        prac_score, feedback = g.score, g.feedback
    wts = f.get("weights") or {"mcq": 0.6, "practical": 0.4}
    w_mcq = float(wts.get("mcq", 0.6))
    w_prac = float(wts.get("practical", 0.4)) if prac.get("prompt") else 0.0
    agent_score = agent_result[0] if agent_result else None
    w_agent = float(wts.get("agent", 0.3)) if agent_result else 0.0
    score = round(
        (mcq_score * w_mcq + prac_score * w_prac + (agent_score or 0.0) * w_agent)
        / ((w_mcq + w_prac + w_agent) or 1),
        3,
    )
    passed = score >= w.pass_mark
    with transaction.atomic():
        s = locked(s.id)
        s.final_score = max(score, s.final_score or 0.0)
        event(
            s,
            "final_attempt",
            score=score,
            mcq_correct=correct,
            mcq_total=len(mcqs),
            attempt=attempt,
            agent_score=agent_score,
        )
        if agent_result:  # the latest attempt's agent tests, so the result page survives a refresh
            s.agent = {**(s.agent or {}), "final_tests": {"score": agent_score, "tests": agent_result[1]}}
        newly_passed = passed and not s.passed
        if newly_passed:
            s.passed = True
        if s.passed and not s.certificate_id:
            from apps.credentials.services import issue

            cert, created = issue(
                s.user,
                "workshop",
                s.run,
                detail={"pct": round(s.final_score * 100), "minutes": w.duration_minutes},
            )
            s.certificate = cert
            if created:
                from apps.game.services import notify

                notify(s.user, "certificate", f"🎓 {cert.title}"[:160], "", "/certificates")
        if s.passed or s.final_attempts >= FINAL_ATTEMPTS:
            s.status = WorkshopSession.Status.SUBMITTED
            s.ended_at = s.ended_at or now()
        s.save()
        if newly_passed:
            from apps.integrations.hooks import on_workshop_passed

            on_workshop_passed(s.id)  # organisation runs: training record + webhook
    if s.status == WorkshopSession.Status.SUBMITTED:
        from .agent import wipe_secrets

        wipe_secrets(s.id)  # learner MCP tokens are deleted once the session is submitted
    mcq_line = f"You got {correct} of {len(mcqs)} multiple-choice questions right."
    return {
        "score": score,
        "best_score": s.final_score,
        "passed": s.passed,
        "feedback": f"{mcq_line} {feedback}".strip(),
        "mcq": {"correct": correct, "total": len(mcqs)},
        "practical_score": round(prac_score, 3),
        "attempts_left": 0 if s.passed else max(0, FINAL_ATTEMPTS - s.final_attempts),
        "certificate": certificate_out(s.certificate),
        **({"agent_score": agent_score, "agent_tests": agent_result[1]} if agent_result else {}),
    }
