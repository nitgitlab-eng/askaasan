"""Fetch a learner-published web page SAFELY (artifact_check activities).

SSRF defences, all mandatory:
- https only, default port only, no userinfo, no IP-literal / localhost-ish / internal host names;
- we resolve DNS ourselves and refuse if ANY address is private, loopback, link-local, multicast, reserved,
  unspecified, shared (CGNAT) or otherwise non-global — IPv4 and IPv6, incl. IPv4-mapped / 6to4 / Teredo / NAT64;
- we connect to the vetted IP ourselves (TLS SNI + certificate check + Host header use the original name), so a second
  DNS answer can't swap the target (no DNS-rebinding window);
- redirects are followed by hand, at most 3, each one re-validated from scratch;
- one hard 5 s deadline enforced on every socket read/write, header + 1 MB body caps, text/html only, identity encoding (no decompression bombs), no cookies or auth sent.
Tests replace `resolve` and `transport` to simulate DNS answers and servers."""

import http.client
import ipaddress
import logging
import socket
import ssl
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

TIMEOUT_S = 5.0
MAX_BYTES = 1_000_000
MAX_REDIRECTS = 3
USER_AGENT = "AasanArtifactCheck/1.0 (+learning activity checker)"
_BLOCKED_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".intranet",
    ".lan",
    ".home",
    ".corp",
    ".private",
    ".localdomain",
    ".home.arpa",
    ".arpa",
)
_BLOCKED_NAMES = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "metadata",
    "metadata.google.internal",
    "instance-data",
}
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_V6_GLOBAL_UNICAST = ipaddress.ip_network("2000::/3")
MAX_HEADER_BYTES = 32 * 1024
MAX_HEADERS = 60
UNREACHABLE = (
    "unreachable"  # one code for DNS failure, non-public answers and connection errors: no DNS/network oracle
)


class FetchRefused(Exception):
    """We won't fetch this (unsafe URL/target or policy). `code` is safe to show the learner."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class FetchFailed(Exception):
    """The site didn't answer usefully (yet): timeout, TLS error, 4xx/5xx …"""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class Page:
    url: str
    html: str


@dataclass
class RawResponse:
    status: int
    headers: dict[str, str] = field(default_factory=dict)  # lower-cased names
    body: bytes = b""


def ip_is_public(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(a, ipaddress.IPv6Address):
        if a.is_site_local:
            return False
        embedded = a.ipv4_mapped or (a.teredo[1] if a.teredo else None) or a.sixtofour
        if embedded is None and a in _NAT64:
            embedded = ipaddress.IPv4Address(int(a) & 0xFFFFFFFF)
        if embedded is not None and not ip_is_public(str(embedded)):
            return False
        if a.ipv4_mapped:
            return True  # embedded v4 vetted above
        if a not in _V6_GLOBAL_UNICAST or a.sixtofour or a.teredo or a in _NAT64:
            return (
                False  # allowlist: only plain global unicast (2000::/3); never tunnels/translation prefixes
            )
    if isinstance(a, ipaddress.IPv4Address) and a in _CGNAT:
        return False
    return a.is_global and not (
        a.is_private
        or a.is_loopback
        or a.is_link_local
        or a.is_multicast
        or a.is_reserved
        or a.is_unspecified
    )


def check_url(url: str) -> tuple[str, str]:
    """Validate the URL shape → (ascii host, path+query). Raises FetchRefused."""
    if not isinstance(url, str) or len(url) > 2000 or any(c in url for c in "\r\n\t\x00 "):
        raise FetchRefused("bad_url")
    try:
        u = urlsplit(url.strip())
        port = u.port
    except ValueError:
        raise FetchRefused("bad_url") from None
    if u.scheme.lower() != "https":
        raise FetchRefused("https_only")
    if u.username is not None or u.password is not None or "@" in u.netloc:
        raise FetchRefused("bad_url")
    if port not in (None, 443):
        raise FetchRefused("port_not_allowed")
    host = (u.hostname or "").rstrip(".").lower()
    if not host:
        raise FetchRefused("bad_url")
    try:
        ipaddress.ip_address(host.strip("[]"))
        raise FetchRefused("ip_not_allowed")  # published sites have names; raw IPs are an SSRF smell
    except ValueError:
        pass
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise FetchRefused("bad_url") from None
    if host in _BLOCKED_NAMES or host.endswith(_BLOCKED_SUFFIXES) or "." not in host:
        raise FetchRefused("private_address")
    if not all(
        part and len(part) <= 63 and all(c.isalnum() or c == "-" for c in part) for part in host.split(".")
    ):
        raise FetchRefused("bad_url")
    path = (u.path or "/") + (f"?{u.query}" if u.query else "")
    return host, path


def resolve(host: str) -> list[str]:
    """All A/AAAA answers for host (replaced in tests)."""
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        raise FetchFailed(UNREACHABLE) from None
    return list(dict.fromkeys(i[4][0] for i in infos))


def safe_ip(host: str) -> str:
    ips = resolve(host)
    if not ips or not all(ip_is_public(ip) for ip in ips):  # one bad answer poisons the lot
        raise FetchFailed(UNREACHABLE)  # same answer as "no such host": learners can't probe internal DNS
    return ips[0]


class _PinnedHTTPS(http.client.HTTPSConnection):
    """HTTPS to a pre-vetted IP, while TLS SNI/cert checks and the Host header use the real hostname."""

    def __init__(self, host: str, ip: str, timeout: float):
        super().__init__(host, 443, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip
        self._deadline = time.monotonic() + timeout

    def connect(self):
        self.sock = tls_connect(self._ip, 443, self.host, self._context, self._deadline)


def _remaining(deadline: float) -> float:
    rem = deadline - time.monotonic()
    if rem <= 0:
        raise TimeoutError("deadline")
    return rem


def tls_connect(ip: str, port: int, host: str, context: ssl.SSLContext, deadline: float) -> ssl.SSLSocket:
    """TCP connect + TLS handshake under ONE hard deadline. The handshake runs non-blocking and every wait is bounded by
    the time left, so a server that drips (or never sends) handshake bytes can't hold the worker past the deadline."""
    import select

    raw = socket.create_connection((ip, port), _remaining(deadline))
    try:
        ssock = context.wrap_socket(raw, server_hostname=host, do_handshake_on_connect=False)
        ssock.setblocking(False)
        while True:
            try:
                ssock.do_handshake()
                break
            except ssl.SSLWantReadError:
                ready = select.select([ssock], [], [], _remaining(deadline))[0]
            except ssl.SSLWantWriteError:
                ready = select.select([], [ssock], [], _remaining(deadline))[1]
            if not ready:
                raise TimeoutError("deadline")
        ssock.settimeout(_remaining(deadline))
        return ssock
    except BaseException:
        raw.close()
        raise


class _DeadlineSocket:
    """Socket wrapper enforcing ONE hard deadline for the whole exchange: every send/recv gets timeout = deadline - now
    (a drip-feeding server can't stretch it), and the total bytes received are capped (headers + body)."""

    def __init__(self, sock, deadline: float, max_bytes: int):
        self._s, self._deadline, self._left = sock, deadline, max_bytes
        # Like socket.socket: http.client closes the connection as soon as the response arrives ("Connection: close")
        # and keeps reading the body through makefile(). The real socket must stay open until that reader is done.
        self._io_refs, self._closed = 0, False

    def _arm(self):
        rem = self._deadline - time.monotonic()
        if rem <= 0:
            raise TimeoutError("deadline")
        self._s.settimeout(rem)

    def sendall(self, data, *a):
        self._arm()
        return self._s.sendall(data, *a)

    def recv_into(self, buf, nbytes=0, *a):
        self._arm()
        n = self._s.recv_into(buf, min(nbytes or len(buf), 65536), *a)
        self._left -= n
        if self._left < 0:
            raise FetchRefused("too_large")
        return n

    def recv(self, n, *a):
        b = bytearray(min(n, 65536))
        k = self.recv_into(b, len(b))
        return bytes(b[:k])

    def makefile(self, mode="rb", *a, **kw):
        import io

        self._io_refs += 1
        return io.BufferedReader(socket.SocketIO(self, "rb"))

    def _decref_socketios(self):
        self._io_refs = max(0, self._io_refs - 1)
        if self._closed and not self._io_refs:
            self._s.close()

    def close(self):
        self._closed = True
        if not self._io_refs:
            self._s.close()

    def force_close(self):
        """Release the real socket once the exchange is over, whatever readers are still referenced."""
        self._closed, self._io_refs = True, 0
        close = getattr(self._s, "close", None)  # tests may wrap a bare stand-in
        if close:
            close()

    def __getattr__(self, name):
        return getattr(self._s, name)


def transport(host: str, ip: str, path: str, deadline: float) -> RawResponse:
    """One GET, no redirects followed, body capped at MAX_BYTES+1, hard deadline on every byte (replaced in tests)."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise FetchFailed("timeout")
    conn = _PinnedHTTPS(host, ip, timeout=remaining)
    guarded = None
    try:
        conn.connect()  # TCP + TLS handshake bounded by `remaining`
        conn.sock = guarded = _DeadlineSocket(conn.sock, deadline, MAX_BYTES + MAX_HEADER_BYTES + 1)
        conn.request(
            "GET",
            path,
            headers={
                "Host": host,
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Encoding": "identity",
                "Connection": "close",
            },
        )
        resp = conn.getresponse()
        raw = resp.getheaders()
        if len(raw) > MAX_HEADERS or sum(len(k) + len(v) for k, v in raw) > MAX_HEADER_BYTES:
            raise FetchRefused("too_large")
        headers = {k.lower(): v for k, v in raw}
        body = b""
        if resp.status == 200:
            chunks, size = [], 0
            while size <= MAX_BYTES:
                if time.monotonic() > deadline:
                    raise FetchFailed("timeout")
                part = resp.read1(65536) if hasattr(resp, "read1") else resp.read(65536)
                if not part:
                    break
                chunks.append(part)
                size += len(part)
            body = b"".join(chunks)
        return RawResponse(resp.status, headers, body)
    except TimeoutError:
        raise FetchFailed("timeout") from None
    except ssl.SSLError:
        raise FetchFailed("tls_error") from None
    except (OSError, http.client.HTTPException):
        raise FetchFailed(UNREACHABLE) from None
    finally:
        conn.close()
        release = getattr(
            guarded, "force_close", None
        )  # None before connect (or with a stub socket in tests)
        if release:
            release()


def fetch(url: str) -> Page:
    """GET a public https page as text. Raises FetchRefused (never will) or FetchFailed (not reachable yet)."""
    deadline = time.monotonic() + TIMEOUT_S
    for _ in range(MAX_REDIRECTS + 1):
        host, path = check_url(url)
        ip = safe_ip(host)
        if time.monotonic() > deadline:
            raise FetchFailed("timeout")
        r = transport(host, ip, path, deadline)
        if r.status in (301, 302, 303, 307, 308):
            loc = r.headers.get("location", "")
            if not loc:
                raise FetchFailed("bad_redirect")
            url = urljoin(f"https://{host}{path}", loc)  # re-validated (scheme, host, IPs) on the next loop
            continue
        if r.status != 200:
            raise FetchFailed(f"http_{r.status}" if 400 <= r.status < 600 else "unreachable")
        ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype not in ("text/html", "application/xhtml+xml"):
            raise FetchRefused("not_html")
        if r.headers.get("content-encoding", "identity").lower() not in ("", "identity"):
            raise FetchRefused("encoded_body")
        try:
            declared = int(r.headers.get("content-length", "0") or 0)
        except ValueError:
            declared = 0
        if declared > MAX_BYTES or len(r.body) > MAX_BYTES:
            raise FetchRefused("too_large")
        charset = "utf-8"
        for part in r.headers.get("content-type", "").split(";")[1:]:
            k, _, v = part.strip().partition("=")
            if k.lower() == "charset" and v.strip().strip('"'):
                charset = v.strip().strip('"')
        try:
            text = r.body.decode(charset, errors="replace")
        except LookupError:
            text = r.body.decode("utf-8", errors="replace")
        return Page(url=url, html=text)
    raise FetchFailed("too_many_redirects")


# ── JSON POST (MCP client for learner-connected servers) ──────────────
# Same pinned-IP HTTPS and URL/IP vetting as fetch(), but: one POST, never a redirect (3xx is an error), a ≤10 s
# deadline, a 256 KB response cap, and only an allow-listed set of request headers (never cookies).

POST_TIMEOUT_S = 10.0
POST_MAX_BYTES = 256 * 1024
POST_MAX_BODY = 64 * 1024
POST_USER_AGENT = "AasanWorkshopAgent/1.0 (+MCP client)"
_POST_HEADERS = {"accept", "content-type", "authorization", "mcp-session-id", "mcp-protocol-version"}
_HEADER_NAME_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")


def _post_headers(headers: dict) -> dict[str, str]:
    """Only allow-listed names (plus one learner `X-…` API-key header); values must be single-line and short."""
    out: dict[str, str] = {}
    for k, v in (headers or {}).items():
        name = str(k)
        low = name.lower()
        custom = low.startswith("x-") and 2 < len(name) <= 40 and set(name) <= _HEADER_NAME_OK
        if low not in _POST_HEADERS and not custom:
            raise FetchRefused("bad_header")
        value = str(v)
        if len(value) > 4000 or any(c in value for c in "\r\n\x00"):
            raise FetchRefused("bad_header")
        out[name] = value
    return out


def post_transport(
    host: str, ip: str, path: str, body: bytes, headers: dict[str, str], deadline: float, stop=None
) -> RawResponse:
    """One POST to the vetted IP; reads the response (any status) up to POST_MAX_BYTES+1 under the hard deadline.
    `stop(bytes_so_far)` may end the read early (an SSE stream that already carried our answer). Replaced in tests."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise FetchFailed("timeout")
    conn = _PinnedHTTPS(host, ip, timeout=remaining)
    guarded = None
    try:
        conn.connect()
        conn.sock = guarded = _DeadlineSocket(conn.sock, deadline, POST_MAX_BYTES + MAX_HEADER_BYTES + 1)
        conn.request(
            "POST",
            path,
            body=body,
            headers={
                **headers,
                "Host": host,
                "User-Agent": POST_USER_AGENT,
                "Accept-Encoding": "identity",
                "Content-Length": str(len(body)),
                "Connection": "close",
            },
        )
        resp = conn.getresponse()
        raw = resp.getheaders()
        if len(raw) > MAX_HEADERS or sum(len(k) + len(v) for k, v in raw) > MAX_HEADER_BYTES:
            raise FetchRefused("too_large")
        out_headers = {k.lower(): v for k, v in raw}
        chunks, size = [], 0
        while size <= POST_MAX_BYTES:
            if time.monotonic() > deadline:
                raise FetchFailed("timeout")
            part = resp.read1(65536) if hasattr(resp, "read1") else resp.read(65536)
            if not part:
                break
            chunks.append(part)
            size += len(part)
            if stop is not None and stop(b"".join(chunks)):
                break
        return RawResponse(resp.status, out_headers, b"".join(chunks))
    except TimeoutError:
        raise FetchFailed("timeout") from None
    except ssl.SSLError:
        raise FetchFailed("tls_error") from None
    except (OSError, http.client.HTTPException):
        raise FetchFailed(UNREACHABLE) from None
    finally:
        conn.close()
        release = getattr(
            guarded, "force_close", None
        )  # None before connect (or with a stub socket in tests)
        if release:
            release()


def post_json(
    url: str, body, headers: dict | None = None, deadline: float | None = None, stop=None
) -> RawResponse:
    """POST a JSON body to a public https URL. `body` is bytes or a JSON-serialisable value. Raises FetchRefused
    (bad_url, https_only, port_not_allowed, ip_not_allowed, private_address, bad_header, too_large, encoded_body) or
    FetchFailed (unreachable, timeout, tls_error, redirect). Redirects are never followed; no cookies are sent."""
    import json as _json

    data = body if isinstance(body, bytes) else _json.dumps(body, ensure_ascii=False).encode()
    if len(data) > POST_MAX_BODY:
        raise FetchRefused("too_large")
    hdrs = _post_headers(headers or {})
    hard = time.monotonic() + POST_TIMEOUT_S
    deadline = hard if deadline is None else min(deadline, hard)
    host, path = check_url(url)
    ip = safe_ip(host)  # re-resolved and vetted on every call, then pinned for this connection
    if time.monotonic() > deadline:
        raise FetchFailed("timeout")
    r = post_transport(host, ip, path, data, hdrs, deadline, stop)
    if 300 <= r.status < 400:
        raise FetchFailed("redirect")
    if r.headers.get("content-encoding", "identity").lower() not in ("", "identity"):
        raise FetchRefused("encoded_body")
    try:
        declared = int(r.headers.get("content-length", "0") or 0)
    except ValueError:
        declared = 0
    if declared > POST_MAX_BYTES or len(r.body) > POST_MAX_BYTES:
        raise FetchRefused("too_large")
    return r


# ── What's on the page ────────────────────────────────────────────────


class PageFacts(HTMLParser):
    """Visible text, heading texts, link hrefs/texts and image count. Never executes anything."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.headings: list[str] = []
        self.links: list[str] = []
        self.images = 0
        self._skip = 0
        self._heading: list[str] | None = None
        self._link_text: list[str] | None = None
        self._href = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "noscript", "template"):
            self._skip += 1
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading = []
        elif tag == "a":
            self._href, self._link_text = a.get("href") or "", []
        elif tag == "img" or (tag == "image" and (a.get("href") or a.get("xlink:href"))):
            self.images += 1
        if tag == "img" and a.get("alt"):
            self.text.append(a["alt"])

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template"):
            self._skip = max(0, self._skip - 1)
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._heading is not None:
            self.headings.append(" ".join("".join(self._heading).split()))
            self._heading = None
        elif tag == "a" and self._link_text is not None:
            self.links.append(f"{self._href} {' '.join(''.join(self._link_text).split())}".strip())
            self._link_text = None

    def handle_data(self, data):
        if self._skip:
            return
        self.text.append(data)
        if self._heading is not None:
            self._heading.append(data)
        if self._link_text is not None:
            self._link_text.append(data)


def page_facts(html: str) -> PageFacts:
    p = PageFacts()
    try:
        p.feed(html[:MAX_BYTES])
        p.close()
    except Exception:  # noqa: BLE001 — malformed markup: keep whatever was parsed
        logging.getLogger(__name__).info("artifact page: HTML parse stopped early")
    return p
