"""Load check for AI workshops: ~100 learner sockets on one institution run, measuring live-monitor tile latency.

    cd api && uv run python scripts/workshop_load.py [--learners 100] [--seconds 60] [--spacing 6]

Everything runs in this process: a throwaway SQLite database in a temp folder (migrated fresh), the in-memory channel
layer, the local-memory cache and the fake LLM provider. It never touches api/.env's database, Redis, mail, payment
or model keys: those variables are blanked before Django loads, and .env never overrides a variable already set.

Each learner socket authenticates, then acts every --spacing seconds (with jitter): attention changes, messages to
the host (a fake streamed AI turn plus a structured check), and now and then a raised hand. One owner's monitor socket
records when each learner's tile arrives. Reported:
  · fresh latency: action → tile, for actions whose tile went out at once (the learner's 5 s throttle window was free);
  · staleness: action → the next tile for that learner, whatever caused it (a throttled action waits for the next
    publish: another action or the 15 s clock tick);
  · raised-hand latency (urgent: sent at once, or as soon as the throttle window closes).
"""

import argparse
import asyncio
import atexit
import os
import random
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

API = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="aasan-workshop-load-"))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
SAFE_ENV = {
    "DJANGO_SETTINGS_MODULE": "config.settings",
    "DATABASE_URL": f"sqlite:///{TMP / 'load.sqlite3'}",
    "REDIS_URL": "",
    "CACHE_REDIS_URL": "",
    "LLM_FORCE_PROVIDER": "fake",
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    "SENTRY_DSN": "",
    "DJANGO_ALLOWED_HOSTS": "localhost",
    "FRONTEND_URL": "http://localhost:5173",
}
for _k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "SARVAM_API_KEY", "GOOGLE_CLOUD_API_KEY"):
    SAFE_ENV[_k] = ""
for _k in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
    SAFE_ENV[_k] = ""
os.environ.update(SAFE_ENV)  # set before Django: load_dotenv() never overrides a variable that is already set
sys.path.insert(0, str(API))

import django

django.setup()

from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

HEADERS = [(b"host", b"localhost"), (b"origin", b"http://localhost:5173")]
FOREVER = 24 * 3600


def _guard():
    db = settings.DATABASES["default"]
    assert db["ENGINE"].endswith("sqlite3") and str(db["NAME"]).startswith(str(TMP)), db["NAME"]
    assert "InMemoryChannelLayer" in settings.CHANNEL_LAYERS["default"]["BACKEND"]
    assert "locmem" in settings.CACHES["default"]["BACKEND"]
    settings.LLM_FORCE_PROVIDER = "fake"
    settings.EMAIL_FALLBACK_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


def _setup(n: int) -> dict:
    from datetime import timedelta

    from rest_framework_simplejwt.tokens import AccessToken

    from apps.accounts.models import User
    from apps.orgs.models import Group, Membership, Organization
    from apps.workshops import services
    from apps.workshops.content import seed
    from apps.workshops.models import Workshop, WorkshopEnrollment, WorkshopRun, WorkshopSession

    call_command("migrate", verbosity=0)
    seed()
    org = Organization.objects.create(
        name="Load School", slug="load-school", features={"workshops": True}, workshop_seats=n + 10
    )
    group = Group.objects.create(org=org, name="All")
    owner = User.objects.create_user("owner@load.test", None)
    Membership.objects.create(org=org, user=owner, role="owner")
    run = WorkshopRun.objects.create(
        workshop=Workshop.objects.get(slug="prompt-engineering"),
        audience="org",
        org=org,
        starts_at=timezone.now() - timedelta(minutes=1),
        status="live",
        proctoring="activity",
    )
    run.groups.set([group])
    learners = []
    for i in range(n):
        u = User.objects.create_user(f"learner{i:03d}@load.test", None)
        u.profile.display_name = f"Learner {i:03d}"
        u.profile.save()
        m = Membership.objects.create(org=org, user=u, role="learner", fields={"roll_no": f"L{i:03d}"})
        group.members.add(m)
        e = WorkshopEnrollment.objects.create(run=run, user=u)
        s = WorkshopSession.objects.create(enrollment=e, user=u, run=run)
        s.prereqs_done = {p["key"]: "x" for p in run.workshop.prerequisites}
        s.save()
        assert services.start(s) is None
        learners.append({"sid": s.id, "token": str(AccessToken.for_user(u))})
    return {"run": run.id, "owner": str(AccessToken.for_user(owner)), "learners": learners}


def pct(vals, p):
    if not vals:
        return float("nan")
    vals = sorted(vals)
    k = max(0, min(len(vals) - 1, round(p / 100 * (len(vals) - 1))))
    return vals[k]


def line(name, vals):
    if not vals:
        return f"{name:<34} n=0"
    ms = [v * 1000 for v in vals]
    return (
        f"{name:<34} n={len(ms):<5} p50={pct(ms, 50):7.1f} ms  p95={pct(ms, 95):7.1f} ms  "
        f"p99={pct(ms, 99):7.1f} ms  max={max(ms):7.1f} ms  mean={statistics.fmean(ms):7.1f} ms"
    )


async def main(args):
    from config.asgi import application

    _guard()
    t0 = time.perf_counter()
    world = await sync_to_async(_setup)(args.learners)
    print(f"setup: {args.learners} learners, run #{world['run']} in {time.perf_counter() - t0:.1f}s ({TMP})")

    # sid → {"t": first action not yet shown on a tile, "fresh": tile due at once, "hand": raised-hand time or None}
    pending: dict[int, dict] = {}
    fresh, stale, hands, tiles = [], [], [], {"total": 0, "unsolicited": 0}
    last_tile: dict[int, float] = {}
    errors: dict[str, int] = {}
    stop = asyncio.Event()

    # Monitor (owner): snapshot, then tiles.
    mon = WebsocketCommunicator(application, f"/ws/workshop-runs/{world['run']}/monitor/", headers=HEADERS)
    assert (await mon.connect())[0]
    t = time.perf_counter()
    await mon.send_json_to({"type": "auth", "token": world["owner"]})
    assert (await mon.receive_json_from(timeout=30))["type"] == "ready"
    snap = await mon.receive_json_from(timeout=30)
    assert snap["type"] == "snapshot", snap
    print(
        f"monitor snapshot: {len(snap.get('tiles') or [])} tiles in {(time.perf_counter() - t) * 1000:.0f} ms"
    )

    # Never let a receive time out: the test communicator cancels the app on a timeout. Readers are cancelled at the end.
    async def watch():
        while True:
            msg = await mon.receive_json_from(timeout=FOREVER)
            if msg.get("type") != "tile":
                continue
            now = time.perf_counter()
            sid = msg["tile"]["session_id"]
            tiles["total"] += 1
            last_tile[sid] = now
            p = pending.pop(sid, None)
            if not p:
                tiles["unsolicited"] += 1  # the 15 s clock tick, or an AI turn finishing
                continue
            stale.append(now - p["t"])
            if p["fresh"]:
                fresh.append(now - p["t"])
            if p["hand"] is not None and msg["tile"].get("raised_hand"):
                hands.append(now - p["hand"])
            elif p["hand"] is not None:
                pending[sid] = {"t": p["hand"], "fresh": False, "hand": p["hand"]}

    # Learners.
    socks = {}
    t = time.perf_counter()
    for lr in world["learners"]:
        c = WebsocketCommunicator(application, f"/ws/workshop/{lr['sid']}/", headers=HEADERS)
        assert (await c.connect())[0]
        await c.send_json_to({"type": "auth", "token": lr["token"]})
        socks[lr["sid"]] = c
    ready = 0
    for c in socks.values():
        while True:
            m = await c.receive_json_from(timeout=30)
            if m["type"] == "ready":
                ready += 1
                break
    print(f"learners connected + ready: {ready}/{len(socks)} in {(time.perf_counter() - t):.1f}s")
    watcher = asyncio.create_task(watch())

    idle = {sid: asyncio.Event() for sid in socks}

    async def drain(sid, c):
        idle[sid].set()
        while True:
            m = await c.receive_json_from(timeout=FOREVER)
            kind = m.get("type")
            if kind == "start":
                idle[sid].clear()
            elif kind in ("done", "paused"):
                idle[sid].set()
            elif kind == "error":
                errors[m.get("code", "?")] = errors.get(m.get("code", "?"), 0) + 1
                idle[sid].set()

    def note(sid, hand=False):
        now = time.perf_counter()
        window_free = now - last_tile.get(sid, -1e9) > 5.05  # monitor.THROTTLE_SECONDS
        p = pending.get(sid)
        if p is None:
            pending[sid] = {"t": now, "fresh": window_free, "hand": now if hand else None}
        elif hand and p["hand"] is None:
            p["hand"] = now

    async def learner(sid, c):
        rng = random.Random(sid)
        await asyncio.sleep(rng.uniform(0, args.spacing))
        hidden = False
        n = 0
        while not stop.is_set():
            n += 1
            roll = rng.random()
            if roll < 0.08:
                note(sid, hand=True)
                await c.send_json_to({"type": "raise_hand"})
            elif roll < 0.45 and idle[sid].is_set():
                idle[sid].clear()
                note(sid)
                await c.send_json_to(
                    {"type": "say", "text": f"I think it means the AI predicts words ({n})."}
                )
            else:
                hidden = not hidden
                note(sid)
                await c.send_json_to({"type": "attention", "kind": "hidden" if hidden else "visible"})
            await asyncio.sleep(args.spacing * rng.uniform(0.85, 1.25))

    drains = [asyncio.create_task(drain(sid, c)) for sid, c in socks.items()]
    t = time.perf_counter()
    actors = [asyncio.create_task(learner(sid, c)) for sid, c in socks.items()]
    await asyncio.sleep(args.seconds)
    stop.set()
    elapsed = time.perf_counter() - t
    for task in (*actors, watcher, *drains):
        task.cancel()
    await asyncio.gather(*actors, watcher, *drains, return_exceptions=True)
    for c in socks.values():
        await c.disconnect()
    await mon.disconnect()

    print(f"\nload: {len(socks)} learners for {elapsed:.0f}s, action every ~{args.spacing}s each")
    print(
        f"tiles received by the monitor: {tiles['total']} ({tiles['unsolicited']} from clock ticks / AI turns)"
    )
    print(line("fresh latency (action → tile)", fresh))
    print(line("staleness (action → next tile)", stale))
    print(line("raised hand → tile", hands))
    print(f"actions still waiting for a tile at the end: {len(pending)}")
    print(f"learner-side errors: {errors or 'none'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--learners", type=int, default=100)
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--spacing", type=float, default=6.0, help="seconds between one learner's actions")
    asyncio.run(main(ap.parse_args()))
