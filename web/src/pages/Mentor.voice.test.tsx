import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import type { ChatMsg } from "@/lib/useMentorSocket";
import type { VadEvent } from "@/voice/vad";

// ── Fakes: browser recognition, a speaker the test can finish, a VAD the test drives, and the chat socket. ────────
type Result = { isFinal: boolean; 0: { transcript: string } };
class FakeRecognition {
  static all: FakeRecognition[] = [];
  lang = "";
  continuous = false;
  interimResults = false;
  running = false;
  starts = 0;
  onresult: ((e: { resultIndex: number; results: ArrayLike<Result> }) => void) | null = null;
  onerror: ((e: { error: string }) => void) | null = null;
  onend: (() => void) | null = null;
  constructor() {
    FakeRecognition.all.push(this);
  }
  results: Result[] = [];
  start() {
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
  /** Like Chrome in continuous mode: one growing result list; an interim is refined in place until it is final. */
  say(text: string, isFinal = true) {
    const last = this.results.at(-1);
    const idx = last && !last.isFinal ? this.results.length - 1 : this.results.length;
    this.results[idx] = { isFinal, 0: { transcript: text } };
    this.onresult?.({ resultIndex: idx, results: [...this.results] });
  }
}

const h = vi.hoisted(() => ({
  spk: { busy: false, spoken: [] as string[], cancel: vi.fn(), onIdle: undefined as undefined | (() => void) },
  vad: { emit: (_e: VadEvent) => {}, stop: vi.fn(), opened: 0, deny: false },
  fetchVoiceConfig: vi.fn(async () => ({ stt: { engine: "browser", provider: "browser" }, tts: { engine: "server", provider: "deepgram" } })),
  sock: { setMessages: null as null | ((f: (m: ChatMsg[]) => ChatMsg[]) => void), send: vi.fn(), cancel: vi.fn(), busy: false },
  mutate: vi.fn(),
  prefs: { voice: { workshop_mode: "tap", mentor_mode: "tap", mentor_read_aloud: true, mentor_lang: "en" } as Record<string, unknown> },
  live: { emit: null as null | ((e: { type: string; text?: string; speech_final?: boolean }) => void), opened: 0 },
}));
vi.mock("@/voice/stream", () => ({
  FATAL_STREAM_ERRORS: new Set(["plan_limit"]),
  openVoiceStream: vi.fn(async (_lang: string, onEvent: (e: { type: string }) => void) => {
    h.live.emit = onEvent;
    h.live.opened++;
    return { stop: vi.fn(), level: () => 0 };
  }),
}));

vi.mock("@/voice/engines", () => ({
  BCP47: { en: "en-IN", ta: "ta-IN" },
  get BrowserRecognition() {
    return FakeRecognition;
  },
  fetchVoiceConfig: h.fetchVoiceConfig,
  unlockAudio: () => {},
  serverTranscribe: vi.fn(),
  startClip: vi.fn(),
  serverSpeaker: () => makeSpeaker(),
  browserSpeaker: () => makeSpeaker(),
}));
function makeSpeaker() {
  return {
    speak(t: string) {
      h.spk.spoken.push(t);
      h.spk.busy = true;
    },
    cancel() {
      h.spk.busy = false;
      h.spk.cancel();
    },
    get busy() {
      return h.spk.busy;
    },
    level: () => 0,
    set onIdle(f: (() => void) | undefined) {
      h.spk.onIdle = f;
    },
    get onIdle() {
      return h.spk.onIdle;
    },
    onError: undefined,
  };
}
vi.mock("@/voice/vad", () => ({
  startMicVad: vi.fn(async (cb: (e: VadEvent) => void) => {
    if (h.vad.deny) throw Object.assign(new Error("Permission denied"), { name: "NotAllowedError" });
    h.vad.emit = cb;
    h.vad.opened++;
    return { stream: {}, machine: { sensitivity: 1, speaking: false }, level: () => 0, stop: h.vad.stop };
  }),
}));
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn(async () => null) }));
vi.mock("@/lib/useMentorSocket", () => ({
  useMentorSocket: () => {
    const [messages, setMessages] = useState<ChatMsg[]>([]);
    h.sock.setMessages = setMessages;
    return { status: "ready", messages, setMessages, busy: h.sock.busy, error: null, send: h.sock.send, cancel: h.sock.cancel, retry: () => false };
  },
}));
vi.mock("@/lib/useMe", () => ({
  useMe: () => ({
    data: {
      profile: { language: "en" },
      preferences: { mentor: { reply_language: "en" }, mascot: { color: "green", enabled: true }, appearance: { reduced_motion: true }, voice: h.prefs.voice },
    },
  }),
  useUpdatePreferences: () => ({ mutate: h.mutate }),
}));

const { startMicVad } = await import("@/voice/vad");
const { default: MentorPage } = await import("./Mentor");

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/mentor"]}>
        <Routes>
          <Route path="/mentor" element={<MentorPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const reply = (content: string, streaming = true) =>
  act(() => h.sock.setMessages!((m) => [...m.filter((x) => x.id !== "a1"), { id: "a1", role: "assistant", content, streaming }]));

/** Open the voice conversation and wait until it is really listening. */
async function openVoice() {
  fireEvent.click(screen.getByRole("button", { name: /voice conversation/i }));
  await waitFor(() => expect(FakeRecognition.all.at(-1)?.running).toBe(true));
  return FakeRecognition.all.at(-1)!;
}
const screenEl = () => screen.getByRole("region", { name: /voice conversation/i });

let fetchSpy: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  FakeRecognition.all = [];
  Object.assign(h.spk, { busy: false, spoken: [], onIdle: undefined });
  h.spk.cancel.mockClear();
  Object.assign(h.vad, { opened: 0, deny: false });
  h.vad.stop.mockClear();
  h.fetchVoiceConfig.mockClear();
  h.fetchVoiceConfig.mockImplementation(async () => ({ stt: { engine: "browser", provider: "browser" }, tts: { engine: "server", provider: "deepgram" } }));
  h.live.opened = 0;
  vi.mocked(startMicVad).mockClear();
  h.sock.busy = false;
  h.sock.send.mockReset().mockImplementation((text: string) => {
    act(() => h.sock.setMessages!((m) => [...m, { id: `u${m.length}`, role: "user", content: text }]));
    return true;
  });
  h.sock.cancel.mockClear();
  h.mutate.mockClear();
  h.prefs.voice = { workshop_mode: "tap", mentor_mode: "tap", mentor_read_aloud: true, mentor_lang: "en" };
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia: vi.fn() }, configurable: true });
  fetchSpy = vi.spyOn(globalThis, "fetch");
});
afterEach(() => {
  fetchSpy.mockRestore();
});

describe("Ask Aasan voice conversation", () => {
  it("opens no mic and shows no voice log until the learner starts a conversation", () => {
    renderPage();
    expect(screen.getByRole("button", { name: /voice conversation/i })).toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: /hands-free/i })).toBeNull();
    expect(screen.getByRole("switch", { name: /read answers aloud/i })).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByTestId("voice-debug")).toBeNull();
    expect(startMicVad).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(FakeRecognition.all).toHaveLength(0);
  });

  it("opens the conversation inside the chat; live words show as my message, each pause sends one turn, the mic stays open", async () => {
    renderPage();
    const rec = await openVoice();
    expect(screenEl()).toBeInTheDocument();
    expect(screen.getByTestId("voice-status")).toHaveTextContent(/listening/i);
    act(() => h.vad.emit("speech-start"));
    act(() => rec.say("what is a neural", false));
    expect(screen.getByTestId("me-caption")).toHaveTextContent("what is a neural"); // words show live
    act(() => rec.say("what is a neural network", false));
    act(() => h.vad.emit("speech-end"));
    expect(h.sock.send).toHaveBeenCalledTimes(1);
    expect(h.sock.send).toHaveBeenCalledWith("what is a neural network", { via: "voice" });
    expect(rec.running).toBe(true); // a conversation: no tap needed for the next turn
    expect(h.vad.stop).not.toHaveBeenCalled();
    // The recogniser's late final for the same words is not sent again.
    act(() => rec.say("what is a neural network"));
    await act(async () => await new Promise((r) => setTimeout(r, 20)));
    expect(h.sock.send).toHaveBeenCalledTimes(1);
  });

  it("English only: no language picker or prompt, and it always listens in English (even with Tamil saved)", async () => {
    h.prefs.voice = { mentor_mode: "tap", mentor_read_aloud: true, mentor_lang: "ta" };
    renderPage();
    expect(screen.queryByRole("group", { name: /i'll speak in/i })).toBeNull();
    expect(screen.queryByRole("button", { name: "தமிழ்" })).toBeNull();
    const rec = await openVoice(); // starts straight away: no "which language" question
    expect(screen.queryByRole("dialog", { name: /which language/i })).toBeNull();
    expect(rec.lang).toMatch(/^en/);
    expect(screen.queryByRole("button", { name: "தமிழ்" })).toBeNull();
  });

  it("speaks the reply with captions; the browser mic rests while Aasan talks, so its voice is never a turn", async () => {
    renderPage();
    const rec = await openVoice();
    act(() => rec.say("explain loops", false));
    act(() => h.vad.emit("speech-end"));
    expect(h.sock.send).toHaveBeenCalledTimes(1);
    reply("A loop repeats work. Like a bus on its route. ");
    await waitFor(() => expect(h.spk.spoken).toEqual(["A loop repeats work.", "Like a bus on its route."]));
    expect(screen.getByTestId("voice-status")).toHaveTextContent(/tap/i);
    expect(rec.running).toBe(false);
    expect(h.spk.cancel).not.toHaveBeenCalled();
  });

  it("while Aasan speaks the orb is the Interrupt button, and it stops the reply", async () => {
    renderPage();
    await openVoice();
    reply("First sentence here. Second one. ");
    await waitFor(() => expect(h.spk.busy).toBe(true));
    fireEvent.click(within(screenEl()).getByRole("button", { name: /^interrupt$/i }));
    expect(h.spk.cancel).toHaveBeenCalled();
    expect(h.sock.cancel).toHaveBeenCalled();
  });

  it("a tap on the orb stops the reply too", async () => {
    renderPage();
    await openVoice();
    reply("Talking now. Still talking. ");
    await waitFor(() => expect(h.spk.busy).toBe(true));
    fireEvent.click(screen.getByTestId("voice-orb"));
    expect(h.spk.cancel).toHaveBeenCalled();
    expect(h.sock.cancel).toHaveBeenCalled();
  });

  it("Mute closes the mic without ending; End closes the screen and the mic", async () => {
    renderPage();
    const rec = await openVoice();
    fireEvent.click(within(screenEl()).getByRole("button", { name: /^mute$/i }));
    await waitFor(() => expect(screen.getByTestId("voice-status")).toHaveTextContent(/mic is off/i));
    expect(rec.running).toBe(false);
    expect(screenEl()).toBeInTheDocument();
    fireEvent.click(within(screenEl()).getByRole("button", { name: /^unmute$/i }));
    await waitFor(() => expect(FakeRecognition.all.at(-1)?.running).toBe(true));
    fireEvent.click(screen.getByTestId("voice-end"));
    expect(screen.queryByRole("region", { name: /voice conversation/i })).toBeNull();
    expect(FakeRecognition.all.filter((r) => r.running)).toHaveLength(0);
  });

  it("never reads a code block aloud: it says the code is on screen", async () => {
    renderPage();
    await openVoice();
    const text = "Here is the code.\n\n```python\nprint('hi'). # one.\n\nx = 2\n```\n\nRun it. What happens?";
    reply(text);
    reply(text, false);
    await waitFor(() => expect(h.spk.spoken.join(" ")).toContain("What happens?"));
    const all = h.spk.spoken.join(" ");
    expect(all).not.toMatch(/print|x = 2|`/);
    expect(h.spk.spoken).toContain("I've put the code on screen.");
  });

  it("the conversation always speaks, even with Read answers aloud off for typed questions", async () => {
    h.prefs.voice = { mentor_mode: "tap", mentor_read_aloud: false, mentor_lang: "en" };
    renderPage();
    await openVoice();
    reply("Spoken answer. In voice mode. ");
    reply("Spoken answer. In voice mode. ", false);
    await waitFor(() => expect(h.spk.spoken.length).toBeGreaterThan(0));
  });

  it("mic blocked: says so clearly and Type instead goes back to typing, which still works", async () => {
    h.vad.deny = true;
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /voice conversation/i }));
    expect(await within(screenEl()).findByRole("alert")).toHaveTextContent(/microphone blocked/i);
    fireEvent.click(within(within(screenEl()).getByRole("alert")).getByRole("button", { name: /type instead/i }));
    expect(screen.queryByRole("region", { name: /voice conversation/i })).toBeNull();
    await waitFor(() => expect(screen.getByRole("textbox")).toHaveFocus());
    const box = screen.getByRole("textbox");
    fireEvent.change(box, { target: { value: "typed question" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(h.sock.send).toHaveBeenCalledWith("typed question");
  });

  it("the message bar is always there: empty shows the voice button, typing swaps it for Send", () => {
    renderPage();
    expect(screen.getByTestId("type-form").className).not.toMatch(/\bhidden\b/);
    expect(screen.getByTestId("open-voice")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "hello" } });
    expect(screen.queryByTestId("open-voice")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^send$/i }));
    expect(h.sock.send).toHaveBeenCalledWith("hello");
  });

  it("a voice conversation keeps the chat on screen: my spoken turn and the answer appear as messages", async () => {
    renderPage();
    const rec = await openVoice();
    act(() => rec.say("what is gravity", false));
    act(() => h.vad.emit("speech-end"));
    reply("Gravity pulls things together. ");
    await waitFor(() => expect(screen.getByText(/gravity pulls things together/i)).toBeInTheDocument());
    expect(screenEl()).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull(); // no full-screen overlay hiding the chat
  });

  it("hides voice with a hint when the browser has no microphone", () => {
    Object.defineProperty(navigator, "mediaDevices", { value: undefined, configurable: true });
    renderPage();
    expect(screen.queryByRole("button", { name: /voice conversation/i })).toBeNull();
    expect(screen.getByTestId("no-mic")).toHaveTextContent(/type your question/i);
    expect(screen.getByTestId("type-form").className).not.toMatch(/\bhidden\b/);
  });
});

describe("voice conversation on streamed listening (Deepgram)", () => {
  it("uses the live stream instead of the browser recogniser; talking over Aasan interrupts", async () => {
    h.fetchVoiceConfig.mockImplementation(async () => ({ stt: { engine: "server", provider: "deepgram", streaming: true }, tts: { engine: "server", provider: "deepgram" } }) as never);
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /voice conversation/i }));
    await waitFor(() => expect(h.live.opened).toBe(1));
    expect(FakeRecognition.all).toHaveLength(0);
    act(() => h.live.emit!({ type: "final", text: "what is a prompt", speech_final: true }));
    expect(h.sock.send).toHaveBeenCalledWith("what is a prompt", { via: "voice" });
    reply("A prompt is an instruction you give the AI. More ");
    await waitFor(() => expect(h.spk.busy).toBe(true));
    expect(screen.getByTestId("voice-status")).toHaveTextContent(/talk any time to interrupt/i);
    act(() => h.live.emit!({ type: "interim", text: "what about images" }));
    expect(h.spk.cancel).toHaveBeenCalled();
    expect(h.sock.cancel).toHaveBeenCalled();
  });
});
