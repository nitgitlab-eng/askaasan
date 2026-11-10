import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/en";
import { journey } from "@/lib/journey";
import { learner } from "@/lib/learner";
import { fetchClip, fetchVoiceConfig } from "@/voice/engines";

import { LessonMedia } from "./LessonMedia";

vi.mock("@/voice/engines", async (orig) => ({
  ...(await orig<typeof import("@/voice/engines")>()),
  fetchVoiceConfig: vi.fn(),
  fetchClip: vi.fn(),
}));

class FakeAudio {
  src = "";
  playbackRate = 1;
  currentTime = 0;
  duration = 0;
  ended = false;
  onended: (() => void) | null = null;
  play() { return Promise.resolve(); }
  pause() {}
  addEventListener() {}
  removeAttribute() {}
}

const ALL = { podcast: true, explainer: true, listen: true };
const OFF = { podcast: false, explainer: false, listen: false };
const props = { md: "## Rows\nA row is a record.\n\n## Columns\nA column is a field.", title: "Tables", keyPoints: [], lang: "en", lessonId: 7, listened: false, onListened: () => {} };

function show(features: typeof ALL | undefined) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><LessonMedia features={features} {...props} /></QueryClientProvider>);
}

beforeEach(() => {
  vi.stubGlobal("Audio", FakeAudio);
  vi.mocked(fetchVoiceConfig).mockResolvedValue({ stt: { engine: "browser", provider: "browser" }, tts: { engine: "server", provider: "deepgram" } });
  vi.mocked(fetchClip).mockImplementation(async (req) => ({ url: `/api/media/speech/${req.voice_role}-${req.text.length}.mp3`, cached: true }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.mocked(fetchClip).mockReset();
  vi.mocked(fetchVoiceConfig).mockReset();
});

describe("LessonMedia switches", () => {
  it("shows nothing (and asks for nothing) when the admin turned it all off", () => {
    const podcast = vi.spyOn(journey, "podcast");
    const explainer = vi.spyOn(learner, "explainer");
    const { container } = show(OFF);
    expect(container).toBeEmptyDOMElement();
    expect(show(undefined).container).toBeEmptyDOMElement();
    expect(podcast).not.toHaveBeenCalled();
    expect(explainer).not.toHaveBeenCalled();
  });

  it("shows only the features that are on", async () => {
    vi.spyOn(journey, "podcast").mockResolvedValue({ status: "none", warmup: [] });
    show({ ...OFF, podcast: true });
    expect(await screen.findByText(en.lj.podcast.title)).toBeInTheDocument();
    expect(screen.queryByText(en.listen.title)).toBeNull();
    expect(screen.queryByText(en.explainer.title)).toBeNull();
  });
});

describe("players are on demand", () => {
  it("Listen fetches no voice config or audio until Play, then plays whole-part clips", async () => {
    show({ ...OFF, listen: true });
    fireEvent.click(screen.getByRole("button", { name: new RegExp(en.listen.title) }));
    await new Promise((r) => setTimeout(r, 20));
    expect(fetchVoiceConfig).not.toHaveBeenCalled();
    expect(fetchClip).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: en.listen.play }));
    await waitFor(() => expect(fetchClip).toHaveBeenCalled());
    expect(fetchVoiceConfig).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fetchClip).mock.calls[0][0]).toEqual({ text: "Rows A row is a record.", lang: "en", voice_role: "narrator" });
  });

  it("the podcast's two hosts request different voice roles, only after Play", async () => {
    vi.spyOn(journey, "podcast").mockResolvedValue({
      status: "ready", warmup: [], title: "Tables talk", hosts: { A: "Meera", B: "Arjun" },
      turns: [{ speaker: "A", text: "What is a row?" }, { speaker: "B", text: "A row is one record." }],
    });
    show({ ...OFF, podcast: true });
    expect(await screen.findByText("Tables talk")).toBeInTheDocument();
    expect(fetchClip).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: en.listen.play }));
    await waitFor(() => expect(fetchClip).toHaveBeenCalledTimes(2));
    expect(vi.mocked(fetchClip).mock.calls.map(([r]) => r.voice_role)).toEqual(["host_a", "host_b"]);
  });
});
