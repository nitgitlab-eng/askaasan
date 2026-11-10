import { afterEach, describe, expect, it, vi } from "vitest";

import { useAuth } from "@/stores/auth";

import { serverSpeaker } from "./engines";

class FakeUtterance {
  text: string;
  lang = "";
  rate = 1;
  voice: unknown = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onboundary: (() => void) | null = null;

  constructor(text: string) {
    this.text = text;
  }
}

const flush = () => new Promise((r) => setTimeout(r, 0));

describe("serverSpeaker", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("falls back to the browser voice on 503 and stays there", async () => {
    const spoken: FakeUtterance[] = [];
    vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);
    vi.stubGlobal("speechSynthesis", {
      getVoices: () => [{ lang: "en-IN" }],
      speak: (u: FakeUtterance) => spoken.push(u),
      cancel: vi.fn(),
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ code: "provider_not_configured" }), { status: 503 })));
    useAuth.setState({ access: "t" });

    const sp = serverSpeaker();
    const errors: string[] = [];
    const idle = vi.fn();
    sp.onError = (c) => errors.push(c);
    sp.onIdle = idle;
    sp.speak("Hello there.");
    await flush();
    await flush();
    expect(spoken.map((u) => u.text)).toEqual(["Hello there."]);
    expect(errors).toEqual([]);
    expect(sp.busy).toBe(true);
    spoken[0].onend?.();
    expect(idle).toHaveBeenCalled();

    sp.speak("Second line.");
    await flush();
    expect(spoken.map((u) => u.text)).toEqual(["Hello there.", "Second line."]);
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1); // no more server requests this session
  });

  it("falls back on network errors too", async () => {
    const spoken: string[] = [];
    vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);
    vi.stubGlobal("speechSynthesis", { getVoices: () => [{ lang: "en-IN" }], speak: (u: FakeUtterance) => spoken.push(u.text), cancel: vi.fn() });
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("offline"); }));
    const sp = serverSpeaker();
    sp.speak("Hi.");
    await flush();
    await flush();
    expect(spoken).toEqual(["Hi."]);
  });

  it("reads a sentence the server voice can't speak (422, e.g. Tamil with Deepgram) in the browser, just that once", async () => {
    const spoken: string[] = [];
    vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);
    vi.stubGlobal("speechSynthesis", { getVoices: () => [{ lang: "ta-IN" }], speak: (u: FakeUtterance) => spoken.push(u.text), cancel: vi.fn() });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ code: "unsupported_language" }), { status: 422 })));
    useAuth.setState({ access: "t" });
    const sp = serverSpeaker();
    const errors: string[] = [];
    sp.onError = (c) => errors.push(c);
    sp.speak("வணக்கம்.");
    await flush();
    await flush();
    expect(spoken).toEqual(["வணக்கம்."]);
    expect(errors).toEqual([]);
    sp.speak("Next line.");
    await flush();
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(2); // the server voice is still used for the next sentence
  });

  it("an English line with no server English voice is read in the browser once; Tamil lines keep the server voice", async () => {
    const spoken: string[] = [];
    vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);
    vi.stubGlobal("speechSynthesis", { getVoices: () => [{ lang: "en-IN" }], speak: (u: FakeUtterance) => spoken.push(u.text), cancel: vi.fn() });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ code: "use_browser_engine" }), { status: 400 })));
    useAuth.setState({ access: "t" });
    const sp = serverSpeaker();
    sp.speak("Hello there.");
    await flush();
    await flush();
    expect(spoken).toEqual(["Hello there."]);
    sp.speak("வணக்கம்.");
    await flush();
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(2); // not stuck on the browser voice for the rest of the reply
  });
});
