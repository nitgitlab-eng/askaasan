import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatMsg } from "@/lib/useMentorSocket";

import type { VadEvent } from "./vad";

// ── Fakes. Unlike the turn-mode tests, this recogniser keeps one growing result list per session, as Chrome does in
// continuous mode: an interim is refined in place until it turns final, then the next words get a new slot. ──────────
type Result = { isFinal: boolean; 0: { transcript: string } };
class FakeRecognition {
  static all: FakeRecognition[] = [];
  lang = "";
  continuous = false;
  interimResults = false;
  running = false;
  starts = 0;
  results: Result[] = [];
  onresult: ((e: { resultIndex: number; results: ArrayLike<Result> }) => void) | null = null;
  onerror: ((e: { error: string }) => void) | null = null;
  onend: (() => void) | null = null;
  constructor() {
    FakeRecognition.all.push(this);
  }
  start() {
    if (this.running) throw new Error("InvalidStateError");
    this.running = true;
    this.starts++;
    this.results = [];
  }
  stop() {
    this.running = false;
    queueMicrotask(() => this.onend?.());
  }
  abort() {
    this.running = false;
    queueMicrotask(() => this.onend?.());
  }
  /** Words heard: refine the open interim slot, or open a new one. */
  hear(text: string, isFinal = false) {
    const last = this.results.at(-1);
    const idx = last && !last.isFinal ? this.results.length - 1 : this.results.length;
    this.results[idx] = { isFinal, 0: { transcript: text } };
    this.onresult?.({ resultIndex: idx, results: [...this.results] });
  }
}

const spk = { busy: false, spoken: [] as string[], cancel: vi.fn(), onIdle: undefined as undefined | (() => void), onStart: undefined as undefined | ((t: string) => void) };
const vad = { emit: (_e: VadEvent) => {}, stop: vi.fn(), opened: 0, opts: undefined as unknown };

vi.mock("./engines", () => ({
  BCP47: { en: "en-IN", ta: "ta-IN" },
  get BrowserRecognition() {
    return FakeRecognition;
  },
  fetchVoiceConfig: async () => ({ stt: { engine: "browser", provider: "browser" }, tts: { engine: "browser", provider: "browser" } }),
  unlockAudio: () => {},
  serverTranscribe: vi.fn(),
  startClip: vi.fn(),
  serverSpeaker: () => makeSpeaker(),
  browserSpeaker: () => makeSpeaker(),
}));
function makeSpeaker() {
  return {
    speak(t: string) {
      spk.spoken.push(t);
      spk.busy = true;
      spk.onStart?.(t);
    },
    cancel() {
      spk.busy = false;
      spk.cancel();
    },
    get busy() {
      return spk.busy;
    },
    level: () => 0,
    set onIdle(f: (() => void) | undefined) {
      spk.onIdle = f;
    },
    get onIdle() {
      return spk.onIdle;
    },
    set onStart(f: ((t: string) => void) | undefined) {
      spk.onStart = f;
    },
    get onStart() {
      return spk.onStart;
    },
    onError: undefined,
  };
}
vi.mock("./vad", () => ({
  startMicVad: async (cb: (e: VadEvent) => void, opts: unknown) => {
    vad.emit = cb;
    vad.opened++;
    vad.opts = opts;
    return { stream: {}, machine: { sensitivity: 1, speaking: false }, level: () => 0.3, stop: vad.stop };
  },
}));

const { useVoiceMode, ECHO_TAIL_MS, RESUME_AFTER_MS, TURN_PAUSE_MS, TURN_SILENCE_MS } = await import("./useVoiceMode");

function setup(messages: ChatMsg[] = []) {
  const send = vi.fn(() => true);
  const cancel = vi.fn();
  const hook = renderHook(
    (p: { messages: ChatMsg[]; busy?: boolean }) => useVoiceMode({ messages: p.messages, send, cancel, lang: "en", mode: "conversation", busy: p.busy }),
    { initialProps: { messages } as { messages: ChatMsg[]; busy?: boolean } },
  );
  return { ...hook, send, cancel };
}
const rec = () => FakeRecognition.all.at(-1)!;
const host = (content: string, streaming: boolean): ChatMsg[] => [
  { id: "u1", role: "user", content: "q" },
  { id: "a1", role: "assistant", content, streaming },
];

beforeEach(() => {
  FakeRecognition.all = [];
  spk.busy = false;
  spk.spoken = [];
  spk.cancel.mockClear();
  vad.stop.mockClear();
  vad.opened = 0;
});
afterEach(() => vi.useRealTimers());

describe("conversation (browser recogniser)", () => {
  it("opens the mic once on start, with a short end-of-turn pause, and stays listening", async () => {
    const { result } = setup();
    await act(() => result.current.start());
    expect(result.current.state).toBe("listening");
    expect(vad.opened).toBe(1);
    expect(vad.opts).toEqual({ releaseMs: TURN_PAUSE_MS });
    expect(rec().running).toBe(true);
    expect(result.current.talkOver).toBe(false); // the browser recogniser pauses while Aasan talks: a tap interrupts
  });

  it("sends the turn the moment the learner stops talking, without waiting for the recogniser to wrap up", async () => {
    const { result, send } = setup();
    await act(() => result.current.start());
    const r = rec();
    act(() => {
      vad.emit("speech-start");
      r.hear("what is");
      r.hear("what is a prompt");
    });
    expect(result.current.interim).toBe("what is a prompt");
    expect(result.current.state).toBe("hearing");
    act(() => vad.emit("speech-end"));
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith("what is a prompt");
    expect(r.running).toBe(true); // the recogniser was never stopped
    // The late final for the same words is not sent again; the next turn is new words only.
    act(() => r.hear("what is a prompt", true));
    act(() => {
      vad.emit("speech-start");
      r.hear("and an agent");
      vad.emit("speech-end");
    });
    expect(send).toHaveBeenCalledTimes(2);
    expect(send).toHaveBeenLastCalledWith("and an agent");
  });

  it("falls back to recogniser silence when the VAD misses the end of the turn", async () => {
    vi.useFakeTimers();
    const { result, send } = setup();
    await act(() => result.current.start());
    act(() => rec().hear("hello there"));
    expect(send).not.toHaveBeenCalled();
    await act(async () => void vi.advanceTimersByTime(TURN_SILENCE_MS));
    expect(send).toHaveBeenCalledWith("hello there");
  });

  it("listening pauses while Aasan talks, so its own voice can never become the learner's turn", async () => {
    vi.useFakeTimers();
    const { result, rerender, send, cancel } = setup();
    await act(() => result.current.start());
    const r = rec();
    rerender({ messages: host("Prompts are instructions you give a model. They", true) });
    expect(spk.spoken.length).toBeGreaterThan(0);
    expect(r.running).toBe(false); // the recogniser is off while Aasan talks
    act(() => {
      vad.emit("speech-start");
      vad.emit("speech-end");
    });
    expect(result.current.state).not.toBe("hearing");
    expect(cancel).not.toHaveBeenCalled();
    // Aasan finishes: listening comes back a moment later, on a fresh session.
    rerender({ messages: host("Prompts are instructions you give a model.", false) });
    act(() => {
      spk.busy = false;
      spk.onIdle?.();
    });
    await act(async () => void vi.advanceTimersByTime(RESUME_AFTER_MS));
    expect(r.running).toBe(true);
    // Aasan's last words arriving late are still its own voice: dropped.
    act(() => {
      r.hear("you give a model", true);
      vad.emit("speech-end");
    });
    expect(send).not.toHaveBeenCalled();
    // The learner's own words go out.
    act(() => {
      vad.emit("speech-start");
      r.hear("what about agents");
      vad.emit("speech-end");
    });
    expect(send).toHaveBeenCalledWith("what about agents");
  });

  it("after the echo tail, even words Aasan used count as the learner's", async () => {
    vi.useFakeTimers();
    const { result, rerender, send } = setup();
    await act(() => result.current.start());
    const r = rec();
    rerender({ messages: host("Prompts are instructions you give a model.", false) });
    act(() => {
      spk.busy = false;
      spk.onIdle?.();
    });
    await act(async () => void vi.advanceTimersByTime(ECHO_TAIL_MS));
    act(() => {
      r.hear("instructions you give", true);
      vad.emit("speech-end");
    });
    expect(send).toHaveBeenCalledWith("instructions you give");
  });

  it("a tap interrupts Aasan; listening resumes and the next turn waits for the cut-off reply to wind down", async () => {
    vi.useFakeTimers();
    const { result, rerender, send, cancel } = setup();
    await act(() => result.current.start());
    const r = rec();
    rerender({ messages: host("Prompts are instructions you give a model. They", true), busy: true });
    expect(r.running).toBe(false);
    act(() => result.current.interrupt());
    expect(spk.cancel).toHaveBeenCalled();
    expect(cancel).toHaveBeenCalled();
    await act(async () => void vi.advanceTimersByTime(RESUME_AFTER_MS));
    expect(r.running).toBe(true);
    await act(async () => void vi.advanceTimersByTime(ECHO_TAIL_MS));
    act(() => {
      r.hear("tell me more please");
      vad.emit("speech-end");
    });
    expect(send).not.toHaveBeenCalled();
    expect(result.current.state).toBe("thinking");
    rerender({ messages: host("Prompts are", false), busy: false });
    await act(async () => {
      await Promise.resolve();
    });
    expect(send).toHaveBeenCalledWith("tell me more please");
  });

  it("mute closes the mic without ending voice; unmute opens it again", async () => {
    const { result, send } = setup();
    await act(() => result.current.start());
    await act(() => result.current.mute(true));
    expect(result.current.micMuted).toBe(true);
    expect(result.current.active).toBe(true);
    expect(vad.stop).toHaveBeenCalled();
    expect(rec().running).toBe(false);
    await act(() => result.current.mute(false));
    expect(result.current.micMuted).toBe(false);
    expect(vad.opened).toBe(2);
    act(() => {
      rec().hear("back again");
      vad.emit("speech-end");
    });
    expect(send).toHaveBeenCalledWith("back again");
  });

  it("start(mode) starts straight into conversation even before the caller re-renders", async () => {
    const send = vi.fn(() => true);
    const { result, rerender } = renderHook((p: { mode: "tap" | "conversation" }) => useVoiceMode({ messages: [], send, cancel: vi.fn(), lang: "en", mode: p.mode }), { initialProps: { mode: "tap" as "tap" | "conversation" } });
    // As Ask Aasan does: start inside the tap, and switch the mode prop in the same tap.
    await act(async () => {
      const started = result.current.start("conversation");
      rerender({ mode: "conversation" });
      await started;
    });
    expect(vad.opened).toBe(1);
    expect(rec().running).toBe(true);
  });
});
