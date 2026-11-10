"""Surveys v2 (P7): question builder (rating, scale, NPS, choice, multi-choice, text, matrix; required; reorder),
question banks with random draw, save-and-resume drafts, public link surveys (no login, rate-limited),
clone, AI survey writer, results for every type.

Surveys v3: sections, AI chat co-writer + draft-from-document, retakes (max attempts, cooldown, attempt history,
latest/all results) and a scored knowledge-test mode (correct answers + points, pass mark, optional review).
Correct answers (`correct` / `accepted`) never leave the server before the respondent submits: every respondent
payload goes through `respondent_questions`."""

import hashlib
import hmac
import random
from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from apps.game.services import notify

from .models import Group, Membership, QuestionBank, Survey, SurveyDraft, SurveyResponse
from .parse import flag, to_int
from .perms import require
from .templates_lib import SURVEY_TEMPLATES

QTYPES = {"rating", "scale", "nps", "choice", "multi", "text", "matrix"}
MAX_Q = 40
SCORABLE = {"choice", "multi", "text"}
ANSWER_KEYS = ("correct", "accepted")  # never sent to respondents before they submit


def _norm(v) -> str:
    """Lenient match for short-text answers: case, spacing and trailing punctuation don't matter."""
    return " ".join(str(v).casefold().split()).strip(" .!?")


def is_scored(q: dict) -> bool:
    return any(k in q for k in ANSWER_KEYS)


def respondent_questions(qs: list) -> list:
    """Questions as a respondent may see them: answer keys removed."""
    return [{k: v for k, v in q.items() if k not in ANSWER_KEYS} for q in qs]


def _scoring(q: dict, item: dict) -> bool:
    """Copy validated answer key + points from builder input into `item`. False if the key is malformed."""
    t = item["type"]
    c, acc = q.get("correct"), q.get("accepted")
    if t not in SCORABLE:
        return True
    if t == "choice" and c not in (None, "", []):
        if isinstance(c, list):
            c = c[0] if len(c) == 1 else None
        if c not in item["options"]:
            return False
        item["correct"] = c
    if t == "multi" and c not in (None, "", []):
        if not isinstance(c, list) or any(x not in item["options"] for x in c):
            return False
        item["correct"] = sorted(set(c), key=item["options"].index)
    if t == "text" and acc:
        if not isinstance(acc, list):
            return False
        a = list(dict.fromkeys(str(x).strip()[:100] for x in acc if str(x).strip()))[:20]
        if a:
            item["accepted"] = a
    if is_scored(item):
        try:
            pts = int(q.get("points") or 1)
        except (TypeError, ValueError):
            return False
        if not 1 <= pts <= 100:
            return False
        item["points"] = pts
    return True


def grade(q: dict, v) -> bool:
    if v is None:
        return False
    if q["type"] == "choice":
        return v == q.get("correct")
    if q["type"] == "multi":
        return isinstance(v, list) and set(v) == set(q.get("correct") or [])
    if q["type"] == "text":
        return isinstance(v, str) and _norm(v) in {_norm(a) for a in q.get("accepted") or []}
    return False


def score_answers(questions: list, answers: dict) -> tuple[float, float, list]:
    """(points earned, points possible, per-question review). All-or-nothing per question."""
    got = total = 0
    review = []
    for q in questions:
        if not is_scored(q):
            continue
        pts = q.get("points", 1)
        ok = grade(q, answers.get(q["id"]))
        total += pts
        got += pts if ok else 0
        review.append(
            {
                "id": q["id"],
                "text": q["text"],
                "type": q["type"],
                "points": pts,
                "earned": pts if ok else 0,
                "correct": ok,
                "your": answers.get(q["id"]),
                "answer": q.get("correct", q.get("accepted")),
            }
        )
    return got, total, review


def _first(user):
    from .api import _first as f

    return f(user)


def validate_questions(qs, prefix: str = "q") -> list | None:
    """Normalise builder output. Returns None if anything is invalid (the UI shows one clear error)."""
    if not isinstance(qs, list) or not 1 <= len(qs) <= MAX_Q:
        return None
    out = []
    for i, q in enumerate(qs):
        if not isinstance(q, dict) or q.get("type") not in QTYPES or not str(q.get("text", "")).strip():
            return None
        t = q["type"]
        item = {
            "id": str(q.get("id") or f"{prefix}{i + 1}")[:24],
            "type": t,
            "text": str(q["text"])[:300],
            "required": bool(q.get("required", False)),
        }
        if sec := str(q.get("section") or "").strip()[:80]:
            item["section"] = sec
        if t in ("choice", "multi", "matrix"):
            opts = [str(o)[:100] for o in (q.get("options") or []) if str(o).strip()]
            if len(opts) < 2 or len(set(opts)) != len(opts):
                return None
            item["options"] = opts[:10]
        if t == "matrix":
            rows = [str(r)[:100] for r in (q.get("rows") or []) if str(r).strip()]
            if not 1 <= len(rows) <= 10 or len(set(rows)) != len(rows):
                return None
            item["rows"] = rows
        if t == "scale":
            try:
                lo, hi = int(q.get("min", 1)), int(q.get("max", 10))
            except (TypeError, ValueError):
                return None
            if not (0 <= lo < hi <= 10):
                return None
            item.update(
                min=lo,
                max=hi,
                min_label=str(q.get("min_label") or "")[:40],
                max_label=str(q.get("max_label") or "")[:40],
            )
        if not _scoring(q, item):
            return None
        out.append(item)
    if len({q["id"] for q in out}) != len(out):
        return None
    return out


def clean_answer(q: dict, v):
    """Validated answer value, or raise ValueError."""
    t = q["type"]
    if t == "rating" and str(v).isdigit() and 1 <= int(v) <= 5:
        return int(v)
    if t == "nps" and str(v).isdigit() and 0 <= int(v) <= 10:
        return int(v)
    if t == "scale" and str(v).lstrip("-").isdigit() and q.get("min", 1) <= int(v) <= q.get("max", 10):
        return int(v)
    if t == "choice" and v in q["options"]:
        return v
    if t == "multi" and isinstance(v, list) and v and all(x in q["options"] for x in v):
        return sorted(set(v), key=q["options"].index)
    if t == "text" and isinstance(v, str):
        return v.strip()[:2000]
    if (
        t == "matrix"
        and isinstance(v, dict)
        and v
        and all(r in q["rows"] and c in q["options"] for r, c in v.items())
    ):
        return {r: v[r] for r in q["rows"] if r in v}
    raise ValueError(q["id"])


def _bank_questions(survey) -> list:
    d = survey.draw or {}
    if not d.get("bank"):
        return []
    bank = QuestionBank.objects.filter(pk=d["bank"], org_id=survey.org_id).first()
    return [{**q, "id": f"b{bank.id}_{q['id']}"} for q in (bank.questions if bank else [])]


def _questions_for(survey, key: str) -> tuple[list, list]:
    """(all questions to show, drawn bank questions). The draw is seeded by the respondent so a resume shows the same ones."""
    pool = _bank_questions(survey)
    n = min(int((survey.draw or {}).get("n") or 0), len(pool))
    drawn = random.Random(f"{survey.id}:{key}").sample(pool, n) if n else []
    return [*survey.questions, *drawn], drawn


def survey_out(s, with_meta=True) -> dict:
    out = {
        "id": s.id,
        "title": s.title,
        "description": s.description,
        "questions": s.questions,
        "anonymous": s.anonymous,
        "status": s.status,
        "group": {"id": s.group_id, "name": s.group.name} if s.group_id else None,
        "public": s.public,
        "draw": s.draw or {},
        "created_at": s.created_at,
        "kind": s.kind,
        "pass_mark": s.pass_mark,
        "show_review": s.show_review,
        "max_attempts": s.max_attempts,
        "cooldown_minutes": s.cooldown_minutes,
    }
    if with_meta:
        out["responses"] = s.responses.count()
        out["public_url"] = (
            f"{settings.FRONTEND_URL}/p/{s.public_token}" if s.public and s.kind != "test" else ""
        )
    return out


def _respondent_key(survey, user):
    return hmac.new(
        settings.SECRET_KEY.encode(), f"survey:{survey.id}:user:{user.id}".encode(), hashlib.sha256
    ).hexdigest()


def _public_key(survey, resume: str):
    return hmac.new(
        settings.SECRET_KEY.encode(), f"survey:{survey.id}:public:{resume}".encode(), hashlib.sha256
    ).hexdigest()


# ── Managers ─────────────────────────────────────────────────────────


@api_view(["GET"])
def survey_templates(request):
    return Response([{"key": k, **v} for k, v in SURVEY_TEMPLATES.items()])


def _draw_from(request, org):
    d = request.data.get("draw")
    if not d:
        return {}
    try:
        bank, n = int(d.get("bank")), int(d.get("n", 0))
    except (TypeError, ValueError, AttributeError):
        return None
    if not QuestionBank.objects.filter(pk=bank, org=org).exists() or not 0 <= n <= 20:
        return None
    return {"bank": bank, "n": n} if n else {}


SETTINGS_LIMITS = {"pass_mark": (0, 100), "max_attempts": (0, 20), "cooldown_minutes": (0, 60 * 24 * 30)}


def _apply_settings(s, data, frozen: bool) -> bool:
    """Test mode + retake settings. Retakes can change any time; the scoring rules only while the survey is a draft."""
    for k, (lo, hi) in SETTINGS_LIMITS.items():
        if k in data and not (frozen and k == "pass_mark"):
            try:
                v = int(data[k])
            except (TypeError, ValueError):
                return False
            if not lo <= v <= hi:
                return False
            setattr(s, k, v)
    if "show_review" in data:
        s.show_review = flag(data["show_review"])
    if "kind" in data and not frozen:
        if data["kind"] not in ("survey", "test"):
            return False
        s.kind = data["kind"]
    return True


def _valid_kind(s) -> bool:
    """Tests need at least one scored question, and can't be public links: a link respondent picks their own resume key,
    so attempt limits couldn't be enforced."""
    return s.kind != "test" or (any(is_scored(q) for q in s.questions) and not s.public)


@api_view(["GET", "POST"])
def surveys(request, slug):
    me = require(request.user, slug, "manager")
    if request.method == "GET":
        return Response([survey_out(s) for s in me.org.surveys.select_related("group")[:100]])
    tpl = SURVEY_TEMPLATES.get(request.data.get("template") or "")
    title = (request.data.get("title") or (tpl or {}).get("title") or "").strip()[:160]
    questions = validate_questions(request.data.get("questions") or (tpl or {}).get("questions"))
    draw = _draw_from(request, me.org)
    if not title or questions is None or draw is None:
        return Response({"code": "invalid_survey"}, status=status.HTTP_400_BAD_REQUEST)
    group = (
        get_object_or_404(Group, pk=to_int(request.data["group_id"]) or 0, org=me.org)
        if request.data.get("group_id")
        else None
    )
    s = Survey(
        org=me.org,
        group=group,
        title=title,
        description=(request.data.get("description") or (tpl or {}).get("description") or "")[:500],
        questions=questions,
        anonymous=flag(request.data.get("anonymous", True)),
        public=flag(request.data.get("public", False)),
        draw=draw,
        created_by=request.user,
    )
    if not _apply_settings(s, request.data, frozen=False) or not _valid_kind(s):
        return Response({"code": "invalid_survey"}, status=status.HTTP_400_BAD_REQUEST)
    s.save()
    return Response(survey_out(s), status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
def survey_detail(request, slug, pk):
    me = require(request.user, slug, "manager")
    s = get_object_or_404(Survey, pk=pk, org=me.org)
    if request.method == "DELETE":
        s.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    if (st := request.data.get("status")) in ("open", "closed", "draft"):
        if st == "open" and s.status == "draft":
            targets = Membership.objects.filter(org=me.org, role="learner")
            if s.group_id:
                targets = targets.filter(groups=s.group)
            for m in targets.select_related("user"):
                notify(m.user, "survey", f"📝 {s.title}"[:160], s.description[:300], "/surveys")
        s.status = st
    if "public" in request.data:
        s.public = flag(request.data["public"])
    if not _apply_settings(s, request.data, frozen=s.status != "draft"):
        return Response({"code": "invalid_survey"}, status=status.HTTP_400_BAD_REQUEST)
    if s.status == "draft":  # questions freeze once responses can arrive
        for k in ("title", "description"):
            if k in request.data:
                setattr(s, k, str(request.data[k])[: 160 if k == "title" else 500])
        if "anonymous" in request.data:
            s.anonymous = flag(request.data["anonymous"])
        if "questions" in request.data:
            q = validate_questions(request.data["questions"])
            if q is None:
                return Response({"code": "invalid_survey"}, status=status.HTTP_400_BAD_REQUEST)
            s.questions = q
        if "draw" in request.data:
            d = _draw_from(request, me.org)
            if d is None:
                return Response({"code": "invalid_survey"}, status=status.HTTP_400_BAD_REQUEST)
            s.draw = d
    if s.kind == "test" and s.public and not flag(request.data.get("public")):
        s.public = (
            False  # a test saved as public before links were refused for tests: quietly turn the link off
        )
    if not _valid_kind(s):
        return Response({"code": "invalid_survey"}, status=status.HTTP_400_BAD_REQUEST)
    s.save()
    return Response(survey_out(s))


@api_view(["POST"])
def survey_clone(request, slug, pk):
    me = require(request.user, slug, "manager")
    s = get_object_or_404(Survey, pk=pk, org=me.org)
    c = Survey.objects.create(
        org=me.org,
        group=s.group,
        title=f"{s.title} (copy)"[:160],
        description=s.description,
        questions=s.questions,
        anonymous=s.anonymous,
        public=False,
        draw=s.draw,
        created_by=request.user,
        kind=s.kind,
        pass_mark=s.pass_mark,
        show_review=s.show_review,
        max_attempts=s.max_attempts,
        cooldown_minutes=s.cooldown_minutes,
    )
    return Response(survey_out(c), status=status.HTTP_201_CREATED)


@api_view(["GET", "POST"])
def question_banks(request, slug):
    me = require(request.user, slug, "manager")
    if request.method == "POST":
        name = str(request.data.get("name") or "").strip()[:120]
        qs = validate_questions(request.data.get("questions"))
        if not name or qs is None:
            return Response({"code": "invalid_bank"}, status=status.HTTP_400_BAD_REQUEST)
        b = QuestionBank.objects.create(org=me.org, name=name, questions=qs)
        return Response(
            {"id": b.id, "name": b.name, "questions": b.questions}, status=status.HTTP_201_CREATED
        )
    return Response(
        [
            {"id": b.id, "name": b.name, "questions": b.questions}
            for b in me.org.question_banks.order_by("name")
        ]
    )


@api_view(["PATCH", "DELETE"])
def question_bank_detail(request, slug, pk):
    me = require(request.user, slug, "manager")
    b = get_object_or_404(QuestionBank, pk=pk, org=me.org)
    if request.method == "DELETE":
        b.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    if "name" in request.data:
        b.name = str(request.data["name"]).strip()[:120] or b.name
    if "questions" in request.data:
        qs = validate_questions(request.data["questions"])
        if qs is None:
            return Response({"code": "invalid_bank"}, status=status.HTTP_400_BAD_REQUEST)
        b.questions = qs
    b.save()
    return Response({"id": b.id, "name": b.name, "questions": b.questions})


AI_SYSTEM = """[[TASK:survey_writer]]
Write a short, clear survey for an Indian school, college or company. Use simple words. 4–10 questions.
Allowed types: rating (1-5 stars), scale (min..max with end labels), nps (0-10), choice, multi, text, matrix (rows × options).
Mix types sensibly; end with one optional open text question. Mark key questions required. Never ask for personal data
(phone, address, caste, religion, health) unless the teacher explicitly needs it. {lang_rule}"""


@api_view(["POST"])
def survey_ai_draft(request, slug):
    """'Create a survey about…' → an editable draft (not saved until the manager saves it)."""
    from pydantic import BaseModel

    from apps.learning.services import content_language
    from llm.base import LLMError
    from llm.prompts.curriculum import LANG_RULE
    from llm.structured import complete_json_sync

    require(request.user, slug, "manager")
    prompt = str(request.data.get("prompt") or "").strip()
    if not 5 <= len(prompt) <= 600:
        return Response({"code": "bad_prompt"}, status=status.HTTP_400_BAD_REQUEST)
    from apps.providers.services import BudgetExceeded, charge

    try:
        charge(request.user, "ai_grades", 1, 200, max_tokens=3000)
    except BudgetExceeded:
        return Response({"code": "ai_budget_exceeded"}, status=status.HTTP_429_TOO_MANY_REQUESTS)

    class Q(BaseModel):
        type: str
        text: str
        required: bool
        options: list[str]
        rows: list[str]
        min: int
        max: int
        min_label: str
        max_label: str

    class Draft(BaseModel):
        title: str
        description: str
        questions: list[Q]

    try:
        out = complete_json_sync(
            "suggest",
            AI_SYSTEM.format(lang_rule=LANG_RULE[content_language(request.user)]),
            f"The teacher wants: {prompt}",
            Draft,
            max_tokens=3000,
        )
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    qs = []
    for q in out.questions:  # drop anything malformed instead of failing the whole draft
        d = {k: v for k, v in q.model_dump().items() if v not in ("", [], None)}
        if q.type == "scale":
            d.update(min=q.min, max=q.max)
        one = validate_questions([d])
        if one:
            qs.append(one[0])
    for i, q in enumerate(qs):
        q["id"] = f"q{i + 1}"
    if not qs:
        return Response({"code": "generation_invalid"}, status=status.HTTP_502_BAD_GATEWAY)
    return Response({"title": out.title[:160], "description": out.description[:500], "questions": qs})


# ── Surveys v3: Kili chat co-writer + draft from a document ──────────


def ai_question(raw: dict, qid: str, scored: bool) -> dict | None:
    """One AI-proposed question → a validated question (or None). Answer keys are kept only for tests."""
    d = {k: v for k, v in raw.items() if v not in ("", [], None, 0) or k in ("min",)}
    d["id"] = qid
    if raw.get("type") == "scale":
        d.update(min=raw.get("min") or 1, max=raw.get("max") or 5)
    if raw.get("type") == "choice" and isinstance(d.get("correct"), list):
        d["correct"] = d["correct"][0] if len(d["correct"]) == 1 else None
    if not scored:
        for k in (*ANSWER_KEYS, "points"):
            d.pop(k, None)
    one = validate_questions([d])
    if not one and any(k in d for k in ANSWER_KEYS):  # a broken answer key: keep the question, unscored
        one = validate_questions([{k: v for k, v in d.items() if k not in (*ANSWER_KEYS, "points")}])
    return one[0] if one else None


def _ai_guard(request, max_tokens: int | None = None):
    from apps.providers.services import BudgetExceeded, charge

    try:
        charge(request.user, "ai_grades", 1, 200, max_tokens=max_tokens)
    except BudgetExceeded:
        return Response({"code": "ai_budget_exceeded"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    return None


def _fresh_id(taken: set) -> str:
    n = len(taken) + 1
    while f"q{n}" in taken:
        n += 1
    taken.add(f"q{n}")
    return f"q{n}"


def chat_changes(raw_changes: list, draft_ids: list, scored: bool) -> list:
    """Validate Kili's proposed edits against the current draft; malformed ones are dropped, never half-applied.
    Nothing is saved here: the builder applies a change only when the manager accepts it, then saves the draft."""
    taken, known, out = set(draft_ids), set(draft_ids), []
    for c in raw_changes[:15]:
        op, summary = c.get("op"), str(c.get("summary") or "").strip()[:200]
        item = {"id": f"c{len(out) + 1}", "op": op, "summary": summary}
        if op in ("title", "description"):
            text = str(c.get("text") or "").strip()[: 160 if op == "title" else 500]
            if not text:
                continue
            item["text"] = text
        elif op == "remove":
            if c.get("target") not in draft_ids:
                continue
            item["target"] = c["target"]
        elif op == "update":
            if c.get("target") not in draft_ids or not (
                q := ai_question(c.get("question") or {}, c["target"], scored)
            ):
                continue
            item.update(target=c["target"], question=q)
        elif op == "add":
            after = str(c.get("after") or "")
            if after and after not in known:
                after = ""
            if not (q := ai_question(c.get("question") or {}, _fresh_id(taken), scored)):
                continue
            known.add(q["id"])
            item.update(after=after, question=q)
        else:
            continue
        item["summary"] = summary or op
        out.append(item)
    return out


def _lang_rule(user):
    from apps.learning.services import content_language
    from llm.prompts.curriculum import LANG_RULE

    return LANG_RULE.get(content_language(user), LANG_RULE["en"])


@api_view(["POST"])
def survey_ai_chat(request, slug):
    """Multi-turn 'Kili, help me write this survey': returns a reply + proposed edits (accept/reject per change in the
    builder). Stateless and read-only — the draft changes only when the manager accepts and saves."""
    import json

    from llm.base import LLMError
    from llm.prompts.credentials import QUESTION_RULES, SURVEY_CHAT_SYSTEM, SurveyChatOut
    from llm.structured import complete_json_sync

    require(request.user, slug, "manager")
    msgs = request.data.get("messages")
    draft = request.data.get("draft") or {}
    if not isinstance(msgs, list) or not 1 <= len(msgs) <= 30 or not isinstance(draft, dict):
        return Response({"code": "bad_chat"}, status=status.HTTP_400_BAD_REQUEST)
    convo = []
    for m in msgs[-12:]:
        if (
            not isinstance(m, dict)
            or m.get("role") not in ("user", "assistant")
            or not isinstance(m.get("content"), str)
        ):
            return Response({"code": "bad_chat"}, status=status.HTTP_400_BAD_REQUEST)
        convo.append(f"{'Manager' if m['role'] == 'user' else 'Kili'}: {m['content'].strip()[:1500]}")
    if msgs[-1].get("role") != "user" or len(msgs[-1]["content"].strip()) < 2:
        return Response({"code": "bad_chat"}, status=status.HTTP_400_BAD_REQUEST)
    kind = "test" if draft.get("kind") == "test" else "survey"
    qs = (
        [q for q in (draft.get("questions") or []) if isinstance(q, dict)][:MAX_Q]
        if isinstance(draft.get("questions"), list)
        else []
    )
    ids = [str(q.get("id")) for q in qs if q.get("id")]
    if denied := _ai_guard(request, max_tokens=4000):
        return denied
    current = {
        "title": str(draft.get("title") or "")[:160],
        "description": str(draft.get("description") or "")[:500],
        "kind": kind,
        "questions": [
            {
                k: q.get(k)
                for k in (
                    "id",
                    "type",
                    "text",
                    "section",
                    "required",
                    "options",
                    "rows",
                    "min",
                    "max",
                    "min_label",
                    "max_label",
                    "correct",
                    "accepted",
                    "points",
                )
                if q.get(k) not in (None, "", [])
            }
            for q in qs
        ],
    }
    system = SURVEY_CHAT_SYSTEM.format(
        kind="scored knowledge test" if kind == "test" else "survey",
        rules=QUESTION_RULES,
        lang_rule=_lang_rule(request.user),
    )
    from apps.accounts.companion import as_companion

    system = as_companion(system, request.user)
    user = (
        f"<draft>\n{json.dumps(current, ensure_ascii=False)[:12000]}\n</draft>\n<chat>\n"
        + "\n".join(convo)
        + "\n</chat>"
    )
    try:
        out = complete_json_sync("suggest", system, user, SurveyChatOut, max_tokens=4000)
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    changes = chat_changes([c.model_dump() for c in out.changes], ids, scored=kind == "test")
    return Response({"reply": out.reply.strip()[:2000], "changes": changes})


@api_view(["GET", "POST"])
def survey_ai_doc(request, slug):
    """GET: documents the manager can use (own + shared in their orgs). POST {document_id, kind, focus?}: Kili drafts a
    survey or a knowledge test from that document (an editable draft; nothing is saved)."""
    from llm.base import LLMError
    from llm.prompts.credentials import QUESTION_RULES, SURVEY_DOC_SYSTEM, SurveyDraftOut
    from llm.structured import complete_json_sync

    from .extras import viewable_documents

    require(request.user, slug, "manager")
    docs = viewable_documents(request.user)
    if request.method == "GET":
        return Response(
            [{"id": d.id, "title": d.title, "pages": d.pages} for d in docs.order_by("-created_at")[:100]]
        )
    try:
        doc = docs.filter(pk=int(request.data.get("document_id"))).first()
    except (TypeError, ValueError):
        doc = None
    if not doc:
        return Response(status=status.HTTP_404_NOT_FOUND)
    kind = "test" if request.data.get("kind") == "test" else "survey"
    focus = str(request.data.get("focus") or "").strip()[:300]
    text, used = [], 0
    for ch in doc.chunks.order_by("index").values_list("text", flat=True):
        if used >= 14000:
            break
        text.append(ch[: 14000 - used])
        used += len(text[-1])
    if not used:
        return Response({"code": "empty_document"}, status=status.HTTP_400_BAD_REQUEST)
    if denied := _ai_guard(request, max_tokens=5000):
        return denied
    goal = (
        "Test understanding of the key facts and ideas: 6-12 scored questions with answer keys (choice, multi, short text)."
        if kind == "test"
        else "Ask learners how well they understood and liked the material, and what was unclear: 5-10 questions."
    )
    if focus:
        goal += f" The manager's focus (untrusted text): <focus>{focus}</focus>"
    system = SURVEY_DOC_SYSTEM.format(
        kind="scored knowledge test" if kind == "test" else "survey",
        goal=goal,
        rules=QUESTION_RULES,
        lang_rule=_lang_rule(request.user),
    )
    try:
        out = complete_json_sync(
            "suggest",
            system,
            f'<document title="{doc.title[:120]}">\n{"".join(text)}\n</document>',
            SurveyDraftOut,
            max_tokens=5000,
        )
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    taken: set = set()
    qs = [
        q
        for raw in out.questions[:MAX_Q]
        if (q := ai_question(raw.model_dump(), _fresh_id(taken), kind == "test"))
    ]
    for i, q in enumerate(qs):
        q["id"] = f"q{i + 1}"
    if not qs or (kind == "test" and not any(is_scored(q) for q in qs)):
        return Response({"code": "generation_invalid"}, status=status.HTTP_502_BAD_GATEWAY)
    return Response(
        {
            "title": out.title.strip()[:160] or doc.title[:160],
            "description": out.description.strip()[:500],
            "kind": kind,
            "questions": qs,
        }
    )


# ── Respondents (members) ────────────────────────────────────────────


def _member_survey(request, pk):
    ms = Membership.objects.filter(user=request.user)
    return (
        Survey.objects.filter(pk=pk, status="open", org__memberships__in=ms)
        .filter(Q(group__isnull=True) | Q(group__members__in=ms))
        .distinct()
        .first()
    )


def _attempts(s, key) -> list:
    return list(SurveyResponse.objects.filter(survey=s, respondent_key=key).order_by("attempt"))


def retake_state(s, attempts: list, now=None) -> dict:
    """Can this respondent (re)submit now? {can, retake_at, attempts_left}."""
    if not attempts:
        return {"can": True, "retake_at": None, "attempts_left": s.max_attempts or None}
    left = (s.max_attempts - len(attempts)) if s.max_attempts else None
    if left is not None and left <= 0:
        return {"can": False, "retake_at": None, "attempts_left": 0}
    at = attempts[-1].submitted_at + timedelta(minutes=s.cooldown_minutes)
    if s.cooldown_minutes and (now or timezone.now()) < at:
        return {"can": False, "retake_at": at, "attempts_left": left}
    return {"can": True, "retake_at": None, "attempts_left": left}


def reveal_answers(s, r, n_attempts: int) -> bool:
    """Correct answers may be shown only once they can't help a later attempt: the respondent passed, or has no
    attempts left. (Unlimited attempts → only after passing.)"""
    return bool(r.passed) or bool(s.max_attempts and n_attempts >= s.max_attempts)


def _result(s, r, questions, n_attempts: int) -> dict | None:
    """What the respondent sees after submitting a test: score, pass/fail and — only if the manager allows — the review.
    Before answers may be revealed, the review says right/wrong per question only (bank questions included), and not
    even that when retakes are unlimited and immediate (score only)."""
    if s.kind != "test" or r.max_score is None:
        return None
    out = {
        "attempt": r.attempt,
        "score": r.score,
        "max_score": r.max_score,
        "pct": _pct(r),
        "passed": r.passed,
        "pass_mark": s.pass_mark,
    }
    if s.show_review:
        revealed = reveal_answers(s, r, n_attempts)
        out["answers_revealed"] = revealed
        if not revealed and not s.max_attempts and not s.cooldown_minutes:
            # Unlimited instant retakes + per-question right/wrong = brute-forcing the key one question at a time.
            return out
        review = score_answers(questions, r.answers)[2]
        if not revealed:
            for item in review:
                item.pop("answer", None)
        out["review"] = review
    return out


def _pct(r) -> int | None:
    return None if not r.max_score else round(100 * (r.score or 0) / r.max_score)


def _history(attempts) -> list:
    return [
        {"attempt": a.attempt, "submitted_at": a.submitted_at, "pct": _pct(a), "passed": a.passed}
        for a in attempts
    ]


def _respondent_view(s, key) -> dict:
    """Everything a respondent may see about their own progress on a survey (no answer keys before submitting)."""
    questions, _ = _questions_for(s, key)
    attempts = _attempts(s, key)
    state = retake_state(s, attempts)
    draft = SurveyDraft.objects.filter(survey=s, respondent_key=key).first()
    return {
        "questions": respondent_questions(questions),
        "answered": bool(attempts),
        "attempts": _history(attempts),
        "can_retake": bool(attempts) and state["can"],
        "retake_at": state["retake_at"],
        "attempts_left": state["attempts_left"],
        "last_result": _result(s, attempts[-1], questions, len(attempts)) if attempts else None,
        "draft": draft.answers if draft and state["can"] else {},
    }


@api_view(["GET"])
def my_surveys(request):
    ms = Membership.objects.filter(user=request.user)
    qs = (
        Survey.objects.filter(org__memberships__in=ms, status="open")
        .filter(Q(group__isnull=True) | Q(group__members__in=ms))
        .select_related("org")
        .distinct()
    )
    out = []
    for s in qs:
        key = _respondent_key(s, request.user)
        out.append({**survey_out(s, with_meta=False), **_respondent_view(s, key), "org": s.org.name})
    return Response(out)


def _clean_all(questions, raw, partial: bool):
    answers = {}
    for q in questions:
        v = (raw or {}).get(q["id"])
        if v in (None, "", [], {}):
            if q.get("required") and not partial:
                raise ValueError(f"required:{q['id']}")
            continue
        answers[q["id"]] = clean_answer(q, v)
    return answers


def _closed_response(state):
    if state["retake_at"]:
        return Response(
            {"code": "cooldown", "retake_at": state["retake_at"]}, status=status.HTTP_409_CONFLICT
        )
    return Response({"code": "already_answered"}, status=status.HTTP_409_CONFLICT)


def _submit(s, key, user, raw):
    questions, _ = _questions_for(s, key)
    try:
        answers = _clean_all(questions, raw, partial=False)
    except ValueError as e:
        code, _, qid = str(e).partition(":")
        return Response(
            {"code": "required" if code == "required" else "invalid_answer", "question": qid or code},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not answers:
        return Response({"code": "empty"}, status=status.HTTP_400_BAD_REQUEST)
    attempts = _attempts(s, key)
    state = retake_state(s, attempts)
    if not state["can"]:
        return _closed_response(state)
    scored = {}
    if s.kind == "test":
        got, total, _ = score_answers(questions, answers)
        scored = {
            "score": got,
            "max_score": total,
            "passed": bool(total) and 100 * got / total >= s.pass_mark,
        }
    try:
        with transaction.atomic():  # savepoint: a duplicate must not poison the outer transaction
            r = SurveyResponse.objects.create(
                survey=s,
                respondent_key=key,
                user=None if s.anonymous else user,
                answers=answers,
                attempt=len(attempts) + 1,
                **scored,
            )
            SurveyDraft.objects.filter(survey=s, respondent_key=key).delete()
    except IntegrityError:
        return Response({"code": "already_answered"}, status=status.HTTP_409_CONFLICT)
    if r.passed and r.user_id:
        from apps.integrations.hooks import on_test_passed

        on_test_passed(r.id)  # knowledge test passed: training record
    after = retake_state(s, [*attempts, r])
    return Response(
        {
            "ok": True,
            "attempt": r.attempt,
            "result": _result(s, r, questions, r.attempt),
            "can_retake": after["can"],
            "retake_at": after["retake_at"],
            "attempts_left": after["attempts_left"],
        },
        status=status.HTTP_201_CREATED,
    )


def _save_draft(s, key, raw):
    questions, drawn = _questions_for(s, key)
    try:
        answers = _clean_all(questions, raw, partial=True)
    except ValueError as e:
        return Response({"code": "invalid_answer", "question": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    if not (state := retake_state(s, _attempts(s, key)))["can"]:
        return _closed_response(state)
    SurveyDraft.objects.update_or_create(
        survey=s,
        respondent_key=key,
        defaults={"answers": answers, "extra": drawn, "asked": [q["id"] for q in questions]},
    )
    return Response({"saved": True, "answers": answers})


@api_view(["POST"])
def respond(request, pk):
    s = _member_survey(request, pk)
    if not s:
        return Response(status=status.HTTP_404_NOT_FOUND)
    return _submit(s, _respondent_key(s, request.user), request.user, request.data.get("answers"))


@api_view(["PUT"])
def save_draft(request, pk):
    s = _member_survey(request, pk)
    if not s:
        return Response(status=status.HTTP_404_NOT_FOUND)
    return _save_draft(s, _respondent_key(s, request.user), request.data.get("answers"))


# ── Public link surveys (no login) ───────────────────────────────────


class PublicSurveyThrottle(AnonRateThrottle):
    rate = "60/hour"


def _public(token) -> Survey:
    # Tests are never answerable by link (older ones saved as public are treated as not public).
    return get_object_or_404(
        Survey.objects.select_related("org").exclude(kind="test"),
        public_token=token,
        public=True,
        status="open",
    )


def _resume(request) -> str | None:
    r = str(request.query_params.get("r") or request.data.get("resume") or "")
    return r if 16 <= len(r) <= 64 and r.replace("-", "").isalnum() else None


@api_view(["GET", "PUT", "POST"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
@throttle_classes([PublicSurveyThrottle])
def public_survey(request, token):
    """GET ?r=<resume key> → survey + saved draft · PUT → save draft · POST → submit. The resume key is a random
    id the browser keeps; we store only an HMAC of it, so answers aren't linkable to the person."""
    s = _public(token)
    r = _resume(request)
    if not r:
        return Response({"code": "resume_key_required"}, status=status.HTTP_400_BAD_REQUEST)
    key = _public_key(s, r)
    if request.method == "PUT":
        return _save_draft(s, key, request.data.get("answers"))
    if request.method == "POST":
        return _submit(s, key, None, request.data.get("answers"))
    org = s.org
    return Response(
        {
            "title": s.title,
            "description": s.description,
            "org": org.display_name or org.name,
            "kind": s.kind,
            "pass_mark": s.pass_mark,
            "brand_color": org.brand_color,
            "logo_url": org.logo_url,
            **_respondent_view(s, key),
        }
    )


# ── Results ──────────────────────────────────────────────────────────


def all_questions(s) -> list:
    """Survey questions + any bank questions that appear in responses (for results/exports)."""
    bank = {q["id"]: q for q in _bank_questions(s)}
    seen = set()
    for r in s.responses.all():
        seen |= set(r.answers) & set(bank)
    return [*s.questions, *(bank[i] for i in bank if i in seen)]


def responses_for(s, scope: str = "latest") -> list:
    """Every attempt (`all`) or each respondent's latest attempt (default)."""
    rs = list(s.responses.select_related("user__profile").order_by("respondent_key", "attempt", "id"))
    if scope == "all":
        return sorted(rs, key=lambda r: (r.submitted_at, r.id))
    latest = {}
    for r in rs:
        latest[r.respondent_key] = r
    return sorted(latest.values(), key=lambda r: (r.submitted_at, r.id))


def results(s, scope: str = "latest"):
    from .api import _first as first

    resps = responses_for(s, scope)
    main = {q["id"] for q in s.questions}
    out = []
    for q in all_questions(s):
        vals = [r.answers.get(q["id"]) for r in resps if q["id"] in r.answers]
        item = {"id": q["id"], "type": q["type"], "text": q["text"], "count": len(vals)}
        if q.get("section"):
            item["section"] = q["section"]
        t = q["type"]
        if t in ("rating", "nps", "scale"):
            item["avg"] = round(sum(vals) / len(vals), 2) if vals else None
            item["distribution"] = Counter(vals)
            if t == "nps" and vals:
                promoters = sum(1 for v in vals if v >= 9)
                detractors = sum(1 for v in vals if v <= 6)
                item["nps"] = round(100 * (promoters - detractors) / len(vals))
            if t == "scale":
                item.update(min=q.get("min", 1), max=q.get("max", 10))
        elif t in ("choice", "multi"):
            c = Counter(x for v in vals for x in (v if isinstance(v, list) else [v]))
            item["options"] = [{"option": o, "count": c.get(o, 0)} for o in q["options"]]
        elif t == "matrix":
            item["rows"] = [
                {
                    "row": row,
                    "options": [
                        {
                            "option": o,
                            "count": sum(1 for v in vals if isinstance(v, dict) and v.get(row) == o),
                        }
                        for o in q["options"]
                    ],
                }
                for row in q["rows"]
            ]
        else:
            item["answers"] = [
                {"text": v, "name": None if s.anonymous or not r.user else first(r.user)}
                for r in resps
                if (v := r.answers.get(q["id"]))
            ][:200]
        if s.kind == "test" and is_scored(q):
            asked = [
                r for r in resps if q["id"] in main or q["id"] in r.answers
            ]  # drawn bank questions: only who got them
            right = sum(1 for r in asked if grade(q, r.answers.get(q["id"])))
            item.update(
                scored=True,
                points=q.get("points", 1),
                correct=q.get("correct", q.get("accepted")),
                correct_rate=round(right / len(asked), 3) if asked else None,
            )
        out.append(item)
    return out, len(resps)


def score_stats(s, scope: str = "latest") -> dict | None:
    """Score distribution (10-point buckets), average, pass rate and the hardest questions first."""
    if s.kind != "test":
        return None
    resps = [r for r in responses_for(s, scope) if r.max_score]
    pcts = [_pct(r) for r in resps]
    buckets = [0] * 10
    for p in pcts:
        buckets[min(p // 10, 9)] += 1
    return {
        "n": len(pcts),
        "avg_pct": round(sum(pcts) / len(pcts), 1) if pcts else None,
        "pass_rate": round(sum(1 for r in resps if r.passed) / len(resps), 3) if resps else None,
        "pass_mark": s.pass_mark,
        "distribution": [
            {"label": f"{i * 10}–{i * 10 + 9 if i < 9 else 100}", "count": c} for i, c in enumerate(buckets)
        ],
    }


def flat_answer(v) -> str:
    if isinstance(v, list):
        return ", ".join(map(str, v))
    if isinstance(v, dict):
        return "; ".join(f"{k}: {x}" for k, x in v.items())
    return "" if v is None else str(v)
