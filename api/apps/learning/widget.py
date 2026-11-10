"""AI-written interactive widgets ("Interactive" tab under a lesson's explanation).

The model writes a small HTML+CSS+JS document. We never sanitise it into shape: anything that could reach the network,
load external code or escape the sandbox is REJECTED (the author can regenerate). The browser then renders it only in
an `<iframe sandbox="allow-scripts">` whose src is `widget_frame` below: a same-site URL with a short-lived signed token, served with
its own `Content-Security-Policy: sandbox allow-scripts; default-src 'none'; …` (opaque origin even if opened top-level, no network)
and a bootstrap that removes WebRTC and link/frame elements. srcdoc is NOT used: it would inherit the app's CSP.
An optional checkpoint answer is posted by the widget and checked here against a key that never leaves the server."""

import logging
import math
import re

from django.core import signing
from django.db import transaction
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_GET
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .access import get_viewable_subsection, is_owner
from .models import LessonWidget

log = logging.getLogger(__name__)

MAX_BYTES = 30 * 1024
WIDGETS_PER_DAY = 10  # (re)generations per author per day
CHECKS_PER_DAY = 300  # checkpoint answers per learner per day
STALE_AFTER_S = 300

# The SVG/XHTML namespace URIs are inert identifiers, not fetches; they are the only URLs we tolerate.
_NS = re.compile(r"""xmlns(?::\w+)?\s*=\s*["']http://www\.w3\.org/[\w/.]+["']""", re.IGNORECASE)
# (pattern, reason). Matched case-insensitively against the whole document.
_FORBIDDEN: list[tuple[re.Pattern, str]] = [
    (re.compile(p, re.IGNORECASE | re.DOTALL), why)
    for p, why in [
        (r"<script\b[^>]*\bsrc\s*=", "external script"),
        (
            r"<\s*(link|iframe|frame|frameset|object|embed|applet|base|form|meta|portal|webview)\b",
            "forbidden element",
        ),
        (
            r"\b(src|href|xlink:href|srcset|poster)\s*=\s*[\"'`]?\s*(?!data:|#)[^\s\"'`>]",
            "external resource attribute",
        ),
        (r"\bhttps?:|\bftp:|\bwss?:|\bfile:", "URL"),
        (r"javascript\s*:|vbscript\s*:", "script URL"),
        (r"@import|url\s*\(\s*[\"']?\s*(?!data:|#)", "CSS import / external url()"),
        (r"\bfetch\s*\(|\.\s*fetch\b|[\"'`]fetch[\"'`]", "fetch"),
        (r"XMLHttpRequest|ActiveXObject", "XMLHttpRequest"),
        (r"WebSocket|EventSource|WebTransport|RTCPeerConnection|sendBeacon", "network API"),
        (r"\bimport\s*\(|\bimport\s+[\w{*\"']|importScripts", "import"),
        (
            r"\beval\s*\(|\beval\b\s*[,;)\]]|(?-i:\bFunction\s*\(|new\s+Function\b)|\bset(Timeout|Interval)\s*\(\s*[\"'`]",
            "dynamic code",
        ),
        (r"\b(Shared)?Worker\s*\(|serviceWorker|Worklet", "workers"),
        (
            r"document\s*\.\s*(cookie|write|domain)|localStorage|sessionStorage|indexedDB|\bcaches\s*\.",
            "storage / document access",
        ),
        (
            r"(window|document|self|globalThis|this)\s*\.\s*location\b|\blocation\s*\.\s*(href|assign|replace|reload)\b|\blocation\s*=[^=]",
            "navigation",
        ),
        (
            r"\bwindow\s*\.\s*open\b|\bopen\s*\(\s*[\"'`]|\bopener\b|\bhistory\.(push|replace|back|go|forward)",
            "navigation",
        ),
        (r"\b(top|parent|frameElement)\.(?!postMessage\b)[A-Za-z_$]|\b(top|parent)\s*\[", "parent access"),
        (r"srcdoc", "nested document"),
        # Cheap catches for obfuscation; the sandbox + CSP + bootstrap are what we actually rely on.
        (r"\[\s*[\"'`][^\"'`\]]*[\"'`]\s*\+", "computed property name"),
        (
            r"\b(window|document|self|globalThis|frames|navigator|top|parent)\s*\[|\bglobalThis\b",
            "computed global access",
        ),
        (r"fromCharCode|fromCodePoint|\batob\s*\(|\bunescape\s*\(", "encoded strings"),
        (r"\.\s*constructor\b|\[\s*[\"'`]constructor", "constructor access"),
        (r"(?-i:RTC|PeerConnection|DataChannel)", "WebRTC"),
        (r"createElement(NS)?\s*\([^)]*\+|createElement(NS)?\s*\(\s*[\w$.]+\s*\)", "dynamic element"),
        (
            r"createElement(NS)?\s*\([^)]*[\"'`]\s*(link|meta|base|i?frame|object|embed|portal|form|script)\b",
            "forbidden element",
        ),
        (r"prefetch|preconnect|prerender|preload|modulepreload", "resource hints"),
    ]
]


class WidgetRejected(ValueError):
    pass


def validate_html(html: str) -> str:
    """Return the widget document unchanged if it is safe enough to hand to the sandbox, else raise WidgetRejected."""
    if not isinstance(html, str) or not html.strip():
        raise WidgetRejected("empty")
    if len(html.encode("utf-8")) > MAX_BYTES:
        raise WidgetRejected("too large")
    if "\x00" in html:
        raise WidgetRejected("binary")
    probe = _NS.sub("", html)
    for pat, why in _FORBIDDEN:
        if pat.search(probe):
            raise WidgetRejected(why)
    if not re.search(r"<script\b", html, re.IGNORECASE):
        raise WidgetRejected("not interactive")
    return html


def _answer_key(out) -> tuple[str, dict]:
    """Keep a checkpoint only if it is well-formed and the widget actually posts an answer."""
    kind, value = (out.answer_kind or "").strip().lower(), (out.answer_value or "").strip()
    q = (out.checkpoint_question or "").strip()[:300]
    if not q or kind not in ("number", "text") or not value or "aasan-widget-answer" not in out.html:
        return "", {}
    if kind == "number":
        try:
            v = float(value.replace(",", "").replace("₹", ""))
        except ValueError:
            return "", {}
        tol = abs(float(out.answer_tolerance or 0))
        if not math.isfinite(v) or not math.isfinite(tol):
            return "", {}
        return q, {"kind": "number", "value": v, "tolerance": tol}
    return q, {"kind": "text", "value": value[:100]}


def build(widget_id: int) -> None:
    """Background job: write (or rewrite) one lesson's widget."""
    from llm.prompts.curriculum import LANG_RULE
    from llm.prompts.lx import WIDGET_SYSTEM, WidgetOut, widget_prompt
    from llm.structured import complete_json_sync

    w = LessonWidget.objects.select_related("subsection__section__curriculum").get(id=widget_id)
    sub = w.subsection
    cur = sub.section.curriculum
    try:
        out = complete_json_sync(
            "author",
            WIDGET_SYSTEM.format(lang_rule=LANG_RULE.get(cur.language, LANG_RULE["en"])),
            widget_prompt(
                cur.title, sub.title, sub.objective, sub.explanation_md, sub.key_points, w.instructions
            ),
            WidgetOut,
            max_tokens=9000,
            effort="medium",
        )
        html = validate_html(out.html)
        q, key = _answer_key(out)
        w.title, w.html, w.checkpoint_question, w.answer_key = out.title[:200], html, q, key
        w.status, w.error = LessonWidget.Status.READY, ""
    except WidgetRejected as e:
        log.warning("widget %s rejected: %s", widget_id, e)
        w.status, w.error = LessonWidget.Status.FAILED, "unsafe_widget"
    except Exception as e:  # noqa: BLE001 — provider/parse failures become a retryable "failed"
        log.warning("widget %s failed: %s", widget_id, e)
        w.status, w.error = LessonWidget.Status.FAILED, "generation_failed"
    w.save()
    if (
        w.status == LessonWidget.Status.READY
    ):  # new learner-facing HTML + answer key: re-moderate an approved course
        from .services import send_back_for_review

        send_back_for_review(cur)


FRAME_SALT = "lx.widget.frame"
FRAME_TOKEN_MAX_AGE = (
    600  # seconds: the iframe request carries no Authorization header, so the URL carries a short-lived grant
)


def _version(w: LessonWidget) -> int:
    return int(w.updated_at.timestamp())


def frame_url(w: LessonWidget, user) -> str:
    token = signing.dumps({"u": user.id, "w": w.id, "v": _version(w)}, salt=FRAME_SALT, compress=True)
    return f"/api/learn/widgets/{w.id}/frame/?t={token}"


# Runs before the widget's own script. CSP covers fetch/XHR/WebSocket/images/prefetch; WebRTC is not covered by CSP,
# so it is removed here (non-configurable), and link/meta/frame-like elements are refused or stripped as soon as they appear.
FRAME_BOOTSTRAP = """<script>(function(){var w=window;
["RTCPeerConnection","webkitRTCPeerConnection","mozRTCPeerConnection","RTCDataChannel","RTCSessionDescription","RTCIceCandidate",
"RTCRtpSender","RTCRtpReceiver","RTCRtpTransceiver","RTCDtlsTransport","RTCIceTransport","RTCSctpTransport","RTCCertificate"].forEach(function(n){
try{Object.defineProperty(w,n,{value:undefined,writable:false,configurable:false});}catch(e){try{w[n]=undefined;}catch(e2){}}});
var bad={LINK:1,META:1,BASE:1,IFRAME:1,FRAME:1,FRAMESET:1,OBJECT:1,EMBED:1,PORTAL:1,FORM:1};
var dp=Document.prototype,ce=dp.createElement,cn=dp.createElementNS;
Object.defineProperty(dp,"createElement",{value:function(t){if(bad[String(t).toUpperCase()])throw new Error("blocked");return ce.apply(this,arguments);},writable:false,configurable:false});
Object.defineProperty(dp,"createElementNS",{value:function(ns,t){if(bad[String(t).split(":").pop().toUpperCase()])throw new Error("blocked");return cn.apply(this,arguments);},writable:false,configurable:false});
var sel="link,meta,base,iframe,frame,frameset,object,embed,portal,form";
new MutationObserver(function(ms){ms.forEach(function(m){m.addedNodes.forEach(function(n){if(n.nodeType!==1)return;
if(bad[n.nodeName.toUpperCase()])n.remove();if(n.querySelectorAll)n.querySelectorAll(sel).forEach(function(x){x.remove();});});});})
.observe(document.documentElement,{childList:true,subtree:true});})();</script>"""
FRAME_CSP = (
    "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; "
    "font-src data:; media-src data:; connect-src 'none'; frame-src 'none'; child-src 'none'; worker-src 'none'; "
    "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
)


def frame_document(html: str) -> str:
    body = re.sub(r"^\s*<!doctype[^>]*>", "", html, flags=re.IGNORECASE)
    return (
        '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta http-equiv="x-dns-prefetch-control" content="off">' + FRAME_BOOTSTRAP + "</head><body>" + body
    )


@require_GET
@xframe_options_sameorigin
def widget_frame(request, pk):
    """The widget document for the sandboxed iframe. Auth = signed (user, widget, version) token, 10 minutes."""
    from django.contrib.auth import get_user_model

    try:
        data = signing.loads(request.GET.get("t", ""), salt=FRAME_SALT, max_age=FRAME_TOKEN_MAX_AGE)
    except signing.BadSignature:  # includes SignatureExpired
        raise Http404 from None
    if not isinstance(data, dict) or data.get("w") != pk:
        raise Http404
    user = get_user_model().objects.filter(pk=data.get("u"), is_active=True).first()
    w = (
        LessonWidget.objects.filter(pk=pk, status=LessonWidget.Status.READY)
        .select_related("subsection")
        .first()
    )
    if not user or not w or _version(w) != data.get("v"):
        raise Http404
    get_viewable_subsection(user, w.subsection_id)  # still allowed to see this lesson (404 otherwise)
    resp = HttpResponse(frame_document(w.html), content_type="text/html; charset=utf-8")
    resp["Content-Security-Policy"] = FRAME_CSP
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Cache-Control"] = "private, no-store"
    resp["Referrer-Policy"] = "no-referrer"
    resp["X-DNS-Prefetch-Control"] = "off"
    resp["Cross-Origin-Resource-Policy"] = "same-origin"
    resp["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), display-capture=(), fullscreen=()"
    )
    return resp


def _out(w: LessonWidget | None, can_edit: bool, user=None) -> dict:
    if not w:
        return {"status": "none", "can_edit": can_edit}
    ready = w.status == LessonWidget.Status.READY
    return {
        "status": w.status,
        "title": w.title if ready else "",
        "frame_url": frame_url(w, user) if ready and user else "",
        "error": w.error if can_edit else "",
        "checkpoint_question": w.checkpoint_question if ready else "",
        "has_checkpoint": ready and bool(w.answer_key),
        "instructions": w.instructions if can_edit else "",
        "can_edit": can_edit,
    }


class WidgetIn(serializers.Serializer):
    instructions = serializers.CharField(max_length=500, required=False, allow_blank=True)


@api_view(["GET", "POST"])
def widget(request, pk):
    """GET: the lesson's widget (no answer key). POST (course owner/author only): generate or regenerate it."""
    from apps.providers.services import BudgetExceeded, charge

    sub = get_viewable_subsection(request.user, pk)
    owner = is_owner(request.user, sub.section.curriculum)
    w = LessonWidget.objects.filter(subsection=sub).first()
    if request.method == "GET":
        return Response(_out(w, owner, request.user))
    if not owner:
        return Response({"code": "not_author"}, status=status.HTTP_403_FORBIDDEN)
    if sub.lesson_status != "ready":
        return Response({"code": "lesson_not_ready"}, status=status.HTTP_409_CONFLICT)
    ser = WidgetIn(data=request.data)
    ser.is_valid(raise_exception=True)
    with transaction.atomic():
        w = LessonWidget.objects.select_for_update().filter(subsection=sub).first()
        if (
            w
            and w.status == LessonWidget.Status.GENERATING
            and (timezone.now() - w.updated_at).total_seconds() < STALE_AFTER_S
        ):
            return Response(_out(w, True, request.user))
        try:
            charge(request.user, "lx_widgets", 1, WIDGETS_PER_DAY)
        except BudgetExceeded:
            return Response({"code": "widget_budget"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        instructions = ser.validated_data.get("instructions", "")
        if w:
            w.status, w.error, w.instructions = LessonWidget.Status.GENERATING, "", instructions
            w.save()
        else:
            w = LessonWidget.objects.create(subsection=sub, instructions=instructions)
    from apps.study.jobs import enqueue

    wid = w.id
    transaction.on_commit(lambda: enqueue("apps.learning.widget.build", wid))
    return Response(_out(w, True, request.user), status=status.HTTP_202_ACCEPTED)


def check_answer(key: dict, answer) -> bool:
    from .activities import _norm

    if key.get("kind") == "number":
        if isinstance(answer, bool) or not isinstance(answer, (int, float, str)):
            return False
        try:
            v = float(str(answer).replace(",", "").replace("₹", "").strip())
        except ValueError:
            return False
        if not math.isfinite(v):
            return False
        return abs(v - key["value"]) <= max(key.get("tolerance", 0.0), 1e-9 * max(1.0, abs(key["value"])))
    if key.get("kind") == "text":
        return isinstance(answer, str) and _norm(answer) == _norm(key["value"])
    return False


@api_view(["POST"])
def widget_check(request, pk):
    """The widget posted an answer (relayed by the parent page): right or not. The key itself is never returned."""
    from apps.providers.services import BudgetExceeded, charge

    sub = get_viewable_subsection(request.user, pk)
    w = LessonWidget.objects.filter(subsection=sub, status=LessonWidget.Status.READY).first()
    if not w or not w.answer_key:
        return Response({"code": "no_checkpoint"}, status=status.HTTP_404_NOT_FOUND)
    answer = request.data.get("answer")
    if (
        isinstance(answer, bool)
        or not isinstance(answer, (int, float, str))
        or (isinstance(answer, str) and not 0 < len(answer) <= 100)
    ):
        return Response({"code": "bad_answer"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        charge(request.user, "lx_widget_checks", 1, CHECKS_PER_DAY)
    except BudgetExceeded:
        return Response({"code": "too_many_checks"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    return Response({"correct": check_answer(w.answer_key, answer)})
