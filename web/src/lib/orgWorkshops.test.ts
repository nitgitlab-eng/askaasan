import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  applyTiles, blankOrgRunForm, countByStatus, filterTiles, FLUSH_MS, normStatus, sortTiles, splitRuns, useMonitorSocket, validateOrgRunForm,
  type OrgRun, type Tile,
} from "./orgWorkshops";

vi.mock("./api", async (orig) => ({ ...(await orig<typeof import("./api")>()), ensureFreshAccess: vi.fn(async () => `tok-${++n}`) }));
let n = 0;

const tile = (id: number, over: Partial<Tile> = {}): Tile => ({
  session_id: id, learner: { id: 100 + id, name: `Learner ${id}` }, status: "engaged", stage: { index: 0, title: "Intro", kind: "teach" },
  diy: null, score_so_far: null, attention: null, help_summaries: [], raised_hand: false, last_activity_at: null, pace: "on_track", ...over,
});

const NOW = Date.parse("2026-10-18T06:00:00Z");

describe("schedule form validation", () => {
  it("flags every missing field and builds nothing", () => {
    const { errors, body } = validateOrgRunForm({ ...blankOrgRunForm(), late_join_minutes: "99", lobby_opens_minutes: "1" }, NOW);
    expect(body).toBeNull();
    expect(errors).toEqual({ workshop_slug: "template", date: "when", groups: "audience", late_join_minutes: "late", lobby_opens_minutes: "lobby" });
  });

  it("refuses a start time in the past (IST)", () => {
    const { errors } = validateOrgRunForm({ ...blankOrgRunForm(), workshop_slug: "quick-check", date: "2026-10-18", time: "09:00", groups: [1] }, NOW);
    expect(errors.date).toBe("past"); // 09:00 IST = 03:30 UTC, before NOW
  });

  it("builds the request with classes, cohorts and an explicit proctoring choice", () => {
    const { errors, body } = validateOrgRunForm({ ...blankOrgRunForm(), workshop_slug: "quick-check", date: "2026-10-20", time: "10:30", groups: [3], cohorts: [9], proctoring: "activity" }, NOW);
    expect(errors).toEqual({});
    expect(body).toEqual({ workshop_slug: "quick-check", starts_at: "2026-10-20T05:00:00.000Z", groups: [3], cohorts: [9], proctoring: "activity", late_join_minutes: 15, lobby_opens_minutes: 15 });
  });

  it("a cohort alone is enough", () => {
    expect(validateOrgRunForm({ ...blankOrgRunForm(), workshop_slug: "x", date: "2026-10-20", time: "10:30", cohorts: [2] }, NOW).errors).toEqual({});
  });
});

describe("runs split", () => {
  const run = (id: number, status: string, starts: string) => ({ id, status, starts_at: starts, workshop: { slug: "w", title: "W" }, proctoring: "", late_join_minutes: 15, lobby_opens_minutes: 15 }) as OrgRun;
  it("puts upcoming soonest first and past latest first", () => {
    const { upcoming, past } = splitRuns([run(1, "scheduled", "2026-10-22T00:00:00Z"), run(2, "ended", "2026-10-01T00:00:00Z"), run(3, "live", "2026-10-18T00:00:00Z"), run(4, "cancelled", "2026-10-10T00:00:00Z")]);
    expect(upcoming.map((r) => r.id)).toEqual([3, 1]);
    expect(past.map((r) => r.id)).toEqual([4, 2]);
  });
});

describe("tiles", () => {
  it("replacing one tile keeps every other tile's identity (memoised tiles skip re-rendering)", () => {
    const a = tile(1), b = tile(2), c = tile(3);
    const prev = { 1: a, 2: b, 3: c };
    const next = applyTiles(prev, [tile(2, { status: "stuck" })]);
    expect(next).not.toBe(prev);
    expect(next[1]).toBe(a);
    expect(next[3]).toBe(c);
    expect(next[2].status).toBe("stuck");
    expect(applyTiles(prev, [])).toBe(prev);
  });

  it("sorts needs-attention first: raised hands, then urgency, then name", () => {
    const list = [tile(1, { status: "engaged", learner: { id: 1, name: "Anu" } }), tile(2, { status: "stuck", learner: { id: 2, name: "Bala" } }),
      tile(3, { status: "passed", learner: { id: 3, name: "Chitra" } }), tile(4, { status: "engaged", raised_hand: true, learner: { id: 4, name: "Divya" } }),
      tile(5, { status: "needs_help", learner: { id: 5, name: "Ezhil" } }), tile(6, { status: "idle", learner: { id: 6, name: "Faiz" } })];
    expect(sortTiles(list).map((t) => t.learner.name)).toEqual(["Divya", "Ezhil", "Bala", "Faiz", "Anu", "Chitra"]);
  });

  it("counts and filters by status, accepting the server's other spellings", () => {
    expect(normStatus("prereq")).toBe("getting_ready");
    expect(normStatus("over_time")).toBe("overtime");
    expect(normStatus("something_new")).toBe("engaged");
    const list = [tile(1, { status: "stuck" }), tile(2, { status: "stuck" }), tile(3, { status: "diy" })];
    expect(countByStatus(list)).toEqual({ stuck: 2, doing_diy: 1 });
    expect(filterTiles(list, new Set(["doing_diy"] as const)).map((t) => t.session_id)).toEqual([3]);
    expect(filterTiles(list, new Set())).toHaveLength(3);
  });
});

class FakeSocket {
  static all: FakeSocket[] = [];
  static OPEN = 1;
  readyState = 0;
  sent: Record<string, unknown>[] = [];
  onopen?: () => void;
  onmessage?: (e: { data: string }) => void;
  onclose?: (e: { code: number }) => void;
  url: string;
  constructor(url: string) {
    this.url = url;
    FakeSocket.all.push(this);
  }
  send(d: string) {
    this.sent.push(JSON.parse(d));
  }
  close() {
    this.readyState = 3;
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  msg(ev: object) {
    this.onmessage?.({ data: JSON.stringify(ev) });
  }
}

describe("monitor socket", () => {
  beforeEach(() => {
    n = 0;
    FakeSocket.all = [];
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeSocket);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });
  const flush = (ms = 0) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));

  it("authenticates, takes the snapshot, and applies a burst of tile updates together", async () => {
    const { result } = renderHook(() => useMonitorSocket(5));
    await flush();
    const s = FakeSocket.all[0];
    expect(s.url).toMatch(/\/ws\/workshop-runs\/5\/monitor\/$/);
    act(() => s.open());
    expect(s.sent[0]).toEqual({ type: "auth", token: "tok-1" });
    act(() => s.msg({ type: "snapshot", tiles: [tile(1), tile(2)] }));
    expect(result.current.status).toBe("live");
    expect(Object.keys(result.current.tiles)).toEqual(["1", "2"]);
    const before = result.current.tiles[1];
    act(() => {
      s.msg({ type: "tile", tile: tile(2, { status: "stuck" }) });
      s.msg({ type: "tile", tile: tile(2, { status: "needs_help", raised_hand: true }) });
    });
    expect(result.current.tiles[2].status).toBe("engaged"); // not yet: coalesced
    await flush(FLUSH_MS);
    expect(result.current.tiles[2].status).toBe("needs_help");
    expect(result.current.tiles[1]).toBe(before);
  });

  it("reconnects at once with a fresh token on 4401, and stops on 4403", async () => {
    const { result } = renderHook(() => useMonitorSocket(5));
    await flush();
    act(() => FakeSocket.all[0].open());
    act(() => FakeSocket.all[0].onclose?.({ code: 4401 }));
    await flush();
    const second = FakeSocket.all[1];
    act(() => second.open());
    expect(second.sent[0]).toEqual({ type: "auth", token: "tok-2" });
    act(() => second.onclose?.({ code: 4403 }));
    await flush(20_000);
    expect(result.current.status).toBe("forbidden");
    expect(FakeSocket.all).toHaveLength(2);
  });

  it("sends nudges (trimmed, at most 300 characters) and hand acknowledgements", async () => {
    const { result } = renderHook(() => useMonitorSocket(5));
    await flush();
    const s = FakeSocket.all[0];
    act(() => s.open());
    act(() => s.msg({ type: "snapshot", tiles: [tile(1, { raised_hand: true })] }));
    act(() => void result.current.nudge(1, `  ${"x".repeat(400)}  `));
    expect(s.sent[1]).toEqual({ type: "nudge", session_id: 1, text: "x".repeat(300) });
    act(() => void result.current.ackHand(1));
    expect(s.sent[2]).toEqual({ type: "ack_hand", session_id: 1 });
    expect(result.current.tiles[1].raised_hand).toBe(false);
  });

  it("a server ack for a hand also clears a hand still up in a queued tile", async () => {
    const { result } = renderHook(() => useMonitorSocket(5));
    await flush();
    const s = FakeSocket.all[0];
    act(() => s.open());
    act(() => s.msg({ type: "snapshot", tiles: [tile(1, { raised_hand: true })], not_joined: [] }));
    act(() => s.msg({ type: "tile", tile: tile(1, { raised_hand: true, status: "needs_help" }) }));
    act(() => s.msg({ type: "ack", action: "ack_hand", session_id: 1, changed: true }));
    expect(result.current.tiles[1].raised_hand).toBe(false);
    act(() => s.msg({ type: "ack", action: "nudge", session_id: 1 }));
    await flush(FLUSH_MS);
    expect(result.current.tiles[1]).toMatchObject({ status: "needs_help", raised_hand: false });
  });
});
