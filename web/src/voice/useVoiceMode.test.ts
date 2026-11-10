import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatMsg } from "@/lib/useMentorSocket";

import type { VadEvent } from "./vad";

// ── Fakes: browser recognition, a speaker whose "busy" the test controls, and a VAD the test drives. ──────────────
type Result = { isFinal: boolean; 0: { transcript: string } };
class FakeRecognition {
  static all: FakeRecognition[] = [];
  lang = "";
  continuous = false;
  interimResults = false;
  running = false;
  starts = 0;
  aborts = 0;
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
  }
  /** Like Chrome: pending words arrive as finals, then "end". */
  stop() {
    this.running = false;
    queueMicrotask(() => this.onend?.());
  }
  abort() {
    this.running = false;
    this.aborts++;
    queueMicrotask(() => this.onend?.());
  }
  say(text: string, isFinal = true) {
    this.onresult?.({ resultIndex: 0, results: [{ isFinal, 0: { transcript: text } }] });
  }
}

const spk = { busy: false, spoken: [] as string[], cancel: vi.fn(), onIdle: undefined as undefined | (() => void) };
const vad = { emit: (_e: VadEvent) => {}, stop: vi.fn(), opened: 0 };

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
    onError: undefined,
  };
}
vi.mock("./vad", () => ({
  startMicVad: async (cb: (e: VadEvent) => void) => {
    vad.emit = cb;
    vad.opened++;
    return { stream: {}, machine: { sensitivity: 1, speaking: false }, level: () => 0, stop: vad.stop };
  },
}));

const { useVoiceMode } = await import("./useVoiceMode");

const flush = () => act(async () => {
  await Promise.resolve();
  await Promise.resolve();
});

function setup(mode: "tap" | "handsfree" | undefined, messages: ChatMsg[] = []) {
  const send = vi.fn(() => true);
  const cancel = vi.fn();
  const hook = renderHook((p: { messages: ChatMsg[] }) => useVoiceMode({ messages: p.messages, send, cancel, lang: "en", ...(mode ? { mode } : {}) }), { initialProps: { messages } });
  return { ...hook, send, cancel };
}
const rec = () => FakeRecognition.all.at(-1)!;
const host = (content: string, streaming: boolean): ChatMsg[] => [{ id: "a1", role: "assistant", content, streaming }];

beforeEach(() => {
  FakeRecognition.all = [];
  spk.busy = false;
  spk.spoken = [];
  spk.cancel.mockClear();
  vad.stop.mockClear();
  vad.opened = 0;
});
afterEach(() => vi.useRealTimers());

describe("tap-to-talk", () => {
  it("keeps the mic closed until a tap", async () => {
    const { result } = setup("tap");
    await act(() => result.current.start());
    expect(result.current.state).toBe("ready");
    expect(vad.opened).toBe(0);
    expect(FakeRecognition.all).toHaveLength(0);
  });

  it("joins every final from one tap and sends exactly one message when the learner falls silent", async () => {
    const { result, send } = setup("tap");
    await act(() => result.current.start());
    await act(() => result.current.listen());
    expect(result.current.listening).toBe(true);
    act(() => {
      vad.emit("speech-start");
      rec().say("a prompt is");
      rec().say("an instruction", false);
    });
    expect(result.current.interim).toBe("a prompt is an instruction");
    act(() => rec().say("an instruction to the AI"));
    expect(send).not.toHaveBeenCalled(); // finals alone don't send
    act(() => vad.emit("speech-end"));
    await flush();
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith("a prompt is an instruction to the AI");
    expect(vad.stop).toHaveBeenCalled(); // the mic closes after the turn
    expect(result.current.state).toBe("thinking");
    // Late recognition noise after the turn sends nothing more.
    act(() => rec().onresult?.({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript: "echo" } }] }));
    act(() => rec().onend?.());
    await flush();
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("“tap to send” sends what was heard right away", async () => {
    const { result, send } = setup("tap");
    await act(() => result.current.start());
    await act(() => result.current.listen());
    act(() => rec().say("yes", false));
    act(() => result.current.finish());
    await flush();
    expect(send).toHaveBeenCalledWith("yes");
  });

  it("closes the mic when the host starts speaking, and never interrupts the host by itself", async () => {
    const { result, rerender, send, cancel } = setup("tap");
    await act(() => result.current.start());
    await act(() => result.current.listen());
    rerender({ messages: host("Think of a prompt like ordering at a hotel. ", true) });
    await flush();
    expect(spk.spoken.length).toBeGreaterThan(0);
    expect(vad.stop).toHaveBeenCalled();
    expect(result.current.listening).toBe(false);
    act(() => rec().say("Think of a prompt"));
    await flush();
    expect(send).not.toHaveBeenCalled();
    expect(cancel).not.toHaveBeenCalled();
    expect(spk.cancel).not.toHaveBeenCalled();
  });

  it("a deliberate tap (interrupt) stops the speech and the reply, and the rest of that reply stays silent", async () => {
    const { result, rerender, cancel } = setup("tap");
    await act(() => result.current.start());
    rerender({ messages: host("First sentence here. ", true) });
    await flush();
    act(() => result.current.interrupt());
    expect(spk.cancel).toHaveBeenCalled();
    expect(cancel).toHaveBeenCalledTimes(1);
    const before = spk.spoken.length;
    rerender({ messages: host("First sentence here. Second sentence too. ", true) });
    await flush();
    expect(spk.spoken.length).toBe(before);
  });
});

describe("hands-free", () => {
  it("pauses recognition while the host talks, so its echo can never be sent, and resumes after", async () => {
    const { result, rerender, send, cancel } = setup("handsfree");
    await act(() => result.current.start());
    const r = rec();
    expect(r.running).toBe(true);
    rerender({ messages: host("Shall we move on? ", true) });
    await flush();
    expect(r.aborts).toBe(1);
    expect(r.running).toBe(false);
    // The speaker's own words picked up by the mic: ignored, no barge-in.
    act(() => {
      vad.emit("speech-start");
      r.say("shall we move on");
      vad.emit("speech-end");
    });
    await flush();
    expect(send).not.toHaveBeenCalled();
    expect(cancel).not.toHaveBeenCalled();
    // Reply finished and spoken: listening resumes.
    rerender({ messages: host("Shall we move on? ", false) });
    act(() => {
      spk.busy = false;
      spk.onIdle?.();
    });
    await flush();
    expect(r.running).toBe(true);
    act(() => {
      vad.emit("speech-start");
      r.say("yes");
      r.say("let's go");
      vad.emit("speech-end");
    });
    await flush();
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith("yes let's go");
    expect(r.running).toBe(true); // keeps listening
  });
});

describe("never stuck on “Hearing you…” (seen live)", () => {
  it("tap: speech ended but the recogniser gave no words → back to Tap to talk with a hint, nothing sent", async () => {
    const { result, send } = setup("tap");
    await act(() => result.current.start());
    await act(() => result.current.listen());
    act(() => vad.emit("speech-start"));
    expect(result.current.state).toBe("hearing");
    act(() => vad.emit("speech-end"));
    await flush();
    expect(send).not.toHaveBeenCalled();
    expect(result.current.state).toBe("ready");
    expect(result.current.error).toBe("stt_no_words");
    expect(result.current.listening).toBe(false);
  });

  it("hands-free: no words → keeps listening (not stuck on hearing) and the next words clear the hint", async () => {
    const { result, send } = setup("handsfree");
    await act(() => result.current.start());
    act(() => vad.emit("speech-start"));
    act(() => vad.emit("speech-end"));
    await flush();
    expect(result.current.state).toBe("listening");
    expect(result.current.error).toBe("stt_no_words");
    act(() => {
      vad.emit("speech-start");
      rec().say("what is a prompt");
    });
    expect(result.current.error).toBeNull();
    act(() => vad.emit("speech-end"));
    await flush();
    expect(send).toHaveBeenCalledWith("what is a prompt");
  });

  it("a recogniser that never answers is reset after a few seconds", async () => {
    vi.useFakeTimers();
    try {
      const { result } = setup("tap");
      await act(() => result.current.start());
      await act(() => result.current.listen());
      const r = rec();
      r.stop = () => {
        r.running = false; // Chrome sometimes never fires "end"
      };
      act(() => vad.emit("speech-start"));
      act(() => vad.emit("speech-end"));
      expect(result.current.state).toBe("hearing");
      act(() => void vi.advanceTimersByTime(4100));
      expect(result.current.state).toBe("ready");
      expect(result.current.error).toBe("stt_no_words");
    } finally {
      vi.useRealTimers();
    }
  });

  it("a network error from the browser's speech service is shown, not swallowed", async () => {
    const { result } = setup("tap");
    await act(() => result.current.start());
    await act(() => result.current.listen());
    act(() => rec().onerror?.({ error: "network" }));
    expect(result.current.error).toBe("stt_network");
  });
});

describe("one recogniser at a time (seen live: words went to an orphan)", () => {
  it("a leftover recogniser that hears words is stopped, sends nothing, and the live one is restarted", async () => {
    vi.useFakeTimers();
    try {
      const send = vi.fn(() => true);
      const hook = renderHook((p: { mode: "tap" | "handsfree" }) => useVoiceMode({ messages: [], send, cancel: vi.fn(), lang: "en", mode: p.mode }), { initialProps: { mode: "handsfree" as "tap" | "handsfree" } });
      await act(() => hook.result.current.start());
      const orphan = rec();
      // Re-plumb (tap → hands-free) creates a new live recogniser; the old one keeps delivering words, as Chrome did.
      hook.rerender({ mode: "tap" });
      hook.rerender({ mode: "handsfree" });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(50); // let the re-plumb open the mic (microtasks + a tick)
      });
      const live = rec();
      expect(live).not.toBe(orphan);
      live.running = false; // the live one never got the mic
      const abortsBefore = orphan.aborts;
      act(() => orphan.say("hello Tamil"));
      expect(orphan.aborts).toBe(abortsBefore + 1);
      expect(send).not.toHaveBeenCalled();
      const startsBefore = live.starts;
      await act(async () => void vi.advanceTimersByTime(200));
      expect(live.starts).toBe(startsBefore + 1);
    } finally {
      vi.useRealTimers();
    }
  });
});
