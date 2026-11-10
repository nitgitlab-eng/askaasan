import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatMsg } from "@/lib/useMentorSocket";

import { FILLERS, pickFiller, THINK_FILLER_MS, type FillerKind } from "./fillers";
import type { VadEvent } from "./vad";

// ── Fakes: a browser recogniser and a speaker that records what it was asked to say. ─────────────────────────────
class FakeRecognition {
  static all: FakeRecognition[] = [];
  lang = "";
  continuous = false;
  interimResults = false;
  running = false;
  results: { isFinal: boolean; 0: { transcript: string } }[] = [];
  onresult: ((e: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null = null;
  onerror: ((e: { error: string }) => void) | null = null;
  onend: (() => void) | null = null;
  constructor() {
    FakeRecognition.all.push(this);
  }
  start() {
    this.running = true;
    this.results = [];
  }
  stop() {
    this.running = false;
  }
  abort() {
    this.running = false;
  }
  hear(text: string) {
    this.results = [{ isFinal: true, 0: { transcript: text } }];
    this.onresult?.({ resultIndex: 0, results: [...this.results] });
  }
}

const spk = { busy: false, spoken: [] as string[], ends: 0 };
const vad = { emit: (_e: VadEvent) => {} };

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
    },
    end() {
      spk.ends++;
    },
    get busy() {
      return spk.busy;
    },
    level: () => 0,
  };
}
vi.mock("./vad", () => ({
  startMicVad: async (cb: (e: VadEvent) => void) => {
    vad.emit = cb;
    return { stream: {}, machine: { sensitivity: 1, speaking: false }, level: () => 0, stop: vi.fn() };
  },
}));

const { useVoiceMode } = await import("./useVoiceMode");

type Props = { messages: ChatMsg[]; busy?: boolean; activity?: "searching" | null; speak?: boolean };

function setup(opts: { fillers?: FillerKind; lang?: "en" | "ta" } = {}) {
  const send = vi.fn(() => true);
  const hook = renderHook(
    (p: Props) =>
      useVoiceMode({
        messages: p.messages,
        send,
        cancel: vi.fn(),
        lang: opts.lang ?? "en",
        mode: "conversation",
        busy: p.busy,
        activity: p.activity ?? null,
        speak: p.speak ?? true,
        fillers: opts.fillers,
      }),
    { initialProps: { messages: [] } as Props },
  );
  return { ...hook, send };
}

const asked: ChatMsg[] = [{ id: "u1", role: "user", content: "gold price today?" }];
const reply = (content: string, streaming: boolean): ChatMsg[] => [...asked, { id: "a1", role: "assistant", content, streaming }];
const isFiller = (t: string, kind: "search" | "think", lang: "en" | "ta" = "en") => FILLERS[lang][kind].includes(t);

async function askQuestion(h: ReturnType<typeof setup>) {
  await act(() => h.result.current.start());
  act(() => {
    FakeRecognition.all.at(-1)!.hear("gold price today?");
    vad.emit("speech-end");
  });
  expect(h.send).toHaveBeenCalledWith("gold price today?");
  h.rerender({ messages: asked, busy: true });
}

beforeEach(() => {
  FakeRecognition.all = [];
  spk.busy = false;
  spk.spoken = [];
  spk.ends = 0;
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("spoken fillers", () => {
  it("says one search line when the server starts searching, and shows it is searching", async () => {
    const h = setup();
    await askQuestion(h);
    h.rerender({ messages: asked, busy: true, activity: "searching" });
    expect(spk.spoken).toHaveLength(1);
    expect(isFiller(spk.spoken[0], "search")).toBe(true);
    expect(h.result.current.searching).toBe(true);
    expect(h.result.current.state).toBe("thinking");
    // Still searching past the thinking delay: no second filler.
    await act(async () => void vi.advanceTimersByTime(THINK_FILLER_MS * 2));
    expect(spk.spoken).toHaveLength(1);
  });

  it("says a thinking line when the first word is slow, and only one per turn", async () => {
    const h = setup();
    await askQuestion(h);
    await act(async () => void vi.advanceTimersByTime(THINK_FILLER_MS));
    expect(spk.spoken).toHaveLength(1);
    expect(isFiller(spk.spoken[0], "think")).toBe(true);
    h.rerender({ messages: asked, busy: true, activity: "searching" });
    expect(spk.spoken).toHaveLength(1);
  });

  it("stays quiet when the reply starts quickly", async () => {
    const h = setup();
    await askQuestion(h);
    h.rerender({ messages: reply("Gold is", true), busy: true });
    await act(async () => void vi.advanceTimersByTime(THINK_FILLER_MS * 2));
    expect(spk.spoken.some((t) => isFiller(t, "think") || isFiller(t, "search"))).toBe(false);
  });

  it("the reply's words follow the filler and are never mixed into the message", async () => {
    const h = setup();
    await askQuestion(h);
    h.rerender({ messages: asked, busy: true, activity: "searching" });
    h.rerender({ messages: reply("Gold is ₹7,000 today. ", true), busy: true });
    h.rerender({ messages: reply("Gold is ₹7,000 today. Want the 22 carat rate?", false), busy: false });
    expect(isFiller(spk.spoken[0], "search")).toBe(true);
    expect(spk.spoken.slice(1).join(" ")).toContain("Gold is ₹7,000 today.");
    expect(h.result.current.searching).toBe(false);
  });

  it("closes the filler when no reply follows (an error), so a live call doesn't wait for more", async () => {
    const h = setup();
    await askQuestion(h);
    h.rerender({ messages: asked, busy: true, activity: "searching" });
    expect(spk.ends).toBe(0);
    h.rerender({ messages: asked, busy: false, activity: null });
    expect(spk.ends).toBe(1);
  });

  it("role-play and workshops only use the neutral thinking line", async () => {
    const h = setup({ fillers: "think" });
    await askQuestion(h);
    h.rerender({ messages: asked, busy: true, activity: "searching" });
    expect(spk.spoken).toHaveLength(0);
    await act(async () => void vi.advanceTimersByTime(THINK_FILLER_MS));
    expect(isFiller(spk.spoken[0], "think")).toBe(true);
  });

  it("no fillers when fillers are off", async () => {
    const quiet = setup({ fillers: "none" });
    await askQuestion(quiet);
    quiet.rerender({ messages: asked, busy: true, activity: "searching" });
    await act(async () => void vi.advanceTimersByTime(THINK_FILLER_MS));
    expect(spk.spoken).toHaveLength(0);
  });

  it("no fillers when reading aloud is off", async () => {
    const h = setup();
    h.rerender({ messages: [], speak: false });
    await act(() => h.result.current.start());
    act(() => {
      FakeRecognition.all.at(-1)!.hear("gold price today?");
      vad.emit("speech-end");
    });
    h.rerender({ messages: asked, busy: true, speak: false, activity: "searching" });
    await act(async () => void vi.advanceTimersByTime(THINK_FILLER_MS));
    expect(spk.spoken).toHaveLength(0);
  });

  it("speaks in the voice's language", async () => {
    const h = setup({ lang: "ta" });
    await askQuestion(h);
    h.rerender({ messages: asked, busy: true, activity: "searching" });
    expect(isFiller(spk.spoken[0], "search", "ta")).toBe(true);
  });

  it("an interrupt cancels a pending thinking line", async () => {
    const h = setup();
    await askQuestion(h);
    act(() => h.result.current.interrupt());
    await act(async () => void vi.advanceTimersByTime(THINK_FILLER_MS * 2));
    expect(spk.spoken).toHaveLength(0);
  });
});

describe("pickFiller", () => {
  it("picks from the language's lines and falls back to English", () => {
    expect(pickFiller("en", "search", () => 0)).toBe(FILLERS.en.search[0]);
    expect(pickFiller("ta", "think", () => 0.99)).toBe(FILLERS.ta.think.at(-1));
    expect(pickFiller("xx" as "en", "think", () => 0)).toBe(FILLERS.en.think[0]);
  });
});
