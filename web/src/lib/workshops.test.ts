import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { IDLE_MS, NUDGES_SHOWN_MAX, NUDGE_TEXT_MAX, REAUTH_MS, isBuildTask, isDiy, mergeNudges, nudgesNewestFirst, paceOf, useProctoring, useWorkshopSocket, type Session } from "./workshops";

vi.mock("./api", async (orig) => ({ ...(await orig<typeof import("./api")>()), ensureFreshAccess: vi.fn(async () => `tok-${++n}`) }));
let n = 0;

class FakeSocket {
  static all: FakeSocket[] = [];
  static OPEN = 1;
  readyState = 0;
  sent: unknown[] = [];
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

const session = (over: Partial<Session> = {}): Session => ({
  id: 7, status: "active", workshop: { slug: "quick-check", title: "Quick check", duration_minutes: 10, grace_minutes: 5, proctoring: "off", pass_mark: 60 },
  prerequisites: [], ready: true, started_at: "2026-10-18T10:00:00Z", planned_end: null, grace_end: null, stage_index: 0,
  stages: [{ key: "a", kind: "teach", title: "Basics", minutes: 5, concepts: [{ text: "What a prompt is", done: false }], steps: [] }],
  scores: {}, final_score: null, passed: null, certificate: null, proctoring: "off", proctor_notice_seen: true, ...over,
});

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

const flush = () => act(async () => void (await vi.advanceTimersByTimeAsync(0)));

describe("useWorkshopSocket", () => {
  it("authenticates, restores state and turns from ready, and streams a turn", async () => {
    const onSession = vi.fn();
    const { result } = renderHook(() => useWorkshopSocket(7, onSession));
    await flush();
    const sock = FakeSocket.all[0];
    expect(sock.url).toMatch(/\/ws\/workshop\/7\/$/);
    act(() => sock.open());
    expect(sock.sent[0]).toEqual({ type: "auth", token: "tok-1" });
    act(() => sock.msg({ type: "ready", session: session(), turns: [{ role: "assistant", text: "Welcome back" }, { role: "user", text: "hi" }] }));
    expect(onSession).toHaveBeenCalledWith(expect.objectContaining({ id: 7 }));
    expect(result.current.messages.map((m) => m.role)).toEqual(["assistant", "user"]);
    act(() => void result.current.say("a prompt is an instruction"));
    expect(sock.sent).toContainEqual({ type: "say", text: "a prompt is an instruction" });
    act(() => sock.msg({ type: "start" }));
    act(() => sock.msg({ type: "delta", text: "Nice!" }));
    act(() => sock.msg({ type: "done" }));
    expect(result.current.messages.at(-1)).toMatchObject({ role: "assistant", content: "Nice!", streaming: false });
    expect(result.current.busy).toBe(false);
    act(() => sock.msg({ type: "pace", status: "in_grace", minutes_left: 4 }));
    expect(result.current.pace).toEqual({ status: "in_grace", minutesLeft: 4 });
    act(() => {
      result.current.next();
      result.current.control("tamil");
      result.current.stepDone(1);
      result.current.raiseHand();
    });
    expect(sock.sent.slice(-4)).toEqual([{ type: "next" }, { type: "control", action: "tamil" }, { type: "step_done", step: 1 }, { type: "raise_hand" }]);
  });

  it("reconnects at once with a fresh token on 4401 and re-auths before expiry", async () => {
    const { result } = renderHook(() => useWorkshopSocket(7, () => {}));
    await flush();
    const first = FakeSocket.all[0];
    act(() => first.open());
    act(() => first.msg({ type: "ready", session: session() }));
    await act(async () => void (await vi.advanceTimersByTimeAsync(REAUTH_MS)));
    expect(first.sent).toContainEqual({ type: "auth", token: "tok-2" });
    act(() => first.msg({ type: "error", code: "token_expired" }));
    act(() => first.onclose?.({ code: 4401 }));
    await flush();
    const second = FakeSocket.all[1];
    act(() => second.open());
    expect(second.sent[0]).toEqual({ type: "auth", token: "tok-3" });
    expect(result.current.error).toBeNull();
  });

  it("does not retry when the session is not found", async () => {
    const { result } = renderHook(() => useWorkshopSocket(7, () => {}));
    await flush();
    act(() => FakeSocket.all[0].onclose?.({ code: 4404 }));
    await act(async () => void (await vi.advanceTimersByTimeAsync(20_000)));
    expect(FakeSocket.all).toHaveLength(1);
    expect(result.current.error).toBe("not_found");
  });
});

describe("paceOf", () => {
  it("prefers the live tick, then the session's pace, and shows nothing before start", () => {
    expect(paceOf(session({ status: "prereq" }), null)).toBeNull();
    expect(paceOf(session({ pace: { status: "behind", minutes_left: 3 } }), null)).toEqual({ status: "behind", minutesLeft: 3 });
    expect(paceOf(session({ status: "overtime" }), null)).toEqual({ status: "overtime", minutesLeft: null });
    expect(paceOf(session(), { status: "on_track", minutesLeft: 8 })).toEqual({ status: "on_track", minutesLeft: 8 });
  });
});

describe("useProctoring", () => {
  const fire = () => {
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
    window.dispatchEvent(new Event("blur"));
    window.dispatchEvent(new Event("focus"));
    vi.advanceTimersByTime(IDLE_MS);
    window.dispatchEvent(new Event("keydown"));
  };

  it("sends nothing when proctoring is off", () => {
    const send = vi.fn();
    renderHook(() => useProctoring({ mode: "off", enabled: true, send }));
    fire();
    expect(send).not.toHaveBeenCalled();
  });

  it("sends tab, focus and idle events when on", () => {
    const send = vi.fn();
    renderHook(() => useProctoring({ mode: "activity", enabled: true, send }));
    fire();
    expect(send.mock.calls.map((c) => c[0])).toEqual(["hidden", "blur", "focus", "idle", "active"]);
  });

  it("sends nothing while paused (hands-on stage)", () => {
    const send = vi.fn();
    renderHook(() => useProctoring({ mode: "strict", enabled: false, send }));
    fire();
    document.dispatchEvent(new Event("fullscreenchange"));
    expect(send).not.toHaveBeenCalled();
  });

  it("strict mode reports leaving full screen", () => {
    const send = vi.fn();
    renderHook(() => useProctoring({ mode: "strict", enabled: true, send }));
    document.dispatchEvent(new Event("fullscreenchange"));
    expect(send).toHaveBeenCalledWith("fs_exit");
  });
});

describe("staff nudges (M5: offline nudges arrive in ready)", () => {
  it("keeps plain non-blank strings, caps the text, drops duplicates and keeps at most NUDGES_SHOWN_MAX", () => {
    const now = Date.parse("2026-10-18T10:00:00Z");
    const a = mergeNudges([], [
      { text: "Open the tab", from: "Ms. Priya", at: "2026-10-18T09:00:00Z" },
      { text: 42 }, { text: "  " }, { from: "x" },
      { text: "x".repeat(NUDGE_TEXT_MAX + 50), from: { evil: true }, at: "not a date" },
    ], now);
    expect(a).toHaveLength(2);
    expect(a[0]).toMatchObject({ text: "Open the tab", from: "Ms. Priya", at: "2026-10-18T09:00:00Z" });
    expect(a[1].text).toHaveLength(NUDGE_TEXT_MAX);
    expect(a[1].from).toBeNull();
    expect(a[1].at).toBe(new Date(now).toISOString()); // a bad time becomes "now"
    expect(mergeNudges(a, [{ text: "Open the tab", from: "Ms. Priya", at: "2026-10-18T09:00:00Z" }], now)).toHaveLength(2);
    const many = mergeNudges([], Array.from({ length: NUDGES_SHOWN_MAX + 5 }, (_, i) => ({ text: `n${i}`, at: new Date(now + i * 1000).toISOString() })), now);
    expect(many).toHaveLength(NUDGES_SHOWN_MAX);
    expect(many[0].text).toBe("n5"); // the oldest go first
  });

  it("dedupes on the server's id when sent (a live nudge repeated in ready), else on text + time", () => {
    const live = mergeNudges([], [{ id: 31, text: "Try step 2", from: "Ms. Priya", at: "2026-10-18T09:00:00Z" }]);
    // The same nudge again in ready, even with a re-serialised time, is not shown twice.
    expect(mergeNudges(live, [{ id: 31, text: "Try step 2", from: "Ms. Priya", at: "2026-10-18T09:00:00.000000+00:00" }])).toHaveLength(1);
    // Two different nudges with the same text and time but different ids are both kept.
    const two = mergeNudges([], [{ id: 1, text: "Same", at: "2026-10-18T09:00:00Z" }, { id: 2, text: "Same", at: "2026-10-18T09:00:00Z" }]);
    expect(two).toHaveLength(2);
    expect(two.map((x) => x.sid)).toEqual(["1", "2"]);
    // Without ids, text + time decides.
    expect(mergeNudges([], [{ text: "Hi", at: "2026-10-18T09:00:00Z" }, { text: "Hi", at: "2026-10-18T09:00:00Z" }])).toHaveLength(1);
  });

  it("orders newest first by send time, arrival order breaking ties", () => {
    const list = mergeNudges([], [
      { text: "old", at: "2026-10-18T09:00:00Z" },
      { text: "new", at: "2026-10-18T09:30:00Z" },
      { text: "same-a", at: "2026-10-18T09:10:00Z" },
      { text: "same-b", at: "2026-10-18T09:10:00Z" },
    ]);
    expect(nudgesNewestFirst(list).map((x) => x.text)).toEqual(["new", "same-b", "same-a", "old"]);
  });

  it("ready.nudges reach the hook's nudges", async () => {
    const { result } = renderHook(() => useWorkshopSocket(5, () => {}));
    await flush();
    const sock = FakeSocket.all[0];
    act(() => sock.open());
    act(() => sock.msg({ type: "ready", session: session(), nudges: [{ text: "Hi", from: "T", at: "2026-10-18T09:00:00Z" }] }));
    act(() => sock.msg({ type: "staff_nudge", id: 9, text: "Live one", from: "T", at: "2026-10-18T09:05:00Z" }));
    act(() => sock.msg({ type: "ready", session: session(), nudges: [{ id: 9, text: "Live one", from: "T", at: "2026-10-18T09:05:00Z" }] }));
    expect(result.current.nudges.map((x) => x.text)).toEqual(["Hi", "Live one"]);
  });
});

describe("build stages (M5)", () => {
  it("are hands-on: proctoring pauses and the DIY steps apply", () => {
    expect(isDiy("build")).toBe(true);
    expect(isDiy("teach")).toBe(false);
  });

  it("isBuildTask accepts only the three activity bodies with a payload", () => {
    expect(isBuildTask({ type: "code", payload: {} })).toBe(true);
    expect(isBuildTask({ type: "open_input", payload: {} })).toBe(true);
    expect(isBuildTask({ type: "artifact_check", payload: {} })).toBe(true);
    expect(isBuildTask({ type: "quiz", payload: {} })).toBe(false);
    expect(isBuildTask({ type: "code", payload: null as unknown as Record<string, unknown> })).toBe(false);
    expect(isBuildTask(null)).toBe(false);
  });
});
