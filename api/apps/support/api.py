"""Help centre: articles + search, 'Ask Help' (answers only from articles, with citations), problem reports + admin inbox."""

import math
import re
from collections import Counter

from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from apps.accounts.staff import AdminSection
from apps.legal.mail import EMAIL_NOT_CONFIGURED, mail_ready

from .models import HelpArticle, ProblemReport

WORD = re.compile(r"[\w஀-௿]+", re.UNICODE)


def _tokens(s: str) -> list[str]:
    return [w.lower() for w in WORD.findall(s or "") if len(w) > 1]


def search(q: str, k: int = 5) -> list[tuple[HelpArticle, float]]:
    """Small BM25 over title (weighted) + body, both languages — the help centre has tens of articles, not millions."""
    arts = list(HelpArticle.objects.filter(published=True))
    if not arts:
        return []
    docs = [
        _tokens(f"{a.title} {a.title} {a.title_ta} {a.title_ta} {a.body_md} {a.body_ta_md}") for a in arts
    ]
    avg = sum(map(len, docs)) / len(docs)
    df = Counter(w for d in docs for w in set(d))
    qs = _tokens(q)
    scored = []
    for a, d in zip(arts, docs, strict=True):
        tf = Counter(d)
        s = sum(
            math.log(1 + (len(docs) - df[w] + 0.5) / (df[w] + 0.5))
            * tf[w]
            * 2.2
            / (tf[w] + 1.2 * (0.25 + 0.75 * len(d) / avg))
            for w in qs
            if w in tf
        )
        if s > 0:
            scored.append((a, s))
    return sorted(scored, key=lambda x: -x[1])[:k]


def _out(a: HelpArticle, full=False) -> dict:
    o = {"slug": a.slug, "category": a.category, "title": a.title, "title_ta": a.title_ta}
    if full:
        o.update(body_md=a.body_md, body_ta_md=a.body_ta_md, updated_at=a.updated_at)
    return o


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def articles(request):
    q = (request.query_params.get("q") or "").strip()[:200]
    if q:
        return Response([_out(a) for a, _ in search(q, 8)])
    return Response([_out(a) for a in HelpArticle.objects.filter(published=True)])


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def article(request, slug):
    return Response(_out(get_object_or_404(HelpArticle, slug=slug, published=True), full=True))


class AskThrottle(UserRateThrottle):
    rate = "30/hour"


ASK_SYSTEM = """[[TASK:ask_help]]
You are Aasan's help desk. Answer ONLY from the help articles given below. If they don't cover the question, say so
in one sentence and suggest using "Report a problem". Keep it short (max ~120 words), friendly and step-by-step.
Cite the articles you used by their slug in `sources`. Never invent features, prices or policies. {lang_rule}"""


@api_view(["POST"])
@throttle_classes([AskThrottle])
def ask(request):
    from pydantic import BaseModel

    from apps.learning.services import content_language
    from llm.base import LLMError
    from llm.prompts.curriculum import LANG_RULE
    from llm.structured import complete_json_sync

    q = str(request.data.get("question") or "").strip()
    if not 3 <= len(q) <= 500:
        return Response({"code": "bad_question"}, status=status.HTTP_400_BAD_REQUEST)
    hits = search(q, 4)
    if not hits:
        return Response({"answer": "", "sources": [], "found": False})
    lang = content_language(request.user)
    ctx = "\n\n".join(
        f"[{a.slug}] {a.title}\n{a.body_ta_md if lang == 'ta' and a.body_ta_md else a.body_md}"
        for a, _ in hits
    )

    class Out(BaseModel):
        answer: str
        sources: list[str]
        covered: bool

    from apps.providers.services import BudgetExceeded, charge

    try:  # same daily AI budget as the other AI helpers, on top of the hourly throttle
        charge(request.user, "ai_grades", 1, 200, max_tokens=800)
    except BudgetExceeded:
        return Response({"code": "ai_budget_exceeded"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    try:
        out = complete_json_sync(
            "suggest",
            ASK_SYSTEM.format(lang_rule=LANG_RULE.get(lang, LANG_RULE["en"])),
            f"HELP ARTICLES:\n{ctx}\n\nQUESTION: {q}",
            Out,
            max_tokens=800,
        )
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    known = {a.slug: a for a, _ in hits}
    sources = [
        _out(known[s]) for s in dict.fromkeys(out.sources) if s in known
    ]  # only real articles can be cited
    return Response({"answer": out.answer.strip(), "sources": sources, "found": out.covered})


# ── Problem reports ──────────────────────────────────────────────────


class ReportIn(serializers.Serializer):
    category = serializers.ChoiceField(choices=ProblemReport.CATEGORIES, default="bug")
    text = serializers.CharField(min_length=5, max_length=4000)
    page = serializers.CharField(max_length=300, required=False, allow_blank=True)
    ref = serializers.RegexField(r"^[a-z_]+:[a-z_]+:\d+$|^$", max_length=60, required=False)
    screenshot = serializers.CharField(max_length=300, required=False, allow_blank=True)
    browser = serializers.CharField(max_length=300, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)

    def validate_screenshot(self, v):
        if v and not re.fullmatch(re.escape(settings.MEDIA_URL) + r"[\w/\-]+\.(png|jpe?g|webp)", v):
            raise serializers.ValidationError("upload_first")
        return v


class ReportThrottle(UserRateThrottle):
    rate = "10/hour"


def _report_out(r: ProblemReport, admin=False) -> dict:
    o = {
        "id": r.id,
        "category": r.category,
        "text": r.text,
        "page": r.page,
        "status": r.status,
        "reply": r.reply,
        "replied_at": r.replied_at,
        "created_at": r.created_at,
        "screenshot": r.screenshot,
    }
    if admin:
        o.update(
            ref=r.ref,
            browser=r.browser,
            email=r.email or (r.user.email if r.user_id else ""),
            user=r.user.email if r.user_id else None,
            updated_at=r.updated_at,
        )
    return o


@api_view(["GET", "POST"])
@throttle_classes([ReportThrottle])
def reports(request):
    if request.method == "GET":
        return Response([_report_out(r) for r in ProblemReport.objects.filter(user=request.user)[:50]])
    ser = ReportIn(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    r = ProblemReport.objects.create(
        user=request.user,
        email=d.get("email") or request.user.email,
        **{k: v for k, v in d.items() if k != "email"},
    )
    return Response(_report_out(r), status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([AdminSection])
def admin_reports(request):
    qs = ProblemReport.objects.select_related("user")
    if st := request.query_params.get("status"):
        qs = qs.filter(status=st)
    if cat := request.query_params.get("category"):
        qs = qs.filter(category=cat)
    counts = {s: ProblemReport.objects.filter(status=s).count() for s, _ in ProblemReport.Status.choices}
    return Response({"counts": counts, "rows": [_report_out(r, admin=True) for r in qs[:300]]})


@api_view(["PATCH"])
@permission_classes([AdminSection])
def admin_report(request, pk):
    """Change status and/or reply; a reply is emailed to the reporter."""
    r = get_object_or_404(ProblemReport.objects.select_related("user"), pk=pk)
    st = request.data.get("status")
    if st and st in ProblemReport.Status.values:
        r.status = st
    reply = str(request.data.get("reply") or "").strip()[:4000]
    mailed = {}
    if reply:
        r.reply, r.replied_at = reply, timezone.now()
        to = (
            r.user.email if r.user_id else r.email
        )  # the account's own address — never a typed-in one (no phishing relay)
        mailed = {"emailed": False}
        if to and not mail_ready():
            mailed["code"] = EMAIL_NOT_CONFIGURED
        elif to:
            try:
                send_mail(
                    f"Re: your Aasan report #{r.id}",
                    f"{reply}\n\n— Aasan support\n\nYour report: {r.text[:500]}",
                    None,
                    [to],
                    fail_silently=False,
                )
                mailed["emailed"] = True
            except Exception:  # noqa: BLE001 — the reply is still saved (and notified in-app); say it wasn't emailed
                mailed["code"] = "send_failed"
        if r.user_id:
            from apps.game.services import notify

            notify(r.user, "support", f"Reply to your report #{r.id}", reply[:300], "/help?tab=reports")
    r.save()
    return Response({**_report_out(r, admin=True), **mailed})


class ArticleSer(serializers.ModelSerializer):
    class Meta:
        model = HelpArticle
        fields = [
            "id",
            "slug",
            "category",
            "title",
            "title_ta",
            "body_md",
            "body_ta_md",
            "order",
            "published",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]


@api_view(["GET", "POST"])
@permission_classes([AdminSection])
def admin_articles(request):
    if request.method == "POST":
        ser = ArticleSer(data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data, status=status.HTTP_201_CREATED)
    return Response(ArticleSer(HelpArticle.objects.all(), many=True).data)


@api_view(["PATCH", "DELETE"])
@permission_classes([AdminSection])
def admin_article(request, pk):
    a = get_object_or_404(HelpArticle, pk=pk)
    if request.method == "DELETE":
        a.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    ser = ArticleSer(a, data=request.data, partial=True)
    ser.is_valid(raise_exception=True)
    ser.save()
    return Response(ser.data)
