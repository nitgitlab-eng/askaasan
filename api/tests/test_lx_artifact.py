"""lx: artifact_check activities — SSRF-safe fetching (monkeypatched DNS + transport), grading, authoring, rate limit."""

import socket
import threading
import time

import pytest
from django.utils import timezone

from apps.learning import safe_fetch as sf
from apps.learning.models import Activity, Curriculum, Enrollment, Section, Subsection
from tests.test_lab import client_for

pytestmark = pytest.mark.django_db

PAGE = b"""<!doctype html><html><head><title>Kavya</title><style>.x{}</style><script>var hidden = "About me";</script></head>
<body><h1>Kavya's portfolio</h1><h2>My projects</h2><p>I love building with Python and data.</p>
<a href="https://github.com/kavya">GitHub</a> <a href="mailto:k@x.in">Mail me</a>
<img src="a.png" alt="me"><img src="b.png"></body></html>"""


class FakeNet:
    """DNS table + canned responses per (host, path)."""

    def __init__(self, monkeypatch, dns=None, pages=None):
        self.dns = dns or {"kavya.github.io": ["185.199.108.153"]}
        self.pages = pages or {
            ("kavya.github.io", "/"): sf.RawResponse(200, {"content-type": "text/html; charset=utf-8"}, PAGE)
        }
        self.calls = []
        monkeypatch.setattr(sf, "resolve", self.resolve)
        monkeypatch.setattr(sf, "transport", self.transport)

    def resolve(self, host):
        if host not in self.dns:
            raise sf.FetchFailed("unreachable")
        return self.dns[host]

    def transport(self, host, ip, path, deadline):
        self.calls.append((host, ip, path))
        return self.pages.get((host, path), sf.RawResponse(404, {}))


# ── URL + IP policy ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url,code",
    [
        ("http://kavya.github.io/", "https_only"),
        ("ftp://kavya.github.io/", "https_only"),
        ("file:///etc/passwd", "https_only"),
        ("https://kavya.github.io:8443/", "port_not_allowed"),
        ("https://user:pw@kavya.github.io/", "bad_url"),
        ("https://evil.example@kavya.github.io/", "bad_url"),
        ("https://127.0.0.1/", "ip_not_allowed"),
        ("https://[::1]/", "ip_not_allowed"),
        ("https://169.254.169.254/latest/meta-data/", "ip_not_allowed"),
        ("https://localhost/", "private_address"),
        ("https://app.localhost/", "private_address"),
        ("https://metadata.google.internal/", "private_address"),
        ("https://printer.local/", "private_address"),
        ("https://intranet/", "private_address"),
        ("https://kavya.github.io/a b", "bad_url"),
        ("not a url", "bad_url"),
    ],
)
def test_url_shape_refusals(url, code):
    with pytest.raises(sf.FetchRefused) as e:
        sf.check_url(url)
    assert e.value.code == code


@pytest.mark.parametrize(
    "ip",
    [
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "127.0.0.1",
        "169.254.169.254",
        "100.64.1.1",
        "0.0.0.0",
        "224.0.0.1",
        "240.0.0.1",
        "255.255.255.255",
        "198.18.0.1",
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "ff02::1",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
        "::ffff:10.0.0.1",
        "64:ff9b::a9fe:a9fe",
        "2002:7f00:1::",
        "2001:db8::1",
        "not-an-ip",
        "fec0::1",
        "fec0:1:2::3",
        "2002:808:808::1",
        "2001::1",
        "100::1",
        "3fff::1",
        "4000::1",
        "::8.8.8.8",
    ],
)
def test_non_public_ips_refused(ip):
    assert not sf.ip_is_public(ip)


@pytest.mark.parametrize("ip", ["8.8.8.8", "185.199.108.153", "2606:4700:4700::1111", "::ffff:8.8.8.8"])
def test_public_ips_allowed(ip):
    assert sf.ip_is_public(ip)


def test_dns_to_private_or_mixed_answers_is_refused_before_connecting(monkeypatch):
    net = FakeNet(
        monkeypatch,
        dns={
            "evil.example": ["93.184.216.34", "127.0.0.1"],
            "rebind.example": ["10.1.2.3"],
            "v6.example": ["::ffff:169.254.169.254"],
        },
    )
    for host in ("evil.example", "rebind.example", "v6.example", "no-such-host.example"):
        with pytest.raises(
            sf.FetchFailed
        ) as e:  # one generic answer for "private" and "no such host": no DNS oracle
            sf.fetch(f"https://{host}/")
        assert e.value.code == "unreachable"
    assert net.calls == []


def test_connects_to_the_vetted_ip_with_original_host(monkeypatch):
    net = FakeNet(monkeypatch)
    page = sf.fetch("https://Kavya.GitHub.io")
    assert net.calls == [("kavya.github.io", "185.199.108.153", "/")] and "portfolio" in page.html


def test_redirect_to_metadata_ip_or_private_host_is_refused(monkeypatch):
    net = FakeNet(
        monkeypatch,
        dns={"kavya.github.io": ["185.199.108.153"], "sneaky.example": ["169.254.169.254"]},
        pages={
            ("kavya.github.io", "/"): sf.RawResponse(
                302, {"location": "https://sneaky.example/latest/meta-data/"}
            ),
            ("kavya.github.io", "/raw"): sf.RawResponse(
                301, {"location": "https://169.254.169.254/latest/meta-data/"}
            ),
            ("kavya.github.io", "/http"): sf.RawResponse(302, {"location": "http://kavya.github.io/"}),
            ("kavya.github.io", "/loop"): sf.RawResponse(302, {"location": "/loop"}),
        },
    )
    with pytest.raises(sf.FetchFailed) as e:
        sf.fetch("https://kavya.github.io/")
    assert e.value.code == "unreachable"
    for path, code in (("/raw", "ip_not_allowed"), ("/http", "https_only")):
        with pytest.raises(sf.FetchRefused) as e:
            sf.fetch(f"https://kavya.github.io{path}")
        assert e.value.code == code
    assert all(ip == "185.199.108.153" for _h, ip, _p in net.calls)  # never connected anywhere else
    with pytest.raises(sf.FetchFailed) as e:
        sf.fetch("https://kavya.github.io/loop")
    assert e.value.code == "too_many_redirects"
    assert len([c for c in net.calls if c[2] == "/loop"]) == sf.MAX_REDIRECTS + 1


def test_oversized_wrong_type_and_errors(monkeypatch):
    html = {"content-type": "text/html"}
    FakeNet(
        monkeypatch,
        pages={
            ("kavya.github.io", "/big"): sf.RawResponse(200, html, b"x" * (sf.MAX_BYTES + 1)),
            ("kavya.github.io", "/declared"): sf.RawResponse(
                200, {**html, "content-length": str(5 * sf.MAX_BYTES)}, b"<p>hi</p>"
            ),
            ("kavya.github.io", "/json"): sf.RawResponse(200, {"content-type": "application/json"}, b"{}"),
            ("kavya.github.io", "/pdf"): sf.RawResponse(200, {}, b"%PDF"),
            ("kavya.github.io", "/gz"): sf.RawResponse(
                200, {**html, "content-encoding": "gzip"}, b"\x1f\x8b"
            ),
            ("kavya.github.io", "/down"): sf.RawResponse(503, {}),
        },
    )
    for path, code in (
        ("/big", "too_large"),
        ("/declared", "too_large"),
        ("/json", "not_html"),
        ("/pdf", "not_html"),
        ("/gz", "encoded_body"),
    ):
        with pytest.raises(sf.FetchRefused) as e:
            sf.fetch(f"https://kavya.github.io{path}")
        assert e.value.code == code, path
    for path, code in (("/down", "http_503"), ("/missing", "http_404")):
        with pytest.raises(sf.FetchFailed) as e:
            sf.fetch(f"https://kavya.github.io{path}")
        assert e.value.code == code
    with pytest.raises(sf.FetchFailed):
        sf.fetch("https://unknown-host.example/")


def test_real_transport_sends_no_cookies_and_pins_ip(monkeypatch):
    """The stdlib transport: connects to the vetted IP, SNI/Host = original name, no cookie/auth headers."""
    sent = {}

    class FakeResp:
        status = 200

        def getheaders(self):
            return [("Content-Type", "text/html")]

        def __init__(self):
            self._parts = [b"<p>ok</p>", b""]

        def read(self, n):
            return self._parts.pop(0)

    class FakeConn:
        def __init__(self, host, ip, timeout):
            sent.update(host=host, ip=ip, timeout=timeout)
            self.sock = None

        def connect(self):
            self.sock = object()

        def request(self, method, path, headers):
            sent.update(method=method, path=path, headers=headers)

        def getresponse(self):
            return FakeResp()

        def close(self):
            sent["closed"] = True

    import time

    monkeypatch.setattr(sf, "_PinnedHTTPS", FakeConn)
    r = sf.transport("kavya.github.io", "185.199.108.153", "/", time.monotonic() + 5)
    assert (
        r.body == b"<p>ok</p>"
        and sent["ip"] == "185.199.108.153"
        and sent["host"] == "kavya.github.io"
        and sent["closed"]
    )
    assert sent["headers"]["Host"] == "kavya.github.io" and sent["headers"]["Accept-Encoding"] == "identity"
    assert not {"Cookie", "Authorization"} & set(sent["headers"]) and 0 < sent["timeout"] <= 5


# ── Activity: authoring, grading, rate limit ──────────────────────────

SOURCE = {
    "type": "artifact_check",
    "title": "Publish your portfolio",
    "prompt": "Make a one-page portfolio and paste its link.",
    "steps": ["Create a GitHub Pages site", "Add a heading and two pictures"],
    "checks": [
        {"kind": "heading", "value": "My projects"},
        {"kind": "phrase", "value": "python"},
        {"kind": "link", "value": "github.com", "min_count": 1},
        {"kind": "images", "value": "", "min_count": 2},
        {"kind": "phrase", "value": "Contact form"},
    ],
    "explanation": "Great portfolio!",
}


def _authored():
    c, u = client_for("artifact-author@aasan.test", creator=True)
    cur = Curriculum.objects.create(
        owner=u, goal="Portfolio", title="Portfolio", status="ready", kind="authored", language="en"
    )
    sec = Section.objects.create(curriculum=cur, order=0, title="Build")
    sub = Subsection.objects.create(
        section=sec,
        order=0,
        title="Publish",
        objective="Publish a page",
        lesson_status="ready",
        explanation_md="x",
    )
    return c, u, cur, sub


def test_author_builds_artifact_check_and_learner_is_graded(monkeypatch):
    c, _u, cur, sub = _authored()
    # AI generation is not offered for this type; hand-made only.
    assert (
        c.post(
            f"/api/lab/subsections/{sub.id}/activities/", {"type": "artifact_check"}, format="json"
        ).status_code
        == 400
    )
    bad = {**SOURCE, "checks": [{"kind": "phrase", "value": "  "}]}
    assert (
        c.post(
            f"/api/lab/subsections/{sub.id}/activities/",
            {"type": "artifact_check", "source": bad},
            format="json",
        ).status_code
        == 400
    )
    r = c.post(
        f"/api/lab/subsections/{sub.id}/activities/",
        {"type": "artifact_check", "source": SOURCE},
        format="json",
    )
    assert r.status_code == 201, r.data
    a = Activity.objects.get(id=r.data["id"])
    assert (
        a.payload["checklist"][0] == {"kind": "heading", "value": "My projects", "min_count": 1}
        and a.payload["n_checks"] == 5
    )
    assert a.key["checks"][4]["value"] == "Contact form"

    cur.visibility, cur.published_at = "link", timezone.now()
    cur.save()
    lc, lu = client_for("artifact-learner@aasan.test")
    Enrollment.objects.create(user=lu, curriculum=cur)
    net = FakeNet(monkeypatch)
    r = lc.post(
        f"/api/learn/activities/{a.id}/attempt/",
        {"answer": {"url": "https://kavya.github.io/"}},
        format="json",
    )
    assert r.status_code == 200
    assert r.data["score"] == 0.8 and r.data["correct"] and r.data["reveal"]["status"] == "missing"
    assert r.data["reveal"]["missing"] == [{"kind": "phrase", "value": "Contact form", "min_count": 1}]
    assert "Contact form" in r.data["feedback"] and len(net.calls) == 1

    # Script text never counts as visible content; unreachable sites score 0 with a friendly note.
    r = lc.post(
        f"/api/learn/activities/{a.id}/attempt/",
        {"answer": {"url": "https://nowhere.example/"}},
        format="json",
    )
    assert r.data["score"] == 0 and r.data["reveal"] == {"status": "unreachable", "code": "unreachable"}
    r = lc.post(
        f"/api/learn/activities/{a.id}/attempt/",
        {"answer": {"url": "http://kavya.github.io/"}},
        format="json",
    )
    assert r.data["score"] == 0 and r.data["reveal"]["code"] == "https_only"


def test_all_found_is_live_and_hidden_checklist(monkeypatch):
    c, _u, cur, sub = _authored()
    src = {**SOURCE, "checks": SOURCE["checks"][:4], "show_checklist": False}
    aid = c.post(
        f"/api/lab/subsections/{sub.id}/activities/", {"type": "artifact_check", "source": src}, format="json"
    ).data["id"]
    a = Activity.objects.get(id=aid)
    assert a.payload["checklist"] == [] and a.payload["n_checks"] == 4
    FakeNet(monkeypatch)
    r = c.post(
        f"/api/learn/activities/{aid}/attempt/", {"answer": {"url": "https://kavya.github.io"}}, format="json"
    )
    assert (
        r.data["score"] == 1.0
        and r.data["reveal"]["status"] == "live"
        and r.data["feedback"] == "Great portfolio!"
    )


def test_rate_limit_per_user_per_hour(monkeypatch):
    from apps.learning.api import ARTIFACT_CHECKS_PER_HOUR

    c, _u, _cur, sub = _authored()
    aid = c.post(
        f"/api/lab/subsections/{sub.id}/activities/",
        {"type": "artifact_check", "source": SOURCE},
        format="json",
    ).data["id"]
    net = FakeNet(monkeypatch)
    for _ in range(ARTIFACT_CHECKS_PER_HOUR):
        assert (
            c.post(
                f"/api/learn/activities/{aid}/attempt/",
                {"answer": {"url": "https://kavya.github.io/"}},
                format="json",
            ).status_code
            == 200
        )
    r = c.post(
        f"/api/learn/activities/{aid}/attempt/",
        {"answer": {"url": "https://kavya.github.io/"}},
        format="json",
    )
    assert (
        r.status_code == 429
        and r.data["code"] == "artifact_check_rate_limited"
        and len(net.calls) == ARTIFACT_CHECKS_PER_HOUR
    )


def test_guests_and_strangers_cannot_trigger_fetches(monkeypatch):
    c, _u, cur, sub = _authored()
    aid = c.post(
        f"/api/lab/subsections/{sub.id}/activities/",
        {"type": "artifact_check", "source": SOURCE},
        format="json",
    ).data["id"]
    cur.visibility, cur.published_at = "link", timezone.now()
    cur.save()
    net = FakeNet(monkeypatch)
    from rest_framework.test import APIClient

    guest = APIClient()
    r = guest.post(
        f"/api/share/{cur.share_token}/attempt/{aid}/",
        {"answer": {"url": "https://kavya.github.io/"}},
        format="json",
    )
    assert r.status_code == 403
    stranger, _ = client_for("artifact-stranger@aasan.test")
    assert (
        stranger.post(
            f"/api/learn/activities/{aid}/attempt/",
            {"answer": {"url": "https://kavya.github.io/"}},
            format="json",
        ).status_code
        == 404
    )
    assert net.calls == []


# ── Security review fixes: hard deadline against drip-feeding servers, header caps, atomic rate limit ──


def _drip_server(mode):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def run():
        try:
            c, _ = srv.accept()
            c.recv(4096)
            if mode == "headers":
                c.sendall(b"HTTP/1.1 200 OK\r\n")
                for _ in range(12):
                    c.sendall(b"X-A: b\r\n")
                    time.sleep(0.3)
                c.sendall(b"Content-Type: text/html\r\n\r\n<html></html>")
            elif mode == "body":
                c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 100000\r\n\r\n")
                for _ in range(12):
                    c.sendall(b"a")
                    time.sleep(0.3)
            elif mode == "many_headers":
                c.sendall(
                    b"HTTP/1.1 200 OK\r\n"
                    + b"".join(b"X-%d: v\r\n" % i for i in range(90))
                    + b"Content-Type: text/html\r\n\r\nhi"
                )
            c.close()
        except OSError:
            pass
        finally:
            srv.close()

    threading.Thread(target=run, daemon=True).start()
    port = srv.getsockname()[1]

    class Plain(sf._PinnedHTTPS):
        def connect(self):
            self.sock = socket.create_connection(("127.0.0.1", port), self.timeout)

    return Plain


@pytest.mark.parametrize("mode", ["headers", "body"])
def test_drip_feeding_server_cannot_outlast_the_deadline(monkeypatch, mode):
    monkeypatch.setattr(sf, "_PinnedHTTPS", _drip_server(mode))
    t0 = time.monotonic()
    with pytest.raises(sf.FetchFailed) as e:
        sf.transport("example.com", "127.0.0.1", "/", time.monotonic() + 1.0)
    assert e.value.code == "timeout" and time.monotonic() - t0 < 1.8


def test_header_count_is_capped(monkeypatch):
    monkeypatch.setattr(sf, "_PinnedHTTPS", _drip_server("many_headers"))
    with pytest.raises(sf.FetchRefused) as e:
        sf.transport("example.com", "127.0.0.1", "/", time.monotonic() + 3.0)
    assert e.value.code == "too_large"


def test_rate_limit_reserves_before_fetching(monkeypatch):
    """The hourly slot is taken atomically BEFORE the fetch, so parallel requests can't all pass a count-after check."""
    from django.utils import timezone as tz

    from apps.learning.api import ARTIFACT_CHECKS_PER_HOUR
    from apps.providers.models import UsageCounter

    c, u, _cur, sub = _authored()
    aid = c.post(
        f"/api/lab/subsections/{sub.id}/activities/",
        {"type": "artifact_check", "source": SOURCE},
        format="json",
    ).data["id"]
    seen = []

    def transport(host, ip, path, deadline):
        # While this request is fetching, its slot is already counted.
        seen.append(
            UsageCounter.objects.get(user=u, metric=f"artifact_checks_h{tz.localtime().hour:02d}").amount
        )
        return sf.RawResponse(200, {"content-type": "text/html"}, PAGE)

    FakeNet(monkeypatch)
    monkeypatch.setattr(sf, "transport", transport)
    assert (
        c.post(
            f"/api/learn/activities/{aid}/attempt/",
            {"answer": {"url": "https://kavya.github.io/"}},
            format="json",
        ).status_code
        == 200
    )
    assert seen == [1]
    UsageCounter.objects.filter(user=u).update(amount=ARTIFACT_CHECKS_PER_HOUR)
    assert (
        c.post(
            f"/api/learn/activities/{aid}/attempt/",
            {"answer": {"url": "https://kavya.github.io/"}},
            format="json",
        ).status_code
        == 429
    )
    assert seen == [1]


@pytest.mark.parametrize("mode", ["silent", "drip"])
def test_slow_tls_handshake_cannot_outlast_the_deadline(mode):
    """A host that accepts TCP but never finishes (or drips) the TLS handshake is dropped at the deadline."""
    import ssl

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    stop = threading.Event()

    def run():
        try:
            c, _ = srv.accept()
            c.recv(4096)  # the ClientHello
            if mode == "drip":
                c.sendall(
                    b"\x16\x03\x03\x40\x00"
                )  # a 16 KB handshake record header … then one byte at a time
                while not stop.is_set():
                    c.sendall(b"\x00")
                    time.sleep(0.2)
            else:
                stop.wait(5)
            c.close()
        except OSError:
            pass
        finally:
            srv.close()

    threading.Thread(target=run, daemon=True).start()
    t0 = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            sf.tls_connect(
                "127.0.0.1",
                srv.getsockname()[1],
                "example.com",
                ssl.create_default_context(),
                time.monotonic() + 1.0,
            )
        assert time.monotonic() - t0 < 1.6
    finally:
        stop.set()


def test_transport_maps_slow_handshake_to_timeout(monkeypatch):
    def slow(ip, port, host, context, deadline):
        raise TimeoutError("deadline")

    monkeypatch.setattr(sf, "tls_connect", slow)
    with pytest.raises(sf.FetchFailed) as e:
        sf.transport("example.com", "127.0.0.1", "/", time.monotonic() + 1.0)
    assert e.value.code == "timeout"
