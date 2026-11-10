"""Load test for a running Aasan stack: virtual learners over HTTP and WebSockets.

    # 1. Seed accounts on the target stack (writes JWTs to a mode-600 file; never production):
    uv run python manage.py seed_load_users --count 600 --prefix load --out /tmp/load-tokens.json \\
        --create-workshop-run --course auto --i-know-this-is-not-production [--allow-non-debug]
    # 2. Run (the API must use LLM_FORCE_PROVIDER=fake; set LLM_FAKE_DELAY_MS / LLM_FAKE_TOKEN_MS for real latency):
    uv run python scripts/load_test.py --base http://localhost:8080 --users 500 --ramp 60 --duration 300 \\
        --tokens /tmp/load-tokens.json --mix default --out load-result.json
    # Quick check (5 users, 20 s, at least one mentor and one workshop socket):
    uv run python scripts/load_test.py --base http://127.0.0.1:8000 --origin http://localhost:5173 \\
        --tokens /tmp/load-tokens.json --smoke

Each virtual user (VU) is one seeded learner. VUs start evenly over --ramp seconds and run until --duration ends:
  · reader VUs load the home page (me, game status, today), then cycle through the main reads with think time:
    learn list, a course, its first lesson, catalog, continue, review overview/session, paths, notifications,
    workshops, certificates;
  · mentor VUs open /ws/assistant/, then send a message, wait for `done`, think, repeat;
  · workshop VUs (need `session_id` in the token file: seed with --create-workshop-run or --workshop-run) open
    /ws/workshop/<id>/, wait for the host's opening turn, then send `say` (mostly) or `next`, each waiting for `done`.
Reported: per-endpoint and per-socket-op p50/p95/p99, errors by status or code, throughput, socket connect time and
failures. A JSON result goes to --out and a summary table to stdout. Tokens are never printed or written to the
result; if access tokens are too close to expiry they are refreshed and the token file is rewritten (mode 600).

Exit code: 0 when the error rate is within --max-error-rate (smoke: no errors at all), else 1.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import os
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import websockets
from websockets.asyncio.client import connect as ws_connect

MIXES = {  # share of VUs that are mentor-socket / workshop-socket users; the rest are readers
    "default": (0.20, 0.20),
    "read-heavy": (0.05, 0.05),
    "chat-heavy": (0.40, 0.30),
    "reads-only": (0.0, 0.0),
}
# Workshop codes that are part of the normal flow, not failures (the host hasn't explained the item yet, or the
# learner is at the final stage).
WORKSHOP_FLOW_CODES = {"not_explained", "at_final"}
MENTOR_PROMPTS = [
    "Explain what a prompt is in one line.",
    "Give me one tip to remember Python lists.",
    "What should I study next?",
    "Quiz me with one quick question.",
]
WORKSHOP_SAYS = [
    "I think it means the AI predicts the next words.",
    "Can you give me an example?",
    "I've done that step.",
    "What does that mean in simple words?",
]


# ── metrics ──────────────────────────────────────────────────────────
@dataclass
class Stats:
    lat: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    ok: Counter = field(default_factory=Counter)
    errors: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    flow: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))  # expected app codes
    http_requests: int = 0
    first_at: float | None = None
    last_at: float | None = None

    def hit(self, name: str, seconds: float):
        self.lat[name].append(seconds)
        self.ok[name] += 1

    def err(self, name: str, code: str):
        self.errors[name][str(code)[:60]] += 1


def pct(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    k = max(0, min(len(s) - 1, round(p / 100 * (len(s) - 1))))
    return s[k]


def jwt_exp(token: str) -> float:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
    except (ValueError, KeyError, IndexError, TypeError):
        return 0.0


def scrub(text: str) -> str:
    """Never let a token end up in output: drop anything that looks like a JWT."""
    return " ".join("<redacted>" if w.startswith("eyJ") else w for w in str(text).split())[:120]


# ── virtual users ────────────────────────────────────────────────────
class VU:
    def __init__(self, idx: int, cred: dict, role: str, cfg, client: httpx.AsyncClient, stats: Stats):
        self.idx, self.cred, self.role, self.cfg, self.client, self.stats = (
            idx,
            cred,
            role,
            cfg,
            client,
            stats,
        )
        self.rng = random.Random(idx * 7919 + 17)
        self.course_id = cred.get("course_id")
        self.lesson_id = None

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.cred['access']}"}

    async def think(self, lo=None, hi=None):
        await asyncio.sleep(self.rng.uniform(lo or self.cfg.think_min, hi or self.cfg.think_max))

    def time_left(self) -> bool:
        return time.monotonic() < self.cfg.deadline

    async def get(self, name: str, path: str):
        t = time.perf_counter()
        self.stats.http_requests += 1
        try:
            r = await self.client.get(path, headers=self.headers)
        except httpx.TimeoutException:
            self.stats.err(name, "timeout")
            return None
        except httpx.HTTPError as e:
            self.stats.err(name, type(e).__name__)
            return None
        dt = time.perf_counter() - t
        if r.status_code >= 400:
            self.stats.err(name, r.status_code)
            return None
        self.stats.hit(name, dt)
        try:
            return r.json()
        except ValueError:
            return None

    async def post(self, name: str, path: str, body: dict):
        t = time.perf_counter()
        self.stats.http_requests += 1
        try:
            r = await self.client.post(path, headers=self.headers, json=body)
        except httpx.HTTPError as e:
            self.stats.err(name, "timeout" if isinstance(e, httpx.TimeoutException) else type(e).__name__)
            return None
        if r.status_code >= 400:
            self.stats.err(name, r.status_code)
            return None
        self.stats.hit(name, time.perf_counter() - t)
        try:
            return r.json()
        except ValueError:
            return None

    async def run(self):
        try:
            if self.role == "mentor":
                await self.mentor()
            elif self.role == "workshop":
                await self.workshop()
            else:
                await self.reader()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — a harness bug must not kill the run silently
            self.stats.err(f"vu_{self.role}", f"crash:{type(e).__name__}:{scrub(e)}")

    # ── reader ──
    async def home(self):
        await self.get("GET /api/users/me/", "/api/users/me/")
        await self.get("GET /api/game/status/", "/api/game/status/")
        await self.get("GET /api/study/today/", "/api/study/today/")

    async def open_course(self):
        if not self.course_id:
            courses = await self.get("GET /api/learn/curriculums/", "/api/learn/curriculums/")
            if isinstance(courses, list) and courses:
                self.course_id = courses[0].get("id")
        if not self.course_id:
            return
        cur = await self.get("GET /api/learn/curriculums/<id>/", f"/api/learn/curriculums/{self.course_id}/")
        if isinstance(cur, dict) and self.lesson_id is None:
            for s in cur.get("sections") or []:
                subs = s.get("subsections") or []
                if subs and subs[0].get("id"):
                    self.lesson_id = subs[0]["id"]
                    break
            else:
                self.lesson_id = 0  # nothing to open; don't look again

    async def open_lesson(self):
        if self.lesson_id is None:
            await self.open_course()
        if self.lesson_id:
            await self.get("GET /api/learn/subsections/<id>/", f"/api/learn/subsections/{self.lesson_id}/")

    def reads(self):
        g = self.get
        return [
            (3, lambda: g("GET /api/users/me/", "/api/users/me/")),
            (3, lambda: g("GET /api/game/status/", "/api/game/status/")),
            (3, lambda: g("GET /api/study/today/", "/api/study/today/")),
            (2, lambda: g("GET /api/learn/curriculums/", "/api/learn/curriculums/")),
            (2, self.open_course),
            (2, self.open_lesson),
            (1, lambda: g("GET /api/catalog/", "/api/catalog/")),
            (1, lambda: g("GET /api/learn/continue/", "/api/learn/continue/")),
            (2, lambda: g("GET /api/review/overview/", "/api/review/overview/")),
            (1, lambda: g("GET /api/review/session/", "/api/review/session/")),
            (1, lambda: g("GET /api/paths/skills/", "/api/paths/skills/")),
            (1, lambda: g("GET /api/paths/curated/", "/api/paths/curated/")),
            (2, lambda: g("GET /api/game/notifications/", "/api/game/notifications/")),
            (1, lambda: g("GET /api/workshops/runs/", "/api/workshops/runs/")),
            (1, lambda: g("GET /api/credentials/", "/api/credentials/")),
        ]

    async def reader(self):
        await self.home()
        actions = self.reads()
        weights = [w for w, _ in actions]
        while self.time_left():
            await self.think()
            if not self.time_left():
                break
            await self.rng.choices(actions, weights)[0][1]()

    # ── sockets ──
    async def open_ws(self, op: str, path: str):
        """Connect + auth → (socket, ready message) or (None, None). Records connect and auth times."""
        url = self.cfg.ws_base + path
        t = time.perf_counter()
        try:
            ws = await asyncio.wait_for(
                ws_connect(
                    url,
                    origin=self.cfg.origin,
                    open_timeout=30,
                    close_timeout=3,
                    max_size=2**22,
                    ping_interval=20,
                ),
                timeout=35,
            )
        except Exception as e:  # noqa: BLE001 — refused handshakes, DNS, TLS, timeouts
            code = getattr(getattr(e, "response", None), "status_code", None)
            self.stats.err(f"WS {op} connect", code or type(e).__name__)
            return None, None
        self.stats.hit(f"WS {op} connect", time.perf_counter() - t)
        t = time.perf_counter()
        await ws.send(json.dumps({"type": "auth", "token": self.cred["access"]}))
        try:
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                if m.get("type") == "ready":
                    self.stats.hit(f"WS {op} auth→ready", time.perf_counter() - t)
                    return ws, m
                if m.get("type") == "error":
                    self.stats.err(f"WS {op} auth→ready", m.get("code") or "error")
                    await ws.close()
                    return None, None
        except TimeoutError:
            self.stats.err(f"WS {op} auth→ready", "timeout")
        except websockets.ConnectionClosed as e:
            self.stats.err(f"WS {op} auth→ready", f"closed:{e.rcvd.code if e.rcvd else '?'}")
        with contextlib.suppress(Exception):
            await ws.close()
        return None, None

    async def settle(self, ws, op: str) -> bool:
        """Consume anything already queued (an unsolicited host turn, pace ticks) so the next reply we time is the
        answer to our own message. → False if the socket closed."""
        while True:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=0.3))
            except TimeoutError:
                return True
            except websockets.ConnectionClosed as e:
                self.stats.err(f"WS {op}", f"closed:{e.rcvd.code if e.rcvd else '?'}")
                return False
            if (
                m.get("type") == "start"
                and await self.turn(ws, op, time.perf_counter(), record=False) == "closed"
            ):
                return False

    async def turn(self, ws, op: str, t0: float, stop_on_progress: bool = False, record: bool = True) -> str:
        """Read one streamed reply: → "done" | "error" | "paused" | "closed" | "timeout" | "quiet".
        Records time to first delta and to done."""
        first = None
        try:
            while True:
                left = self.cfg.reply_timeout - (time.perf_counter() - t0)
                if left <= 0:
                    raise TimeoutError
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=left))
                kind = m.get("type")
                if kind == "delta" and first is None:
                    first = time.perf_counter()
                    if record:
                        self.stats.hit(f"WS {op} first token", first - t0)
                elif kind == "done":
                    if record:
                        self.stats.hit(f"WS {op} reply (to done)", time.perf_counter() - t0)
                    return "done"
                elif kind == "error":
                    code = m.get("code") or "error"
                    if code in WORKSHOP_FLOW_CODES:
                        self.stats.flow[f"WS {op}"][code] += 1
                        return "quiet"
                    self.stats.err(f"WS {op}", code)
                    return "error"
                elif kind == "paused":
                    self.stats.flow[f"WS {op}"][f"paused:{m.get('reason')}"] += 1
                    return "paused"
                elif kind == "progress" and stop_on_progress and first is None:
                    # `next` that advanced without a host remark: wait briefly for a turn, else it's done
                    with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                        nxt = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                        if nxt.get("type") == "start":
                            continue
                    self.stats.hit(f"WS {op} reply (to done)", time.perf_counter() - t0)
                    return "done"
        except TimeoutError:
            self.stats.err(f"WS {op}", "reply_timeout")
            return "timeout"
        except websockets.ConnectionClosed as e:
            self.stats.err(f"WS {op}", f"closed:{e.rcvd.code if e.rcvd else '?'}")
            return "closed"

    async def mentor(self):
        await self.get("GET /api/users/me/", "/api/users/me/")
        await self.get("GET /api/assistant/conversations/", "/api/assistant/conversations/")
        ws, _ = await self.open_ws("mentor", "/ws/assistant/")
        if not ws:
            return
        conv = None
        try:
            while self.time_left():
                await self.think(self.cfg.chat_think_min, self.cfg.chat_think_max)
                if not self.time_left():
                    break
                t0 = time.perf_counter()
                await ws.send(
                    json.dumps(
                        {"type": "message", "text": self.rng.choice(MENTOR_PROMPTS), "conversation_id": conv}
                    )
                )
                m: dict = {}
                try:  # the reply opens with `start` (carrying the conversation id) unless it's refused
                    while m.get("type") not in ("start", "error"):
                        m = json.loads(await asyncio.wait_for(ws.recv(), timeout=self.cfg.reply_timeout))
                except TimeoutError:
                    self.stats.err("WS mentor", "reply_timeout")
                    continue
                except websockets.ConnectionClosed as e:
                    self.stats.err("WS mentor", f"closed:{e.rcvd.code if e.rcvd else '?'}")
                    break
                if m["type"] == "error":
                    self.stats.err("WS mentor", m.get("code") or "error")
                    if m.get("code") == "plan_limit":
                        break  # the free plan's daily cap: re-seed to reset it
                    continue
                conv = m.get("conversation_id") or conv
                if await self.turn(ws, "mentor", t0) == "closed":
                    break
        finally:
            with contextlib.suppress(Exception):
                await ws.close()

    async def workshop(self):
        sid = self.cred.get("session_id")
        if not sid:
            return await self.reader()
        await self.get("GET /api/workshops/sessions/<id>/", f"/api/workshops/sessions/{sid}/")
        ws, _ready = await self.open_ws("workshop", f"/ws/workshop/{sid}/")
        if not ws:
            return
        try:
            # `ready` is followed by a `pace` tick and, usually, the host's opening turn: time that turn, if it comes.
            t0 = time.perf_counter()
            with contextlib.suppress(TimeoutError):
                while time.perf_counter() - t0 < 5:
                    m = json.loads(await asyncio.wait_for(ws.recv(), timeout=5 - (time.perf_counter() - t0)))
                    if m.get("type") == "start":
                        await self.turn(ws, "workshop opening", t0)
                        break
            while self.time_left():
                await self.think(self.cfg.chat_think_min, self.cfg.chat_think_max)
                if not self.time_left():
                    break
                if not await self.settle(ws, "workshop"):
                    break
                t0 = time.perf_counter()
                if self.rng.random() < 0.75:
                    await ws.send(json.dumps({"type": "say", "text": self.rng.choice(WORKSHOP_SAYS)}))
                    res = await self.turn(ws, "workshop say", t0)
                else:
                    await ws.send(json.dumps({"type": "next"}))
                    res = await self.turn(ws, "workshop next", t0, stop_on_progress=True)
                if res in ("closed", "paused"):
                    break
        finally:
            with contextlib.suppress(Exception):
                await ws.close()


# ── setup ────────────────────────────────────────────────────────────
async def refresh_tokens(creds: list[dict], cfg, client: httpx.AsyncClient) -> int:
    """Refresh access tokens that would expire before the run ends. → how many were refreshed."""
    need_until = time.time() + cfg.ramp + cfg.duration + 120
    stale = [c for c in creds if jwt_exp(c["access"]) < need_until]
    sem = asyncio.Semaphore(20)

    async def one(c):
        async with sem:
            r = await client.post("/api/users/refresh-token/", json={"refresh": c["refresh"]})
            if r.status_code != 200:
                raise SystemExit(
                    f"token refresh failed for {c['email']} ({r.status_code}); re-run seed_load_users"
                )
            c["access"] = r.json()["access"]
            new = r.cookies.get("aasan_refresh") or next(
                (
                    h.split(";", 1)[0].split("=", 1)[1]
                    for h in r.headers.get_list("set-cookie")
                    if h.startswith("aasan_refresh=")
                ),
                None,
            )
            if new:
                c["refresh"] = new

    await asyncio.gather(*(one(c) for c in stale))
    return len(stale)


def save_tokens(path: Path, creds: list[dict]):
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(creds, f)
    os.replace(tmp, path)


def assign_roles(creds: list[dict], n: int, mentor_share: float, workshop_share: float, smoke: bool):
    n_m = round(n * mentor_share)
    n_w = round(n * workshop_share)
    if smoke and n >= 3:
        n_m, n_w = max(n_m, 1), max(n_w, 1)
    roles = []
    for i in range(n):
        if i < n_m:
            roles.append("mentor")
        elif i < n_m + n_w and creds[i].get("session_id"):
            roles.append("workshop")
        else:
            roles.append("reader")
    return roles


def summarize(stats: Stats, cfg, elapsed: float, roles: Counter) -> dict:
    rows = {}
    for name in sorted(set(stats.lat) | set(stats.errors)):
        vals = stats.lat.get(name, [])
        errs = sum(stats.errors.get(name, Counter()).values())
        rows[name] = {
            "ok": len(vals),
            "errors": errs,
            "error_codes": dict(stats.errors.get(name, Counter())),
            "p50_ms": _ms(pct(vals, 50)),
            "p95_ms": _ms(pct(vals, 95)),
            "p99_ms": _ms(pct(vals, 99)),
            "max_ms": _ms(max(vals) if vals else None),
            "mean_ms": _ms(statistics.fmean(vals) if vals else None),
            "rps": round(len(vals) / elapsed, 2) if elapsed else None,
        }
    http = {k: v for k, v in rows.items() if not k.startswith(("WS ", "vu_"))}
    http_ok = sum(r["ok"] for r in http.values())
    http_err = sum(r["errors"] for r in http.values())
    all_err = sum(r["errors"] for r in rows.values())
    all_ops = sum(r["ok"] for r in rows.values()) + all_err
    ws_connect = {k: v for k, v in rows.items() if k.endswith(" connect")}
    return {
        "config": {
            "base": cfg.base,
            "users": cfg.users,
            "ramp_s": cfg.ramp,
            "duration_s": cfg.duration,
            "mix": cfg.mix,
            "roles": dict(roles),
            "smoke": cfg.smoke,
        },
        "elapsed_s": round(elapsed, 1),
        "http": {
            "requests": http_ok + http_err,
            "ok": http_ok,
            "errors": http_err,
            "throughput_rps": round((http_ok + http_err) / elapsed, 2) if elapsed else None,
        },
        "sockets": {
            "connects_ok": sum(v["ok"] for v in ws_connect.values()),
            "connect_failures": sum(v["errors"] for v in ws_connect.values()),
        },
        "ops_total": all_ops,
        "errors_total": all_err,
        "error_rate": round(all_err / all_ops, 4) if all_ops else 0.0,
        "flow_codes": {k: dict(v) for k, v in stats.flow.items()},
        "endpoints": rows,
    }


def _ms(v):
    return None if v is None else round(v * 1000, 1)


def print_table(res: dict):
    c = res["config"]
    print(
        f"\nAasan load test · {c['base']} · {c['users']} users ({', '.join(f'{k} {v}' for k, v in c['roles'].items())})"
        f" · ramp {c['ramp_s']}s · ran {res['elapsed_s']}s"
    )
    h = f"{'endpoint / socket op':<44}{'ok':>7}{'err':>6}{'p50':>9}{'p95':>9}{'p99':>9}{'max':>9}{'rps':>8}"
    print(h)
    print("─" * len(h))

    def f(v):
        return "-" if v is None else f"{v:.0f}"

    for name, r in res["endpoints"].items():
        print(
            f"{name[:43]:<44}{r['ok']:>7}{r['errors']:>6}{f(r['p50_ms']):>9}{f(r['p95_ms']):>9}"
            f"{f(r['p99_ms']):>9}{f(r['max_ms']):>9}{r['rps'] or 0:>8.2f}"
        )
    print("─" * len(h))
    hh = res["http"]
    print(
        f"HTTP: {hh['requests']} requests, {hh['errors']} errors, {hh['throughput_rps']} req/s · "
        f"sockets: {res['sockets']['connects_ok']} connected, {res['sockets']['connect_failures']} failed · "
        f"error rate {res['error_rate'] * 100:.2f}%  (latencies in ms)"
    )
    errs = {k: v["error_codes"] for k, v in res["endpoints"].items() if v["error_codes"]}
    if errs:
        print("errors by code:")
        for k, v in errs.items():
            print(f"  {k}: {v}")
    if res["flow_codes"]:
        print(f"expected flow codes (not errors): {res['flow_codes']}")


async def main(cfg) -> int:
    path = Path(cfg.tokens).expanduser()
    creds = json.loads(path.read_text())
    if not isinstance(creds, list) or not creds:
        raise SystemExit("token file is empty; run seed_load_users first")
    if cfg.users > len(creds):
        raise SystemExit(f"--users {cfg.users} but the token file has only {len(creds)} accounts")
    creds_used = creds[: cfg.users]

    limits = httpx.Limits(max_connections=cfg.users + 20, max_keepalive_connections=cfg.users + 20)
    headers = {"Origin": cfg.origin, "User-Agent": "aasan-load-test/1"}
    async with httpx.AsyncClient(
        base_url=cfg.base, timeout=cfg.http_timeout, limits=limits, headers=headers
    ) as client:
        try:
            r = await client.get("/api/health/")
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise SystemExit(f"{cfg.base}/api/health/ is not answering: {scrub(e)}") from None
        refreshed = await refresh_tokens(creds_used, cfg, client)
        if refreshed:
            save_tokens(path, creds)
            print(f"refreshed {refreshed} access tokens (token file rewritten)")

        mentor_share, workshop_share = MIXES[cfg.mix]
        if cfg.mentor_share is not None:
            mentor_share = cfg.mentor_share
        if cfg.workshop_share is not None:
            workshop_share = cfg.workshop_share
        roles = assign_roles(creds_used, cfg.users, mentor_share, workshop_share, cfg.smoke)
        if workshop_share and not any(c.get("session_id") for c in creds_used):
            print("note: no session_id in the token file, so workshop VUs act as readers (seed with a run)")

        stats = Stats()
        start = time.monotonic()
        cfg.deadline = start + cfg.duration
        vus = [VU(i, c, roles[i], cfg, client, stats) for i, c in enumerate(creds_used)]

        async def launch(vu: VU):
            await asyncio.sleep(cfg.ramp * vu.idx / max(1, cfg.users))
            await vu.run()

        print(
            f"running {cfg.users} VUs against {cfg.base} for {cfg.duration}s (ramp {cfg.ramp}s): "
            + ", ".join(f"{k} {v}" for k, v in Counter(roles).items())
        )
        tasks = [asyncio.create_task(launch(v)) for v in vus]
        progress = asyncio.create_task(_progress(stats, cfg, start))
        # Grace period after the deadline for in-flight replies, then cancel stragglers.
        _done, pending = await asyncio.wait(tasks, timeout=(cfg.deadline - start) + cfg.reply_timeout + 10)
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        progress.cancel()
        elapsed = time.monotonic() - start

    res = summarize(stats, cfg, elapsed, Counter(roles))
    out = Path(cfg.out or f"load-result-{time.strftime('%Y%m%d-%H%M%S')}.json")
    out.write_text(json.dumps(res, indent=2))
    print_table(res)
    print(f"result: {out}")
    if cfg.smoke:
        return 0 if res["errors_total"] == 0 else 1
    return 0 if res["error_rate"] <= cfg.max_error_rate else 1


async def _progress(stats: Stats, cfg, start: float):
    if cfg.quiet:
        return
    while True:
        await asyncio.sleep(10)
        errs = sum(sum(c.values()) for c in stats.errors.values())
        print(f"  t={time.monotonic() - start:5.0f}s  http={stats.http_requests}  errors={errs}", flush=True)


def parse(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="http://localhost:8080", help="API origin (nginx or the API server)")
    ap.add_argument("--origin", default="", help="Origin header for sockets (default: --base)")
    ap.add_argument("--users", type=int, default=500)
    ap.add_argument("--ramp", type=float, default=60, help="seconds over which VUs start")
    ap.add_argument("--duration", type=float, default=300, help="seconds from the first VU start to the end")
    ap.add_argument("--tokens", required=True, help="token file from seed_load_users")
    ap.add_argument("--mix", choices=sorted(MIXES), default="default")
    ap.add_argument("--mentor-share", type=float, default=None)
    ap.add_argument("--workshop-share", type=float, default=None)
    ap.add_argument("--think-min", type=float, default=2.0)
    ap.add_argument("--think-max", type=float, default=6.0)
    ap.add_argument("--chat-think-min", type=float, default=10.0)
    ap.add_argument("--chat-think-max", type=float, default=25.0)
    ap.add_argument("--reply-timeout", type=float, default=90.0, help="seconds to wait for a socket reply")
    ap.add_argument("--http-timeout", type=float, default=30.0)
    ap.add_argument("--max-error-rate", type=float, default=0.01)
    ap.add_argument("--out", default="", help="JSON result path")
    ap.add_argument(
        "--smoke", action="store_true", help="5 users for 20 s, mentor and workshop sockets included"
    )
    ap.add_argument("--quiet", action="store_true")
    cfg = ap.parse_args(argv)
    if cfg.smoke:
        cfg.users, cfg.ramp, cfg.duration = 5, 2.0, 20.0
        cfg.think_min, cfg.think_max = 0.5, 1.5
        cfg.chat_think_min, cfg.chat_think_max = 1.0, 3.0
    cfg.base = cfg.base.rstrip("/")
    parts = urlsplit(cfg.base)
    cfg.origin = (cfg.origin or f"{parts.scheme}://{parts.netloc}").rstrip("/")
    cfg.ws_base = ("wss" if parts.scheme == "https" else "ws") + f"://{parts.netloc}"
    if cfg.users < 1:
        ap.error("--users must be at least 1")
    return cfg


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse())))
