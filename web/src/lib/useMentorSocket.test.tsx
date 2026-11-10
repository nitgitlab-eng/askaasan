import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fresh = vi.hoisted(() => ({ token: null as string | null, calls: 0 }));
vi.mock("./api", async (orig) => ({
  ...(await orig<typeof import("./api")>()),
  ensureFreshAccess: vi.fn(async () => {
    fresh.calls++;
    return fresh.token;
  }),
}));

import { TOKEN_EXPIRED, useMentorSocket } from "./useMentorSocket";

class FakeWS {
  static OPEN = 1;
  static all: FakeWS[] = [];
  readyState = 0;
  sent: Record<string, unknown>[] = [];
  onopen?: () => void;
  onmessage?: (e: { data: string }) => void;
  onclose?: (e: { code: number }) => void;
  constructor() {
    FakeWS.all.push(this);
  }
  send(d: string) {
    this.sent.push(JSON.parse(d));
  }
  close() {}
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  msg(ev: object) {
    this.onmessage?.({ data: JSON.stringify(ev) });
  }
  drop(code: number) {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}

const flush = async () => {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
};

beforeEach(() => {
  vi.useFakeTimers();
  FakeWS.all = [];
  fresh.calls = 0;
  fresh.token = "tok";
  vi.stubGlobal("WebSocket", FakeWS);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const hook = () => renderHook(() => useMentorSocket({ conversationId: null, onConversation: () => {} }));

describe("Ask Aasan socket never fails silently", () => {
  it("keeps trying when there is no session token yet (new sign-ups), instead of giving up", async () => {
    fresh.token = null;
    const { result } = hook();
    await flush();
    expect(FakeWS.all).toHaveLength(0);
    expect(result.current.status).toBe("offline");
    fresh.token = "tok";
    await act(async () => void vi.advanceTimersByTime(600));
    await flush();
    expect(FakeWS.all).toHaveLength(1);
    expect(fresh.calls).toBeGreaterThanOrEqual(2);
  });

  it("a refused token reconnects at once the first time, then backs off (no tight loop)", async () => {
    hook();
    await flush();
    act(() => FakeWS.all[0].drop(TOKEN_EXPIRED));
    await act(async () => void vi.advanceTimersByTime(0));
    await flush();
    expect(FakeWS.all).toHaveLength(2); // immediate fresh-token retry
    act(() => FakeWS.all[1].drop(TOKEN_EXPIRED));
    await act(async () => void vi.advanceTimersByTime(0));
    await flush();
    expect(FakeWS.all).toHaveLength(2); // the second refusal waits
    await act(async () => void vi.advanceTimersByTime(1100));
    await flush();
    expect(FakeWS.all).toHaveLength(3);
  });

  it("Try again resends the last question without duplicating it", async () => {
    const { result } = hook();
    await flush();
    const ws = FakeWS.all[0];
    act(() => ws.open());
    act(() => ws.msg({ type: "ready" }));
    act(() => void result.current.send("What is AI?"));
    act(() => ws.msg({ type: "error", code: "server_error" }));
    expect(result.current.error).toBe("server_error");
    act(() => void result.current.retry());
    expect(ws.sent.filter((m) => m.type === "message")).toHaveLength(2);
    expect(result.current.messages.filter((m) => m.role === "user")).toHaveLength(1);
    expect(result.current.error).toBeNull();
  });
});

describe("live web search", () => {
  it("shows searching from the status event until the first word, and keeps the web sources", async () => {
    const { result } = hook();
    await flush();
    const ws = FakeWS.all[0];
    act(() => {
      ws.open();
      ws.msg({ type: "ready" });
    });
    act(() => void result.current.send("gold price today?"));
    act(() => ws.msg({ type: "start", conversation_id: 1 }));
    act(() => ws.msg({ type: "status", state: "searching" }));
    expect(result.current.activity).toBe("searching");
    act(() => ws.msg({ type: "delta", text: "Gold is ₹7,000." }));
    expect(result.current.activity).toBeNull();
    const src = { kind: "web", title: "The Hindu", url: "https://www.thehindu.com/gold" };
    act(() => ws.msg({ type: "done", message_id: 9, citations: [src] }));
    expect(result.current.messages.at(-1)?.citations).toEqual([src]);
  });

  it("an error clears searching", async () => {
    const { result } = hook();
    await flush();
    const ws = FakeWS.all[0];
    act(() => {
      ws.open();
      ws.msg({ type: "ready" });
    });
    act(() => void result.current.send("latest news?"));
    act(() => ws.msg({ type: "status", state: "searching" }));
    act(() => ws.msg({ type: "error", code: "provider_error" }));
    expect(result.current.activity).toBeNull();
  });
});
