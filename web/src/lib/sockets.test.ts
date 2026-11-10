import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { REAUTH_MS, useLiveSocket } from "@/live/useLiveSocket";

import { useRolePlaySocket } from "./roleplay";
import { useMentorSocket } from "./useMentorSocket";

vi.mock("./api", async (orig) => ({ ...(await orig<typeof import("./api")>()), ensureFreshAccess: vi.fn(async () => `tok-${++n}`) }));
let n = 0;

/** Minimal WebSocket stand-in: records what was sent; tests drive open / message / close. */
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

describe("token expiry on WebSockets (HB)", () => {
  it("mentor: a 4401 close reconnects at once with a fresh token, without showing an error", async () => {
    const { result } = renderHook(() => useMentorSocket({ conversationId: null, onConversation: () => {} }));
    await flush();
    const first = FakeSocket.all[0];
    act(() => first.open());
    expect(first.sent[0]).toEqual({ type: "auth", token: "tok-1" });
    act(() => first.msg({ type: "error", code: "token_expired" }));
    act(() => first.onclose?.({ code: 4401 }));
    await flush();
    const second = FakeSocket.all[1];
    expect(second).toBeDefined();
    act(() => second.open());
    expect(second.sent[0]).toEqual({ type: "auth", token: "tok-2" });
    expect(result.current.error).toBeNull();
  });

  it("live class: re-authenticates on the open socket before the token expires and stays live", async () => {
    const { result } = renderHook(() => useLiveSocket());
    await flush();
    const sock = FakeSocket.all[0];
    act(() => sock.open());
    act(() => sock.msg({ type: "ready" }));
    act(() => sock.msg({ type: "started", session_id: 1, minutes_left: 60 }));
    expect(result.current.status).toBe("live");
    await act(async () => void (await vi.advanceTimersByTimeAsync(REAUTH_MS)));
    expect(sock.sent).toContainEqual({ type: "auth", token: "tok-2" });
    act(() => sock.msg({ type: "ready" })); // the server's answer to the re-auth
    expect(result.current.status).toBe("live");
    expect(FakeSocket.all).toHaveLength(1); // same socket, no reconnect
  });
});

describe("web search in role-play", () => {
  it("keeps the search tool's sources on the character's reply", async () => {
    const { result } = renderHook(() => useRolePlaySocket(5, []));
    await flush();
    const sock = FakeSocket.all[0];
    act(() => sock.open());
    act(() => sock.msg({ type: "ready" }));
    act(() => void result.current.send("What's the bus fare today?"));
    act(() => sock.msg({ type: "start" }));
    act(() => sock.msg({ type: "status", state: "searching" }));
    act(() => sock.msg({ type: "delta", text: "It's 25 rupees now." }));
    act(() => sock.msg({ type: "done", turns_left: 3, turn_id: 9, sources: [{ title: "MTC fares", url: "https://mtcbus.tn.gov.in/fares" }] }));
    const reply = result.current.messages.at(-1)!;
    expect(reply).toMatchObject({ role: "assistant", content: "It's 25 rupees now.", streaming: false, id: 9 });
    expect(reply.citations).toEqual([{ kind: "web", title: "MTC fares", url: "https://mtcbus.tn.gov.in/fares" }]);
  });
});
