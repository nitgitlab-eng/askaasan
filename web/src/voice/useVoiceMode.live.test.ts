import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatMsg } from "@/lib/useMentorSocket";

import type { StreamEvent } from "./stream";
import type { VadEvent } from "./vad";

// ── Fakes: the voice config (streaming on/off), a speaker the test controls, the stream socket and the VAD. ────────
const cfg = { streaming: true };
const spk = { busy: false, spoken: [] as string[], cancel: vi.fn(), onStart: undefined as undefined | ((t: string) => void), onIdle: undefined as undefined | (() => void) };
const live = { emit: (_e: StreamEvent) => {}, opened: 0, langs: [] as string[], stop: vi.fn(), fail: "" };
const vad = { emit: (_e: VadEvent) => {}, opened: 0 };

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
  fetchVoiceConfig: async () => ({ stt: { engine: "server", provider: "deepgram", streaming: cfg.streaming }, tts: { engine: "browser", provider: "browser" } }),
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
    set onStart(f: ((t: string) => void) | undefined) {
      spk.onStart = f;
    },
    get onStart() {
      return spk.onStart;
    },
    onError: undefined,
  };
}
vi.mock("./stream", () => ({
  FATAL_STREAM_ERRORS: new Set(["plan_limit", "voice_budget_exceeded", "streaming_unavailable"]),
  openVoiceStream: async (lang: string, onEvent: (e: StreamEvent) => void) => {
    if (live.fail) throw new Error(live.fail);
    live.emit = onEvent;
    live.opened++;
    live.langs.push(lang);
    return { stop: live.stop, level: () => 0 };
  },
}));
vi.mock("./vad", () => ({
  startMicVad: async (cb: (e: VadEvent) => void) => {
    vad.emit = cb;
    vad.opened++;
    return { stream: {}, machine: { sensitivity: 1, speaking: false }, level: () => 0, stop: vi.fn() };
  },
}));

const { useVoiceMode } = await import("./useVoiceMode");

const flush = () =>
  act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });

interface Props {
  messages: ChatMsg[];
  busy: boolean;
  lang: "en" | "ta";
}
function setup(messages: ChatMsg[] = []) {
  const send = vi.fn(() => true);
  const cancel = vi.fn();
  const hook = renderHook((p: Props) => useVoiceMode({ messages: p.messages, send, cancel, lang: p.lang, mode: "handsfree", busy: p.busy }), {
    initialProps: { messages, busy: false, lang: "en" },
  });
  return { ...hook, send, cancel };
}
const host = (content: string, streaming: boolean): ChatMsg[] => [
  { id: "u1", role: "user", content: "hi" },
  { id: "a1", role: "assistant", content, streaming },
];
const say = (text: string) => act(() => live.emit({ type: "interim", text }));
const final = (text: string, speech_final = false) => act(() => live.emit({ type: "final", text, speech_final }));

/** Aasan is mid-reply and speaking `sentence` out loud. */
async function aasanSpeaking(h: ReturnType<typeof setup>, sentence: string) {
  h.rerender({ messages: host(`${sentence} And more`, true), busy: true, lang: "en" });
  await flush();
  act(() => spk.onStart?.(sentence));
  expect(spk.busy).toBe(true);
}

beforeEach(() => {
  cfg.streaming = true;
  spk.busy = false;
  spk.spoken = [];
  spk.cancel.mockClear();
  live.opened = 0;
  live.langs = [];
  live.stop.mockClear();
  live.fail = "";
  vad.opened = 0;
  FakeRecognition.all = [];
});

describe("live conversation (streamed listening)", () => {
  it("Aasan's last words heard just after it stops are dropped; new words just after are kept", async () => {
    const h = setup();
    await act(() => h.result.current.start());
    await flush();
    await aasanSpeaking(h, "Tokens are small pieces of text the model reads.");
    h.rerender({ messages: host("Tokens are small pieces of text the model reads.", false), busy: false, lang: "en" });
    act(() => {
      spk.busy = false;
      spk.onIdle?.();
    });
    final("pieces of text the model reads", true);
    expect(h.send).not.toHaveBeenCalled();
    final("ok so what is a context window", true);
    expect(h.send).toHaveBeenCalledWith("ok so what is a context window");
  });

  it("opens one continuous stream, not the browser recogniser, and stays listening while Aasan speaks", async () => {
    const h = setup();
    await act(() => h.result.current.start());
    expect(h.result.current.live).toBe(true);
    expect(live.opened).toBe(1);
    expect(vad.opened).toBe(0);
    expect(FakeRecognition.all).toHaveLength(0);
    await aasanSpeaking(h, "A prompt is an instruction you give the AI.");
    expect(h.result.current.state).toBe("speaking");
    expect(live.stop).not.toHaveBeenCalled(); // never paused
    expect(live.opened).toBe(1);
  });

  it("shows live interim captions of the learner's words", async () => {
    const h = setup();
    await act(() => h.result.current.start());
    say("what is");
    expect(h.result.current.interim).toBe("what is");
    expect(h.result.current.state).toBe("hearing");
    final("what is a prompt");
    say("used for");
    expect(h.result.current.interim).toBe("what is a prompt used for");
  });

  it("sends the turn's finals as one voice message on speech_final", async () => {
    const h = setup();
    await act(() => h.result.current.start());
    final("what is");
    final("a prompt");
    expect(h.send).not.toHaveBeenCalled();
    final("", true);
    expect(h.send).toHaveBeenCalledTimes(1);
    expect(h.send).toHaveBeenCalledWith("what is a prompt");
    expect(h.result.current.interim).toBe("");
  });

  it("utterance_end also ends the turn", async () => {
    const h = setup();
    await act(() => h.result.current.start());
    final("tell me about tokens");
    act(() => live.emit({ type: "utterance_end" }));
    expect(h.send).toHaveBeenCalledWith("tell me about tokens");
  });

  it("barge-in: 2+ words that are not Aasan's echo stop the speech and the reply", async () => {
    const h = setup();
    await act(() => h.result.current.start());
    await aasanSpeaking(h, "A prompt is an instruction you give the AI.");
    say("hold on");
    expect(spk.cancel).toHaveBeenCalled();
    expect(h.cancel).toHaveBeenCalledTimes(1);
    expect(h.result.current.interim).toBe("hold on");
    // The rest of their utterance is the next turn, sent once the cut-off reply has wound down.
    final("hold on what about images", true);
    expect(h.send).not.toHaveBeenCalled();
    h.rerender({ messages: host("A prompt is", false), busy: false, lang: "en" });
    await flush();
    expect(h.send).toHaveBeenCalledWith("hold on what about images");
  });

  it("an echo of the sentence Aasan is saying does NOT interrupt and is never sent", async () => {
    const h = setup();
    await act(() => h.result.current.start());
    await aasanSpeaking(h, "A prompt is an instruction you give the AI.");
    say("an instruction you give");
    final("a prompt is an instruction", true);
    expect(spk.cancel).not.toHaveBeenCalled();
    expect(h.cancel).not.toHaveBeenCalled();
    expect(h.result.current.interim).toBe("");
    expect(h.send).not.toHaveBeenCalled();
  });

  it("one stray word while Aasan talks is ignored", async () => {
    const h = setup();
    await act(() => h.result.current.start());
    await aasanSpeaking(h, "Tokens are pieces of words.");
    say("hmm");
    expect(h.cancel).not.toHaveBeenCalled();
  });

  it("“Aasan” always cuts in, and is stripped from what is sent", async () => {
    const h = setup();
    await act(() => h.result.current.start());
    await aasanSpeaking(h, "A prompt is an instruction you give the AI.");
    say("Aasan");
    expect(h.cancel).toHaveBeenCalledTimes(1);
    expect(spk.cancel).toHaveBeenCalled();
    expect(h.result.current.interim).toBe("");
    h.rerender({ messages: host("A prompt is", false), busy: false, lang: "en" });
    await flush();
    final("Aasan, what is a token?", true);
    expect(h.send).toHaveBeenCalledWith("what is a token?");
  });

  it("saying only “Aasan” stops Aasan and keeps listening, sending nothing", async () => {
    const h = setup();
    await act(() => h.result.current.start());
    await aasanSpeaking(h, "Here is a long explanation.");
    final("Aasan.", true);
    expect(h.cancel).toHaveBeenCalledTimes(1);
    h.rerender({ messages: host("Here is", false), busy: false, lang: "en" });
    await flush();
    expect(h.send).not.toHaveBeenCalled();
    expect(h.result.current.state).toBe("listening");
  });

  it("“stop” and நிறுத்து cut in too", async () => {
    const h = setup();
    await act(() => h.result.current.start());
    await aasanSpeaking(h, "Machine learning finds patterns.");
    say("stop");
    expect(h.cancel).toHaveBeenCalledTimes(1);
    const t = setup();
    await act(() => t.result.current.start());
    await aasanSpeaking(t, "Machine learning finds patterns.");
    say("நிறுத்து");
    expect(t.cancel).toHaveBeenCalledTimes(1);
  });

  it("a fatal stream error is shown and live listening stops", async () => {
    const h = setup();
    await act(() => h.result.current.start());
    act(() => live.emit({ type: "error", code: "voice_budget_exceeded" }));
    expect(h.result.current.error).toBe("voice_budget_exceeded");
    expect(h.result.current.state).toBe("off");
    expect(live.stop).toHaveBeenCalled();
  });

  it("re-opens the stream in the new language", async () => {
    const h = setup();
    await act(() => h.result.current.start());
    h.rerender({ messages: [], busy: false, lang: "ta" });
    await flush();
    await flush();
    expect(live.langs).toEqual(["en", "ta"]);
  });
});

describe("fallback to the old hands-free", () => {
  it("uses the paused browser-recogniser hands-free when the server can't stream", async () => {
    cfg.streaming = false;
    const h = setup();
    await act(() => h.result.current.start());
    expect(h.result.current.live).toBe(false);
    expect(live.opened).toBe(0);
    expect(vad.opened).toBe(1);
  });

  it("falls back when the stream can't be opened", async () => {
    live.fail = "streaming_unavailable";
    const h = setup();
    await act(() => h.result.current.start());
    expect(h.result.current.live).toBe(false);
    expect(h.result.current.state).toBe("listening");
    expect(vad.opened).toBe(1);
  });
});
