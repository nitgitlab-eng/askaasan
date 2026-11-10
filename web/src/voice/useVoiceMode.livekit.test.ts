import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatMsg } from "@/lib/useMentorSocket";

import type { StreamEvent } from "./stream";

// ── Fakes: a voice config with a live call available, and a LiveKit call the test drives. ──
const cfg = { live: true };
const join = { fail: "", calls: 0, feature: "", lang: "" };
const callSpk = { spoken: [] as string[], ended: 0, cancelled: 0, disposed: 0, busy: false };
let heard: (e: StreamEvent) => void = () => {};
let liveCall: {
  speaker: Record<string, unknown>;
  listen: (cb: (e: StreamEvent) => void) => Promise<{ level: () => number; stop: () => void }>;
  onInterrupted?: () => void;
  onClosed?: () => void;
};
const micStops = vi.fn();

class FakeRecognition {
  static all: FakeRecognition[] = [];
  lang = "";
  continuous = false;
  interimResults = false;
  onresult = null;
  onerror = null;
  onend = null;
  constructor() {
    FakeRecognition.all.push(this);
  }
  start() {}
  stop() {}
  abort() {}
}

vi.mock("./engines", () => ({
  BCP47: { en: "en-IN", ta: "ta-IN" },
  get BrowserRecognition() {
    return FakeRecognition;
  },
  fetchVoiceConfig: async () => ({ stt: { engine: "browser", provider: "browser" }, tts: { engine: "browser", provider: "browser" }, live: cfg.live }),
  unlockAudio: () => {},
  serverTranscribe: vi.fn(),
  startClip: vi.fn(),
  serverSpeaker: () => browserSpk(),
  browserSpeaker: () => browserSpk(),
}));
function browserSpk() {
  return { speak: vi.fn(), cancel: vi.fn(), busy: false, level: () => 0 };
}
vi.mock("./livekit", () => ({
  joinLiveCall: async (lang: string, feature: string) => {
    join.calls++;
    join.lang = lang;
    join.feature = feature;
    if (join.fail) throw new Error(join.fail);
    const speaker: Record<string, unknown> = {
      speak(t: string) {
        callSpk.spoken.push(t);
        callSpk.busy = true;
        (speaker.onStart as ((t: string) => void) | undefined)?.(t);
      },
      end() {
        callSpk.ended++;
      },
      cancel() {
        callSpk.cancelled++;
        callSpk.busy = false;
      },
      dispose() {
        callSpk.disposed++;
      },
      get busy() {
        return callSpk.busy;
      },
      level: () => 0.2,
    };
    liveCall = {
      speaker,
      listen: async (cb) => {
        heard = cb;
        return { level: () => 0.4, stop: micStops };
      },
    };
    return liveCall;
  },
}));
vi.mock("./vad", () => ({
  startMicVad: async () => ({ stream: {}, machine: { sensitivity: 1, speaking: false }, level: () => 0, stop: vi.fn() }),
}));

const { useVoiceMode } = await import("./useVoiceMode");

function setup(feature: "mentor" | "roleplay" = "mentor") {
  const send = vi.fn(() => true);
  const cancel = vi.fn();
  const hook = renderHook((p: { messages: ChatMsg[]; busy: boolean }) => useVoiceMode({ messages: p.messages, send, cancel, lang: "ta", mode: "conversation", busy: p.busy, feature }), {
    initialProps: { messages: [] as ChatMsg[], busy: false },
  });
  return { ...hook, send, cancel };
}
const host = (content: string, streaming: boolean): ChatMsg[] => [
  { id: "u1", role: "user", content: "q" },
  { id: "a1", role: "assistant", content, streaming },
];

beforeEach(() => {
  cfg.live = true;
  join.fail = "";
  join.calls = 0;
  Object.assign(callSpk, { spoken: [], ended: 0, cancelled: 0, disposed: 0, busy: false });
  micStops.mockClear();
  FakeRecognition.all = [];
});

describe("live voice call (LiveKit)", () => {
  it("joins a call for this screen and listens through it, not the browser recogniser", async () => {
    const { result } = setup("roleplay");
    await act(() => result.current.start());
    expect(join).toMatchObject({ calls: 1, feature: "roleplay", lang: "ta" });
    expect(FakeRecognition.all).toHaveLength(0);
    expect(result.current.talkOver).toBe(true);
    expect(result.current.levels().mic).toBe(0.4);
  });

  it("the agent's finished turn is sent once; the reply is streamed to the call and closed when done", async () => {
    const { result, rerender, send } = setup();
    await act(() => result.current.start());
    act(() => heard({ type: "interim", text: "loops na" }));
    expect(result.current.interim).toBe("loops na");
    act(() => heard({ type: "final", text: "loops na enna", speech_final: true }));
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith("loops na enna");
    rerender({ messages: host("ஒரு loop வேலையை திரும்ப செய்யும். உதாரணம்", true), busy: true });
    expect(callSpk.spoken[0]).toMatch(/loop/);
    rerender({ messages: host("ஒரு loop வேலையை திரும்ப செய்யும். உதாரணம் பாருங்க.", false), busy: false });
    expect(callSpk.ended).toBe(1);
  });

  it("talking over Aasan: the agent stops speaking and the reply is cut on the server too", async () => {
    const { result, rerender, cancel } = setup();
    await act(() => result.current.start());
    rerender({ messages: host("A long answer. With many sentences", true), busy: true });
    expect(callSpk.busy).toBe(true);
    act(() => liveCall.onInterrupted?.());
    expect(cancel).toHaveBeenCalled();
  });

  it("words heard on a call are never dropped as echo, even when they repeat Aasan's words", async () => {
    const { result, rerender, send } = setup();
    await act(() => result.current.start());
    rerender({ messages: host("I'm listening. Are you listening too? Tell me", true), busy: true });
    act(() => heard({ type: "interim", text: "are you listening" }));
    expect(result.current.interim).toBe("are you listening");
    rerender({ messages: host("I'm listening. Are you listening too?", false), busy: false });
    act(() => heard({ type: "final", text: "are you listening", speech_final: true }));
    expect(send).toHaveBeenCalledWith("are you listening");
  });

  it("a tap interrupts through the call; End hangs up", async () => {
    const { result, rerender } = setup();
    await act(() => result.current.start());
    rerender({ messages: host("Speaking now. More", true), busy: true });
    act(() => result.current.interrupt());
    expect(callSpk.cancelled).toBeGreaterThan(0);
    act(() => result.current.stop());
    expect(callSpk.disposed).toBe(1);
    expect(micStops).toHaveBeenCalled();
  });

  it("falls back to the usual voice when the call can't start", async () => {
    join.fail = "live_unavailable";
    const { result } = setup();
    await act(() => result.current.start());
    expect(result.current.active).toBe(true);
    expect(FakeRecognition.all).toHaveLength(1); // the browser recogniser instead
    expect(result.current.talkOver).toBe(false);
  });

  it("no live call on the server: never tries one", async () => {
    cfg.live = false;
    const { result } = setup();
    await act(() => result.current.start());
    expect(join.calls).toBe(0);
  });

  it("the call dropping ends voice with a message", async () => {
    const { result } = setup();
    await act(() => result.current.start());
    act(() => liveCall.onClosed?.());
    expect(result.current.active).toBe(false);
    expect(result.current.error).toBe("stream_closed");
  });
});
