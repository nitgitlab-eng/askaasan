import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { lessonParts } from "@/components/lesson/narration-hooks";

import { fetchClip, fetchVoiceConfig, type ClipRequest } from "./engines";
import { browserLang, CLIP_MAX, lineLang, Narrator, sentences, serverLang, type NarratorState } from "./narrator";

vi.mock("./engines", async (orig) => ({
  ...(await orig<typeof import("./engines")>()),
  fetchVoiceConfig: vi.fn(),
  fetchClip: vi.fn(),
}));

/** A stand-in <audio>: records what it was asked to play; the test ends clips by hand. */
class FakeAudio {
  static all: FakeAudio[] = [];
  src = "";
  playbackRate = 1;
  currentTime = 0;
  duration = 3;
  ended = false;
  played: string[] = [];
  onended: (() => void) | null = null;
  constructor() { FakeAudio.all.push(this); }
  play() { if (!this.src.startsWith("data:")) this.played.push(this.src); return Promise.resolve(); }
  pause() {}
  addEventListener() {}
  removeAttribute() {}
}

const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
const asked = () => vi.mocked(fetchClip).mock.calls.map(([req]) => req.text);

beforeEach(() => {
  FakeAudio.all = [];
  vi.stubGlobal("Audio", FakeAudio);
  vi.mocked(fetchVoiceConfig).mockResolvedValue({
    stt: { engine: "browser", provider: "browser" },
    tts: { engine: "server", provider: "deepgram" },
    tts_ta: { engine: "server", provider: "sarvam" },
  });
  vi.mocked(fetchClip).mockImplementation(async (req: ClipRequest) => ({ url: `/api/media/speech/${req.text.length}-${req.voice_role}.mp3`, cached: false }));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(fetchClip).mockReset();
  vi.mocked(fetchVoiceConfig).mockReset();
  vi.useRealTimers();
});

describe("sentences", () => {
  it("joins whole sentences into clips and never splits one mid-sentence", () => {
    const long = Array.from({ length: 30 }, (_, i) => `Sentence number ${i} is here.`).join(" ");
    const out = sentences(long);
    expect(out.length).toBeGreaterThan(1);
    expect(out.every((s) => s.length <= CLIP_MAX && s.endsWith("."))).toBe(true);
    expect(out.join(" ")).toBe(long);
  });
  it("cuts a single over-long sentence at a space", () => {
    const out = sentences("One. Two! Three? " + "word ".repeat(200));
    expect(out[0].startsWith("One. Two! Three?")).toBe(true);
    expect(out.every((s) => s.length <= CLIP_MAX)).toBe(true);
    expect(out.every((s) => !s.endsWith("wor"))).toBe(true);
  });
  it("splits Hindi danda and strips markdown symbols", () => {
    const out = sentences("**नमस्ते**। यह पाठ है।");
    expect(out.join(" ")).not.toContain("*");
  });
});

describe("lessonParts", () => {
  it("splits by headings with labels", () => {
    const p = lessonParts("Intro text\n\n## Rows\nA row is a record.\n\n## Columns\nA column is a field.", "Tables");
    expect(p.map((x) => x.label)).toEqual(["Tables", "Rows", "Columns"]);
  });
  it("groups paragraphs when there are no headings", () => {
    const p = lessonParts("a\n\nb\n\nc\n\nd", "T");
    expect(p).toHaveLength(2);
  });
});

describe("narrator language", () => {
  it("speaks Tanglish (Tamil script) with the Tamil voice on both paths", () => {
    expect(serverLang("tanglish")).toBe("ta");
    expect(browserLang("tanglish")).toBe("ta-IN");
    expect(serverLang("ta")).toBe("ta");
    expect(serverLang("en")).toBe("en");
    expect(browserLang("hi")).toBe("hi-IN");
    expect(lineLang("வணக்கம் Kavya", "en")).toBe("ta");
    expect(lineLang("Hello", "en")).toBe("en");
  });
});

describe("Narrator", () => {
  const parts = ["First part.", "Second part!", "Third part?", "Fourth part.", "Fifth part."];

  it("fetches nothing until play", async () => {
    new Narrator(parts, "en", () => {});
    await flush();
    expect(fetchVoiceConfig).not.toHaveBeenCalled();
    expect(fetchClip).not.toHaveBeenCalled();
  });

  it("plays clip URLs in order, asks for 2 ahead, and hands the rest to the server to warm", async () => {
    const states: NarratorState[] = [];
    const done: number[] = [];
    const n = new Narrator(parts, "en", (s) => states.push(s), { onPartDone: (p) => done.push(p) });
    n.play();
    await flush();
    expect(fetchVoiceConfig).toHaveBeenCalledTimes(1);
    const [first, warm] = vi.mocked(fetchClip).mock.calls[0];
    expect(first).toEqual({ text: "First part.", lang: "en", voice_role: "narrator" });
    expect(warm?.map((w) => w.text)).toEqual(["Fourth part.", "Fifth part."]); // after the prefetch window
    expect(asked()).toEqual(["First part.", "Second part!", "Third part?"]); // the one playing + 2 ahead
    const el = FakeAudio.all[0];
    expect(el.played).toEqual(["/api/media/speech/11-narrator.mp3"]);

    el.onended?.();
    await flush();
    expect(el.played[1]).toBe("/api/media/speech/12-narrator.mp3");
    expect(asked()).toEqual(["First part.", "Second part!", "Third part?", "Fourth part."]); // the window moved on
    expect(states.at(-1)?.part).toBe(1); // the transcript highlight follows the clip
    expect(done).toEqual([0]);
    expect(vi.mocked(fetchClip).mock.calls.slice(1).every(([, w]) => !w?.length)).toBe(true); // warm only once
  });

  it("a replay reuses the clip URLs it already has", async () => {
    const n = new Narrator(parts.slice(0, 2), "en", () => {});
    n.play();
    await flush();
    n.goTo(0);
    await flush();
    expect(asked().filter((t) => t === "First part.")).toHaveLength(1);
    expect(FakeAudio.all[0].played).toEqual(["/api/media/speech/11-narrator.mp3", "/api/media/speech/11-narrator.mp3"]);
  });

  it("podcast hosts ask for different voices, with a short pause between speakers", async () => {
    vi.useFakeTimers();
    const n = new Narrator(["Hi, I'm Meera.", "And I'm Arjun."], "en", () => {}, { roles: ["host_a", "host_b"], turnGapMs: 350 });
    n.play();
    await vi.advanceTimersByTimeAsync(0);
    expect(vi.mocked(fetchClip).mock.calls.map(([r]) => r.voice_role)).toEqual(["host_a", "host_b"]);
    const el = FakeAudio.all[0];
    el.onended?.();
    await vi.advanceTimersByTimeAsync(100);
    expect(el.played).toHaveLength(1); // still pausing between turns
    await vi.advanceTimersByTimeAsync(300);
    expect(el.played).toEqual(["/api/media/speech/14-host_a.mp3", "/api/media/speech/14-host_b.mp3"]);
    expect(el.playbackRate).toBe(1); // no pitch / rate trick for the second host
  });
});
