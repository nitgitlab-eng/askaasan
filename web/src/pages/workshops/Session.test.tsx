import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { DialogHost } from "@/components/dialog";
import { PaceBanner } from "@/components/workshop/PaceBanner";
import { ApiError, api } from "@/lib/api";
import type { Session } from "@/lib/workshops";

import WorkshopResultPage from "./Result";
import WorkshopSessionPage from "./Session";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn(), ensureFreshAccess: vi.fn(async () => "tok") }));
const voiceMock = vi.hoisted(() => ({ start: vi.fn(async () => {}), stop: vi.fn(), listen: vi.fn(async () => {}), finish: vi.fn(), interrupt: vi.fn(), hush: vi.fn(), speakText: vi.fn(), opts: [] as { mode?: string }[] }));
vi.mock("@/voice/useVoiceMode", () => ({
  useVoiceMode: (o: { mode?: string }) => {
    voiceMock.opts.push(o);
    return { state: "off", error: null, interim: "", active: false, listening: false, start: voiceMock.start, stop: voiceMock.stop, listen: voiceMock.listen, finish: voiceMock.finish, interrupt: voiceMock.interrupt, hush: voiceMock.hush, speakText: voiceMock.speakText };
  },
}));

const listenOnce = vi.hoisted(() => vi.fn(async (): Promise<string> => "hello Kili"));
vi.mock("@/voice/oneShot", () => ({ listenOnce }));

class FakeSocket {
  static all: FakeSocket[] = [];
  static OPEN = 1;
  readyState = 0;
  sent: { type: string; [k: string]: unknown }[] = [];
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
    act(() => this.onmessage?.({ data: JSON.stringify(ev) }));
  }
}

const base = (over: Partial<Session> = {}): Session => ({
  id: 7, status: "active", workshop: { slug: "quick-check", title: "Quick Check Workshop", duration_minutes: 10, grace_minutes: 5, proctoring: "off", pass_mark: 0.6 },
  prerequisites: [
    { key: "account", label: "A free ChatGPT account", how_to_md: "Sign up at **chat.openai.com**.", done: false },
    { key: "tab", label: "A second browser tab open", how_to_md: "", done: false },
  ],
  ready: false, started_at: "2026-10-18T10:00:00Z", planned_end: null, grace_end: null, stage_index: 0,
  stages: [
    { key: "learn", kind: "teach", title: "What is a prompt?", minutes: 4, concepts: [{ text: "A prompt is an instruction", done: true }, { text: "Context makes answers better", done: false }], steps: [] },
    { key: "try", kind: "diy", title: "Try it yourself", minutes: 3, concepts: [], steps: [{ text: "Ask ChatGPT for a recipe", done: false }] },
    { key: "final", kind: "assessment", title: "Final", minutes: 3, concepts: [], steps: [] },
  ],
  scores: {}, final_score: null, passed: null, certificate: null, proctoring: "off", proctor_notice_seen: false, ...over,
});

let current: Session;
const apiMock = vi.mocked(api);
type Init = { method?: string; json?: unknown; body?: unknown };
let routes: Record<string, (init?: Init) => unknown>;

function mount(route = "/workshops/session/7") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <DialogHost />
        <Routes>
          <Route path="/workshops/session/:id" element={<WorkshopSessionPage />} />
          <Route path="/workshops/session/:id/result" element={<WorkshopResultPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function socket() {
  await waitFor(() => expect(FakeSocket.all.length).toBeGreaterThan(0));
  const s = FakeSocket.all[0];
  act(() => s.open());
  return s;
}

beforeEach(() => {
  localStorage.clear();
  FakeSocket.all = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  current = base();
  routes = {
    "/api/users/me/": () => null,
    "/api/voice/config/": () => ({ stt: { engine: "server", provider: "x" }, tts: { engine: "browser", provider: "browser" } }),
    "/api/users/preferences/": (init) => init?.json ?? {},
    "/api/workshops/sessions/7/prereq/": (init) => {
      const { key, done } = init!.json as { key: string; done: boolean };
      current = { ...current, prerequisites: current.prerequisites.map((p) => (p.key === key ? { ...p, done } : p)) };
      return current;
    },
    "/api/workshops/sessions/7/start/": () => (current = { ...current, status: "active" }),
    "/api/workshops/sessions/7/help/": () => ({ reply_md: "Your **API key** is missing.", summary: "missing key" }),
    "/api/workshops/sessions/7/final/": () => ({ score: 0.8, passed: true, feedback: "Well done.", certificate: { code: "ABC123", url: "https://x/verify/ABC123", id: 42 } }),
    "/api/workshops/sessions/7/": () => current,
  };
  apiMock.mockImplementation((async (path: string, init?: Init) => {
    const key = Object.keys(routes).sort((a, b) => b.length - a.length).find((k) => path.startsWith(k));
    if (!key) throw new Error(`unmocked ${path}`);
    return routes[key](init);
  }) as typeof api);
});
afterEach(() => {
  vi.unstubAllGlobals();
  apiMock.mockReset();
});

describe("prerequisites gate the start", () => {
  it("keeps Start disabled until every prerequisite is ticked, then starts", async () => {
    current = base({ status: "prereq", started_at: null });
    mount();
    routes["/api/workshops/sessions/7/start/"] = () => {
      throw new ApiError(400, { code: "proctor_notice_required" });
    };
    const start = await screen.findByRole("button", { name: /i'm ready, start/i });
    expect(start).toBeDisabled();
    expect(screen.getByTestId("proctor-notice")).toHaveTextContent(/no camera/i);
    fireEvent.click(screen.getByRole("checkbox", { name: /chatgpt account/i }));
    await waitFor(() => expect(screen.getByRole("checkbox", { name: /chatgpt account/i })).toBeChecked());
    expect(start).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /second browser tab/i }));
    await waitFor(() => expect(screen.getByRole("button", { name: /i'm ready, start/i })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /i'm ready, start/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/what we track/i);
    routes["/api/workshops/sessions/7/start/"] = () => (current = { ...current, status: "active" });
    fireEvent.click(screen.getByRole("button", { name: /i'm ready, start/i }));
    await screen.findByRole("heading", { name: "What is a prompt?" });
    expect(apiMock).toHaveBeenCalledWith("/api/workshops/sessions/7/start/", { method: "POST", json: { proctor_notice: true } });
  });
});

describe("mic check before the start", () => {
  it("“Say hello” listens once and shows what was heard; a miss offers typing instead", async () => {
    current = base({ status: "prereq", started_at: null });
    listenOnce.mockResolvedValueOnce("");
    mount();
    const check = await screen.findByTestId("mic-check");
    fireEvent.click(within(check).getByRole("button", { name: /say hello to/i }));
    expect(await within(check).findByRole("status")).toHaveTextContent(/didn't catch that/i);
    fireEvent.click(within(check).getByRole("button", { name: /say hello to/i }));
    expect(await within(check).findByText(/heard you: “hello Kili”/i)).toBeInTheDocument();
    expect(within(check).queryByRole("button")).toBeNull(); // one-time: done
    expect(listenOnce).toHaveBeenCalledWith("en", 6000);
  });

  it("never blocks the start", async () => {
    current = base({ status: "prereq", started_at: null, prerequisites: [] });
    mount();
    expect(await screen.findByRole("button", { name: /i'm ready, start/i })).toBeEnabled();
  });
});

describe("starting from the prerequisites screen", () => {
  it("re-authenticates the already-open socket right after Start so the host begins teaching", async () => {
    current = base({ status: "prereq", started_at: null });
    mount();
    await waitFor(() => expect(FakeSocket.all.length).toBeGreaterThan(0));
    const sock = FakeSocket.all.at(-1)!;
    act(() => sock.open());
    expect(sock.sent.filter((m) => m.type === "auth")).toHaveLength(1);
    fireEvent.click(await screen.findByRole("checkbox", { name: /chatgpt account/i }));
    await waitFor(() => expect(screen.getByRole("checkbox", { name: /chatgpt account/i })).toBeChecked());
    fireEvent.click(screen.getByRole("checkbox", { name: /second browser tab/i }));
    await waitFor(() => expect(screen.getByRole("button", { name: /i'm ready, start/i })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /i'm ready, start/i }));
    await screen.findByRole("heading", { name: "What is a prompt?" });
    await waitFor(() => expect(sock.sent.filter((m) => m.type === "auth")).toHaveLength(2));
  });
});

describe("pace banner", () => {
  it.each([
    ["on_track", /on track/i],
    ["behind", /a little behind/i],
    ["in_grace", /your timeline is over — you're in a grace period/i],
    ["overtime", /over time/i],
  ] as const)("%s", (status, text) => {
    render(<PaceBanner status={status} />);
    expect(screen.getByRole("status")).toHaveTextContent(text);
  });

  it("follows the server clock in the session without blocking anything", async () => {
    mount();
    const s = await socket();
    const explained = { ...current, stages: current.stages.map((st, i) => (i === 0 ? { ...st, cursor: 1, concepts: st.concepts.map((c) => ({ ...c, explained: true })) } : st)) };
    s.msg({ type: "ready", session: explained });
    s.msg({ type: "pace", status: "in_grace", minutes_left: 3 });
    expect(await screen.findByText(/you're in a grace period/i)).toBeInTheDocument();
    s.msg({ type: "suggest", chips: ["yes_next", "not_yet"] });
    fireEvent.click(screen.getByRole("button", { name: "Yes, next" }));
    expect(s.sent).toContainEqual({ type: "control", action: "yes_next" });
  });
});

describe("suggested replies (chips)", () => {
  it("shows the chips from ready.suggest, then follows each suggest event, at most 3 and only known ids", async () => {
    mount();
    const s = await socket();
    s.msg({ type: "ready", session: current, suggest: ["not_sure", "example", "tamil"] });
    const group = await screen.findByRole("group", { name: /quick replies/i });
    expect(within(group).getAllByRole("button").map((b) => b.textContent)).toEqual(["Not sure", "Another example", "Say it in Tamil"]);
    s.msg({ type: "suggest", chips: ["yes_next", "not_yet", "hack_me", "continue", "stuck"] });
    expect(within(screen.getByRole("group", { name: /quick replies/i })).getAllByRole("button").map((b) => b.textContent)).toEqual(["Yes, next", "Not yet", "Continue"]);
    s.msg({ type: "suggest", chips: [] });
    expect(screen.queryByRole("group", { name: /quick replies/i })).toBeNull();
  });

  it.each([
    ["Yes, next", "yes_next"], ["Not yet", "not_yet"], ["Not sure", "not_sure"], ["Another example", "example"],
    ["Say it in Tamil", "tamil"], ["Say it in English", "english"], ["I'm stuck", "stuck"], ["Continue", "continue"],
  ])("“%s” sends control %s (and stops the spoken reply locally)", async (label, action) => {
    mount();
    const s = await socket();
    s.msg({ type: "ready", session: current, suggest: [action] });
    voiceMock.hush.mockClear();
    fireEvent.click(await screen.findByRole("button", { name: label }));
    expect(s.sent).toContainEqual({ type: "control", action });
    expect(voiceMock.hush).toHaveBeenCalled();
  });

  it("“Done” marks the current step done", async () => {
    current = base({ stage_index: 1, stages: base().stages.map((st, i) => (i === 1 ? { ...st, cursor: 0 } : st)) });
    mount();
    const s = await socket();
    s.msg({ type: "ready", session: current, suggest: ["done", "stuck"] });
    fireEvent.click(await screen.findByRole("button", { name: "Done" }));
    expect(s.sent).toContainEqual({ type: "step_done", step: 0 });
  });

  it("can be tapped while the host is talking; then the old chips go away until the reply brings new ones", async () => {
    mount();
    const s = await socket();
    s.msg({ type: "ready", session: current, suggest: ["not_sure", "example"] });
    s.msg({ type: "start" });
    s.msg({ type: "delta", text: "A prompt is…" });
    const chip = await screen.findByRole("button", { name: "Not sure" });
    expect(chip).toBeEnabled();
    fireEvent.click(chip);
    expect(s.sent).toContainEqual({ type: "control", action: "not_sure" });
    // A stale chip (e.g. "Yes, next" from the last moment) must never stay tappable while the host answers.
    await waitFor(() => expect(screen.queryByRole("button", { name: "Another example" })).toBeNull());
    s.msg({ type: "done", stop_reason: "cancelled" });
    s.msg({ type: "start" });
    s.msg({ type: "done", stop_reason: "end_turn" });
    s.msg({ type: "suggest", chips: ["yes_next", "not_yet"] });
    await waitFor(() => expect(screen.getByRole("button", { name: "Yes, next" })).toBeEnabled());
  });

  it("offers 'Tap to hear' when the voice is off (e.g. after a reload) and reads the host's last line aloud", async () => {
    voiceMock.start.mockClear();
    voiceMock.speakText.mockClear();
    mount();
    const s = await socket();
    s.msg({ type: "ready", session: current });
    s.msg({ type: "start" });
    s.msg({ type: "delta", text: "A model learns from many examples." });
    s.msg({ type: "done", stop_reason: "end_turn" });
    fireEvent.click(await screen.findByRole("button", { name: /tap to hear/i }));
    await waitFor(() => expect(voiceMock.speakText).toHaveBeenCalledWith("A model learns from many examples."));
    expect(voiceMock.start).toHaveBeenCalled();
  });

  it("maps socket error codes to messages, with a generic fallback", async () => {
    mount();
    const s = await socket();
    s.msg({ type: "ready", session: current });
    s.msg({ type: "error", code: "not_ready" });
    expect(await screen.findByRole("alert")).toHaveTextContent(/ask when you're ready to move on/i);
    s.msg({ type: "error", code: "bad_step" });
    expect(await screen.findByRole("alert")).toHaveTextContent(/isn't the step you're on/i);
    s.msg({ type: "error", code: "something_new" });
    expect(await screen.findByRole("alert")).toHaveTextContent(/something went wrong/i);
  });
});

describe("the host's live caption", () => {
  const caption = () => screen.getByTestId("host-caption");

  it("streams the host's line, and a message sent mid-reply never freezes it", async () => {
    mount();
    const s = await socket();
    s.msg({ type: "ready", session: current });
    s.msg({ type: "start" });
    s.msg({ type: "delta", text: "Think of a prompt " });
    await waitFor(() => expect(caption()).toHaveTextContent("Think of a prompt"));
    fireEvent.click(screen.getByRole("button", { name: /^type$/i }));
    fireEvent.change(screen.getByRole("textbox", { name: /type your answer/i }), { target: { value: "wait, what?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(s.sent).toContainEqual({ type: "say", text: "wait, what?" });
    expect(screen.getByTestId("me-caption")).toHaveTextContent("wait, what?");
    // Deltas still in flight for the reply land in it (not dropped), until the server says it was stopped.
    s.msg({ type: "delta", text: "like ordering" });
    await waitFor(() => expect(caption()).toHaveTextContent("Think of a prompt like ordering"));
    s.msg({ type: "done", stop_reason: "cancelled" });
    await waitFor(() => expect(caption()).toHaveTextContent("(stopped)"));
    expect(caption().className).toMatch(/text-muted/);
    s.msg({ type: "start" });
    s.msg({ type: "delta", text: "Good question!" });
    s.msg({ type: "done", stop_reason: "end_turn" });
    await waitFor(() => expect(caption()).toHaveTextContent("Good question!"));
    expect(caption()).not.toHaveTextContent("(stopped)");
  });

  it("drops a stopped reply that had no words yet", async () => {
    mount();
    const s = await socket();
    s.msg({ type: "ready", session: current, turns: [{ role: "assistant", text: "Hello there." }] });
    s.msg({ type: "start" });
    s.msg({ type: "done", stop_reason: "cancelled" });
    await waitFor(() => expect(caption()).toHaveTextContent("Hello there."));
    expect(caption()).not.toHaveTextContent("(stopped)");
  });

  it("shows “…” on a reply cut at the length limit, with the Continue chip the server sends", async () => {
    mount();
    const s = await socket();
    s.msg({ type: "ready", session: current });
    s.msg({ type: "start" });
    s.msg({ type: "delta", text: "Let's go sl" });
    s.msg({ type: "done", stop_reason: "max_tokens" });
    s.msg({ type: "suggest", chips: ["continue", "not_sure"] });
    await waitFor(() => expect(caption()).toHaveTextContent("Let's go sl …"));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(s.sent).toContainEqual({ type: "control", action: "continue" });
  });

  it("restores interrupted turns from ready as stopped in the transcript", async () => {
    mount();
    const s = await socket();
    s.msg({ type: "ready", session: current, turns: [{ role: "assistant", text: "Part one", cancelled: true }, { role: "user", text: "yes" }] });
    fireEvent.click(await screen.findByRole("button", { name: /workshop menu/i }));
    const t = within(await screen.findByRole("dialog", { name: /workshop menu/i })).getByTestId("transcript");
    expect(t).toHaveTextContent("Part one(stopped)");
    expect(t).toHaveTextContent("yes");
  });
});

describe("the ⋮ menu", () => {
  it("has the plan, transcript, raise hand, language and the hands-free switch (saved to preferences)", async () => {
    mount();
    const s = await socket();
    s.msg({ type: "ready", session: current });
    fireEvent.click(await screen.findByRole("button", { name: /workshop menu/i }));
    const menu = await screen.findByRole("dialog", { name: /workshop menu/i });
    expect(within(menu).getByRole("navigation", { name: /workshop plan/i })).toBeInTheDocument();
    expect(within(menu).getAllByRole("listitem").map((li) => li.dataset.state)).toEqual(["current", "upcoming", "upcoming"]);
    expect(within(menu).getByText("Transcript")).toBeInTheDocument();
    fireEvent.click(within(menu).getByRole("button", { name: /raise hand/i }));
    expect(s.sent).toContainEqual({ type: "raise_hand" });
    expect(within(menu).getByRole("status")).toHaveTextContent(/hand raised/i);
    fireEvent.click(within(menu).getByRole("radio", { name: "தமிழ்" }));
    expect(s.sent).toContainEqual({ type: "control", action: "tamil" });
    const hf = within(menu).getByRole("switch", { name: /hands-free/i });
    expect(hf).toHaveAttribute("aria-checked", "false");
    expect(hf).toHaveAccessibleDescription(/use headphones/i);
    fireEvent.click(hf);
    await waitFor(() => expect(apiMock).toHaveBeenCalledWith("/api/users/preferences/", { method: "PATCH", json: { voice: { workshop_mode: "handsfree" } } }));
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: /workshop menu/i })).toBeNull());
  });

  it("uses tap-to-talk unless the learner chose hands-free", async () => {
    voiceMock.opts.length = 0;
    mount();
    await screen.findByRole("heading", { name: "What is a prompt?" });
    expect(voiceMock.opts.at(-1)?.mode).toBe("tap");
  });
});

describe("talking", () => {
  it("one big Tap to talk starts the voice and listens; Stop interrupts while the host talks; the mascot tap does both", async () => {
    mount();
    const s = await socket();
    s.msg({ type: "ready", session: current });
    voiceMock.listen.mockClear();
    fireEvent.click(await screen.findByRole("button", { name: /tap to talk/i }));
    await waitFor(() => expect(voiceMock.listen).toHaveBeenCalled());
    expect(voiceMock.start).toHaveBeenCalled();
    s.msg({ type: "start" });
    s.msg({ type: "delta", text: "So…" });
    fireEvent.click(await screen.findByRole("button", { name: /^stop$/i }));
    expect(s.sent).toContainEqual({ type: "cancel" }); // voice is off in this test, so Stop cancels on the socket
    voiceMock.listen.mockClear();
    fireEvent.click(screen.getByTestId("mascot"));
    await waitFor(() => expect(voiceMock.listen).toHaveBeenCalled());
  });
});

describe("teach stage", () => {
  it("is one simple column: no fixed control chips, no Next button and no concept list", async () => {
    mount();
    const s = await socket();
    s.msg({ type: "ready", session: current });
    await screen.findByRole("heading", { name: "What is a prompt?" });
    expect(screen.queryByRole("button", { name: "Slower" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^next/i })).toBeNull();
    expect(screen.queryByText("Context makes answers better")).toBeNull();
    expect(screen.queryByTestId("activity")).toBeNull();
    expect(document.querySelector('[class*="grid-cols"]')).toBeNull(); // no side columns at any width
    // Every control is at least 44 px tall.
    for (const b of [screen.getByRole("button", { name: /tap to talk/i }), screen.getByRole("button", { name: /^type$/i }), screen.getByRole("button", { name: /workshop menu/i })]) {
      expect(b.className).toMatch(/min-h-(11|16)/);
    }
  });

  it("adds no second <main> landmark (the app shell already has one)", async () => {
    mount();
    const s = await socket();
    s.msg({ type: "ready", session: current });
    await screen.findByRole("heading", { name: "What is a prompt?" });
    expect(document.querySelectorAll("main")).toHaveLength(0); // rendered without the shell here
  });
});

describe("DIY Help panel", () => {
  beforeEach(() => {
    current = base({ stage_index: 1 });
  });
  const openHelp = async () => fireEvent.click(await screen.findByRole("button", { name: /show my screen or paste the error/i }));

  it("takes a pasted screenshot and sends it with the error", async () => {
    mount();
    await openHelp();
    const png = new File(["x"], "shot.png", { type: "image/png" });
    const errorBox = screen.getByLabelText(/error or log/i);
    fireEvent.paste(errorBox, { clipboardData: { files: [png] } });
    expect(await screen.findByText("shot.png")).toBeInTheDocument();
    fireEvent.change(errorBox, { target: { value: "KeyError: 'OPENAI_API_KEY'" } });
    fireEvent.click(screen.getByRole("button", { name: /get help/i }));
    expect(await screen.findByText("API key")).toBeInTheDocument();
    const [, init] = apiMock.mock.calls.find(([p]) => p === "/api/workshops/sessions/7/help/")!;
    const body = (init as Init).body as FormData;
    expect(body.get("image")).toBe(png);
    expect(body.get("error_text")).toBe("KeyError: 'OPENAI_API_KEY'");
  });

  it("submits an error alone, and rejects a non-image file", async () => {
    mount();
    await openHelp();
    fireEvent.paste(screen.getByLabelText(/error or log/i), { clipboardData: { files: [new File(["x"], "a.gif", { type: "image/gif" })] } });
    expect(await screen.findByRole("alert")).toHaveTextContent(/png, jpeg or webp/i);
    fireEvent.change(screen.getByLabelText(/error or log/i), { target: { value: "ModuleNotFoundError: requests" } });
    fireEvent.click(screen.getByRole("button", { name: /get help/i }));
    expect(await screen.findByText("API key")).toBeInTheDocument();
    const body = (apiMock.mock.calls.find(([p]) => p === "/api/workshops/sessions/7/help/")![1] as Init).body as FormData;
    expect(body.get("image")).toBeNull();
  });

  it.each([
    [429, { code: "rate_limited", retry_after: 600 }, /try again in about 10 min/i],
    [429, { code: "budget" }, /used up for today/i],
    [429, { code: "cap" }, /paused until tomorrow/i],
    [400, { code: "too_long" }, /too long/i],
    [400, { code: "bad_image" }, /couldn't read that image/i],
    [400, { code: "image_too_large" }, /over 4 MB/i],
    [400, { code: "nothing_to_check" }, /add a screenshot or paste an error/i],
    [503, { code: "help_unavailable" }, /isn't available right now/i],
  ])("shows its own message for a %i %o", async (status, data, text) => {
    routes["/api/workshops/sessions/7/help/"] = () => {
      throw new ApiError(status, data);
    };
    mount();
    await openHelp();
    fireEvent.change(screen.getByLabelText(/error or log/i), { target: { value: "Traceback" } });
    fireEvent.click(screen.getByRole("button", { name: /get help/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });

  it("marks a step done over the socket", async () => {
    mount();
    const s = await socket();
    fireEvent.click(await screen.findByRole("button", { name: /i've done this/i }));
    expect(s.sent).toContainEqual({ type: "step_done", step: 0 });
  });
});

describe("proctoring in the session", () => {
  const away = () => {
    document.dispatchEvent(new Event("visibilitychange"));
    window.dispatchEvent(new Event("blur"));
  };

  it("sends nothing when the workshop has proctoring off", async () => {
    mount();
    const s = await socket();
    await screen.findByRole("heading", { name: "What is a prompt?" });
    away();
    expect(s.sent.filter((m) => m.type === "attention")).toEqual([]);
  });

  it("sends attention events when on, outside hands-on stages", async () => {
    current = base({ proctoring: "activity" });
    mount();
    const s = await socket();
    await screen.findByRole("heading", { name: "What is a prompt?" });
    away();
    expect(s.sent.filter((m) => m.type === "attention").map((m) => m.kind)).toEqual(expect.arrayContaining(["blur"]));
  });

  it("sends nothing during a DIY stage even when on", async () => {
    current = base({ proctoring: "strict", stage_index: 1 });
    mount();
    const s = await socket();
    await screen.findByRole("heading", { name: "Try it yourself" });
    away();
    expect(s.sent.filter((m) => m.type === "attention")).toEqual([]);
  });
});

describe("final assessment", () => {
  it("submits answers and the practical, then shows the result with the certificate", async () => {
    current = base({ stage_index: 2, final: { mcqs: [{ q: "What makes a prompt better?", options: ["Shouting", "Context"] }], practical: { prompt: "Write a prompt for a study plan." } }, attempts_left: 2 });
    mount();
    expect(await screen.findByText("What makes a prompt better?")).toBeInTheDocument();
    expect(screen.getByTestId("attempts-left")).toHaveTextContent("2 attempts left");
    expect(screen.getByText(/Pass mark: 60%\./)).toBeInTheDocument(); // pass_mark 0.6 is a fraction, not "0.6%"
    fireEvent.click(screen.getByRole("button", { name: /submit answers/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/answer every question/i);
    fireEvent.click(screen.getByLabelText("Context"));
    fireEvent.change(screen.getByPlaceholderText(/write your answer/i), { target: { value: "Plan my week of revision." } });
    fireEvent.click(screen.getByRole("button", { name: /submit answers/i }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /submit answers/i }));
    expect(await screen.findByText("You passed!")).toBeInTheDocument();
    expect(apiMock).toHaveBeenCalledWith("/api/workshops/sessions/7/final/", { method: "POST", json: { answers: { 0: 1 }, practical: "Plan my week of revision." } });
    expect(screen.getByText(/score: 80%/i)).toBeInTheDocument(); // the API sends fractions: 0.8 → 80%
    expect(screen.getByText(/pass mark 60%/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /download certificate/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /verify page/i })).toHaveAttribute("href", "/verify/ABC123");
  });
});

describe("agent builder in the session", () => {
  const agentStages = (): Session["stages"] => [
    { key: "learn", kind: "teach", title: "What is an agent?", minutes: 10, concepts: [{ text: "Agents use tools", done: true, explained: true }], steps: [] },
    { key: "build", kind: "agent_build", title: "Build your agent", minutes: 30, concepts: [], steps: [{ text: "Give it a job", done: false }] },
    { key: "test", kind: "diy", title: "Test it", minutes: 10, concepts: [], steps: [{ text: "Ask it a sum", done: false }] },
    { key: "final", kind: "assessment", title: "Final", minutes: 10, concepts: [], steps: [] },
  ];
  const agent = {
    name: "GST Helper", role: "", starter: "", servers: [], auto_approve: {}, runs_left: 40, mcp: null,
    aasan_tools: [{ name: "calculator", description: "", enabled: true }],
  };
  beforeEach(() => {
    routes["/api/workshops/sessions/7/agent/"] = () => agent;
  });

  it("shows the builder in the agent_build stage, with no drawer there", async () => {
    current = base({ stages: agentStages(), stage_index: 1 });
    mount();
    expect(await screen.findByDisplayValue("GST Helper")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^your agent$/i })).toBeNull();
  });

  it("offers a “Your agent” drawer in later stages", async () => {
    current = base({ stages: agentStages(), stage_index: 2 });
    mount();
    await screen.findByRole("heading", { name: "Test it" });
    expect(screen.queryByDisplayValue("GST Helper")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^your agent$/i }));
    const drawer = await screen.findByRole("dialog", { name: /your agent/i });
    expect(await within(drawer).findByDisplayValue("GST Helper")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: /your agent/i })).toBeNull());
  });

  it("no drawer for workshops without an agent stage", async () => {
    current = base({ stage_index: 1 });
    mount();
    await screen.findByRole("heading", { name: "Try it yourself" });
    expect(screen.queryByRole("button", { name: /^your agent$/i })).toBeNull();
  });

  it("explains the hidden agent tests on the final, then shows how the agent did", async () => {
    current = base({ stages: agentStages(), stage_index: 3, final: { mcqs: [{ q: "What is a tool?", options: ["A helper the agent can call", "A font"] }], practical: { prompt: "" }, agent_tests: 3 } });
    routes["/api/workshops/sessions/7/final/"] = () => ({
      score: 0.75, passed: true, feedback: "", certificate: null, agent_score: 0.67,
      agent_tests: [
        { label: "GST on a bill", score: 1, passed: true, tools_used: ["calculator"] },
        { index: 1, score: 0.4, passed: false, tools_used: [] }, // no label: shown as "Test 2"
      ],
    });
    mount();
    expect(await screen.findByTestId("agent-tests-note")).toHaveTextContent("tested on 3 hidden questions");
    fireEvent.click(screen.getByLabelText("A helper the agent can call"));
    fireEvent.click(screen.getByRole("button", { name: /submit answers/i }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: /submit answers/i }));
    const card = await screen.findByTestId("agent-tests");
    expect(card).toHaveTextContent("Agent score: 67%");
    expect(card).toHaveTextContent("GST on a bill");
    expect(card).toHaveTextContent("Passed · 100%");
    expect(card).toHaveTextContent("Tools used: calculator");
    expect(card).toHaveTextContent("Test 2");
    expect(card).toHaveTextContent("Missed · 40%");
    expect(card).toHaveTextContent("No tools used");
  });

  it("keeps the agent test summary on the result page after a refresh", async () => {
    current = base({
      status: "submitted", final_score: 0.8, passed: true, agent_score: 1,
      agent_tests: [{ index: 0, label: "Unit conversion", score: 1, passed: true, tools_used: ["units"] }],
    });
    mount("/workshops/session/7/result");
    const card = await screen.findByTestId("agent-tests");
    expect(card).toHaveTextContent("Agent score: 100%");
    expect(card).toHaveTextContent("Unit conversion");
    expect(card).toHaveTextContent("Tools used: units");
  });
});

describe("institution runs (M4)", () => {
  it("shows a teacher's nudge as a plain-text banner that can be dismissed", async () => {
    mount();
    const s = await socket();
    s.msg({ type: "ready", session: current });
    await screen.findByRole("heading", { name: "What is a prompt?" });
    s.msg({ type: "staff_nudge", text: "<b>Great work</b> — try step 2 yourself", from: "Ms. Priya" });
    const banner = await screen.findByTestId("staff-nudge");
    expect(banner).toHaveTextContent("Message from Ms. Priya");
    expect(banner).toHaveTextContent("<b>Great work</b> — try step 2 yourself");
    expect(banner.querySelector("b")).toBeNull();
    s.msg({ type: "staff_nudge", text: "Keep going" });
    expect(await screen.findByText("Message from your teacher")).toBeInTheDocument();
    // Newest first: the later nudge is on top.
    expect(screen.getAllByTestId("staff-nudge")[0]).toHaveTextContent("Keep going");
    const priya = screen.getAllByTestId("staff-nudge").find((el) => el.textContent?.includes("Ms. Priya"))!;
    fireEvent.click(within(priya).getByRole("button", { name: "Dismiss message" }));
    expect(screen.getAllByTestId("staff-nudge")).toHaveLength(1);
    expect(screen.queryByText("Message from Ms. Priya")).toBeNull();
  });

  it("shows every nudge sent while the learner was offline (from ready), newest first, plain text, each dismissable", async () => {
    mount();
    const s = await socket();
    const nudges = [
      { text: "First, open the tab", from: "Ms. Priya", at: "2026-10-18T09:10:00Z" },
      { text: "<img src=x onerror=alert(1)> Third and newest", from: null, at: "2026-10-18T09:40:00Z" },
      { text: "Second one", from: "Mr. Ravi", at: "2026-10-18T09:25:00Z" },
      { text: "   ", from: "Blank", at: "2026-10-18T09:30:00Z" },
    ];
    s.msg({ type: "ready", session: current, nudges });
    await screen.findByRole("heading", { name: "What is a prompt?" });
    const banners = screen.getAllByTestId("staff-nudge");
    expect(banners.map((b) => b.querySelector("p.text-base")?.textContent)).toEqual(["<img src=x onerror=alert(1)> Third and newest", "Second one", "First, open the tab"]);
    expect(banners[0].querySelector("img")).toBeNull();
    expect(banners[0]).toHaveTextContent("Message from your teacher");
    expect(banners[1]).toHaveTextContent("Message from Mr. Ravi");
    expect(banners[0].querySelector("time")).toHaveAttribute("dateTime", "2026-10-18T09:40:00Z");
    expect(banners[0]).toHaveTextContent(/Sent at/);
    // A reconnect that repeats the same nudges doesn't stack copies.
    s.msg({ type: "ready", session: current, nudges });
    expect(screen.getAllByTestId("staff-nudge")).toHaveLength(3);
    fireEvent.click(within(banners[1]).getByRole("button", { name: "Dismiss message" }));
    expect(screen.getAllByTestId("staff-nudge")).toHaveLength(2);
    expect(screen.queryByText("Second one")).toBeNull();
  });

  it("tells the learner before the start that their institution can see their progress", async () => {
    current = base({ status: "prereq", started_at: null, institution_notice: "Your institution can see…", institution_sees: ["progress", "answers", "scores", "help_summaries"] });
    mount();
    expect(await screen.findByTestId("org-notice")).toHaveTextContent("Your institution can see your progress, answers, scores and help summaries during this workshop.");
  });

  it("adds attention activity to the institution notice when proctoring is on", async () => {
    current = base({ status: "prereq", started_at: null, proctoring: "activity", institution_notice: "…", institution_sees: ["progress", "answers", "scores", "help_summaries", "attention"] });
    mount();
    expect(await screen.findByTestId("org-notice")).toHaveTextContent(/help summaries and attention activity/);
  });

  it("still shows the institution notice when the server only sends institution_notice", async () => {
    current = base({ status: "prereq", started_at: null, institution_notice: "Your institution can see your progress, answers, scores and help summaries during this workshop." });
    mount();
    expect(await screen.findByTestId("org-notice")).toHaveTextContent("Your institution can see your progress, answers, scores and help summaries during this workshop.");
  });

  it("no institution notice on public runs", async () => {
    current = base({ status: "prereq", started_at: null, institution_notice: null, institution_sees: [] });
    mount();
    await screen.findByTestId("proctor-notice");
    expect(screen.queryByTestId("org-notice")).toBeNull();
  });
});

describe("build stages (M5)", () => {
  const buildStages = (task: Session["stages"][number]["task"]): Session["stages"] => [
    { key: "learn", kind: "teach", title: "What is a prompt?", minutes: 4, concepts: [{ text: "A prompt is an instruction", done: true }], steps: [] },
    { key: "make", kind: "build", title: "Write your own prompt", minutes: 5, concepts: [], steps: [{ text: "Use at least four building blocks", done: false }], task },
    { key: "final", kind: "assessment", title: "Final", minutes: 3, concepts: [], steps: [] },
  ];

  it("renders the open_input task, hands it in to the build endpoint and shows the grade as plain text", async () => {
    current = base({ stage_index: 1, stages: buildStages({ type: "open_input", title: "Your best prompt", payload: { prompt: "Write a prompt for a weekly meal plan." } }) });
    let sent: unknown;
    routes["/api/workshops/sessions/7/build/"] = (init) => {
      sent = init?.json;
      return { score: 0.5, passed: false, feedback: "<b>Add</b> a format line." };
    };
    mount();
    const card = await screen.findByTestId("build-task");
    expect(card).toHaveTextContent("Your build task");
    expect(card).toHaveTextContent("Write a prompt for a weekly meal plan.");
    const check = within(card).getByRole("button", { name: /^check$/i });
    expect(check).toBeDisabled();
    fireEvent.change(within(card).getByRole("textbox"), { target: { value: "You are a dietician. Plan 7 dinners as a table." } });
    fireEvent.click(check);
    const status = await within(card).findByRole("status");
    expect(sent).toEqual({ answer: { text: "You are a dietician. Plan 7 dinners as a table." } });
    expect(status).toHaveTextContent("Not quite · 50%");
    expect(status).toHaveTextContent("<b>Add</b> a format line.");
    expect(status.querySelector("b")).toBeNull();
    expect(status).toHaveTextContent(/Not yet/);
    // Try again keeps the learner's work so they can improve it.
    fireEvent.click(within(card).getByRole("button", { name: /try again/i }));
    expect(within(card).getByRole("textbox")).toHaveValue("You are a dietician. Plan 7 dinners as a table.");
  });

  it("shows a passed build with the next-step note and a server error code as a message", async () => {
    current = base({ stage_index: 1, stages: buildStages({ type: "open_input", payload: { prompt: "Write it." } }) });
    let calls = 0;
    routes["/api/workshops/sessions/7/build/"] = () => {
      calls += 1;
      if (calls === 1) throw new ApiError(429, { code: "cap" });
      return { score: 1, passed: true, feedback: "Great." };
    };
    mount();
    const card = await screen.findByTestId("build-task");
    fireEvent.change(within(card).getByRole("textbox"), { target: { value: "A full prompt." } });
    fireEvent.click(within(card).getByRole("button", { name: /^check$/i }));
    expect(await within(card).findByRole("alert")).toHaveTextContent(/Checking is paused/i);
    fireEvent.click(within(card).getByRole("button", { name: /^check$/i }));
    expect(await within(card).findByRole("status")).toHaveTextContent(/Passed\. Tap “Yes, next”/);
    expect(within(card).queryByRole("button", { name: /try again/i })).toBeNull();
  });

  it("uses the lesson bodies for code and artifact_check tasks, and shows a saved attempt", async () => {
    current = base({ stage_index: 1, stages: buildStages({ type: "artifact_check", payload: { prompt: "Publish your page.", steps: ["Make a Google Site"], checklist: [] }, attempt: { score: 1, passed: true, feedback: "It's live.", answer: { url: "https://sites.google.com/view/me" } } }) });
    mount();
    const card = await screen.findByTestId("build-task");
    expect(within(card).getByRole("textbox")).toHaveValue("https://sites.google.com/view/me");
    expect(within(card).getByRole("status")).toHaveTextContent("It's live.");
  });

  it("renders the Python editor for a code task", async () => {
    current = base({ stage_index: 1, stages: buildStages({ type: "code", payload: { prompt: "Print hello.", starter_code: "print('hi')", expected_output: "hello" } }) });
    mount();
    const card = await screen.findByTestId("build-task");
    expect(within(card).getByDisplayValue("print('hi')")).toBeInTheDocument();
  });

  it("counts tries down from the server, and stops at none left", async () => {
    current = base({ stage_index: 1, stages: buildStages({ type: "open_input", title: "Write your own prompt", payload: { prompt: "Write it." }, attempts_left: 2 }) });
    routes["/api/workshops/sessions/7/build/"] = () => ({ score: 0.3, passed: false, feedback: "Too short.", attempts_left: 1, best_score: 0.3 });
    mount();
    const card = await screen.findByTestId("build-task");
    expect(within(card).queryByRole("heading", { level: 3 })).toBeNull(); // the stage title isn't repeated
    expect(within(card).getByTestId("build-attempts")).toHaveTextContent("2 tries left");
    fireEvent.change(within(card).getByRole("textbox"), { target: { value: "A prompt." } });
    fireEvent.click(within(card).getByRole("button", { name: /^check$/i }));
    await within(card).findByRole("status");
    expect(within(card).getByTestId("build-attempts")).toHaveTextContent("1 try left");
    routes["/api/workshops/sessions/7/build/"] = () => {
      throw new ApiError(409, { code: "no_attempts_left" });
    };
    fireEvent.click(within(card).getByRole("button", { name: /try again/i }));
    fireEvent.click(within(card).getByRole("button", { name: /^check$/i }));
    expect(await within(card).findByRole("alert")).toHaveTextContent(/used all your tries/);
    expect(within(card).getByRole("button", { name: /^check$/i })).toBeDisabled();
  });

  it("shows the best score, and the model solution (as plain code) once no tries are left", async () => {
    current = base({ stage_index: 1, stages: buildStages({ type: "code", payload: { prompt: "Print hello.", starter_code: "print('hi')", expected_output: "hello" }, attempts_left: 1, best_score: 0.4 }) });
    routes["/api/workshops/sessions/7/build/"] = () => ({ score: 0.2, passed: false, feedback: "Not the expected output.", attempts_left: 0, best_score: 0.4, reveal: { model_solution: "print('hello') # <b>done</b>" } });
    mount();
    const card = await screen.findByTestId("build-task");
    expect(within(card).getByTestId("build-best")).toHaveTextContent("Best so far: 40%");
    expect(within(card).queryByTestId("build-solution")).toBeNull();
    fireEvent.click(within(card).getByRole("button", { name: /^check$/i }));
    const sol = await within(card).findByTestId("build-solution");
    expect(sol.querySelector("code")).toHaveTextContent("print('hello') # <b>done</b>");
    expect(sol.querySelector("b")).toBeNull();
    expect(within(card).getByRole("status")).toHaveTextContent(/No tries left/);
    expect(within(card).queryByRole("button", { name: /try again/i })).toBeNull();
    expect(within(card).getByTestId("build-best")).toHaveTextContent("Best so far: 40%");
  });

  it.each([
    ["submitted", /already handed in the final/],
    ["grading_unavailable", /Checking isn't available right now/],
    ["not_build", /isn't a build step any more/],
    ["bad_answer", /couldn't be read/],
    ["empty", /Add your work first/],
  ])("maps the %s error code to its own message", async (code, text) => {
    current = base({ stage_index: 1, stages: buildStages({ type: "open_input", payload: { prompt: "Write it." } }) });
    routes["/api/workshops/sessions/7/build/"] = () => {
      throw new ApiError(409, { code });
    };
    mount();
    const card = await screen.findByTestId("build-task");
    fireEvent.change(within(card).getByRole("textbox"), { target: { value: "My prompt." } });
    fireEvent.click(within(card).getByRole("button", { name: /^check$/i }));
    expect(await within(card).findByRole("alert")).toHaveTextContent(text);
  });

  it("prompt engineering's “Your real task” renders as a graded open_input build stage", async () => {
    current = base({
      workshop: { ...base().workshop, slug: "prompt-engineering", title: "Prompt Engineering" },
      stage_index: 1,
      stages: [
        { key: "building-blocks", kind: "teach", title: "The building blocks of a good prompt", minutes: 15, concepts: [{ text: "Role", done: true, explained: true }], steps: [] },
        {
          key: "real-task", kind: "build", title: "Your real task", minutes: 20, concepts: [], cursor: 0,
          steps: [{ text: "Pick a real task from your work or studies", done: false }],
          task: {
            type: "open_input", title: "Your real task", attempts_left: 5, best_score: null, attempt: null,
            payload: { prompt: "Paste the final prompt you wrote for your real task. Show at least four building blocks: role, task and context, format, examples, constraints." },
          },
        },
        { key: "final", kind: "assessment", title: "Final", minutes: 10, concepts: [], steps: [] },
      ],
    });
    let sent: unknown;
    routes["/api/workshops/sessions/7/build/"] = (init) => {
      sent = init?.json;
      return { score: 0.8, passed: true, feedback: "Clear role and format.", attempts_left: 4, best_score: 0.8 };
    };
    mount();
    expect(await screen.findByRole("heading", { name: "Your real task" })).toBeInTheDocument();
    expect(screen.getByText("Pick a real task from your work or studies")).toBeInTheDocument();
    const card = screen.getByTestId("build-task");
    expect(card).toHaveTextContent(/Show at least four building blocks/);
    expect(within(card).getByTestId("build-attempts")).toHaveTextContent("5 tries left");
    fireEvent.click(screen.getByRole("button", { name: /show my screen or paste the error/i })); // hands-on: help is one tap away
    expect(screen.getByRole("heading", { name: "Stuck? Get help" })).toBeInTheDocument();
    fireEvent.change(within(card).getByRole("textbox"), { target: { value: "You are a career coach. Rewrite my CV summary as 3 bullets." } });
    fireEvent.click(within(card).getByRole("button", { name: /^check$/i }));
    expect(await within(card).findByRole("status")).toHaveTextContent(/Passed\. Tap “Yes, next”/);
    expect(sent).toEqual({ answer: { text: "You are a career coach. Rewrite my CV summary as 3 bullets." } });
    expect(within(card).getByTestId("build-best")).toHaveTextContent("Best so far: 80%");
  });

  it("ignores a task type this app can't render (the stage still shows its steps)", async () => {
    current = base({ stage_index: 1, stages: buildStages({ type: "hotspot", payload: {} }) });
    mount();
    await screen.findByRole("heading", { name: "Write your own prompt" });
    expect(screen.queryByTestId("build-task")).toBeNull();
    expect(screen.getByText("Use at least four building blocks")).toBeInTheDocument();
  });
});

describe("tracking notice and drawers (M5 polish)", () => {
  it("prerequisites show the same tracking box as the run page, including the no-camera line", async () => {
    current = base({ status: "prereq", started_at: null, proctoring: "activity" });
    mount();
    const box = await screen.findByTestId("proctor-box");
    expect(within(box).getByRole("heading", { name: "What we track" })).toBeInTheDocument();
    expect(box).toHaveTextContent(/Activity only/);
    expect(box).toHaveTextContent("Never the camera or microphone recording.");
  });

  it("the classroom keeps long titles whole and never fades checklist text below AA contrast", async () => {
    current = base({ workshop: { ...base().workshop, title: "A very long workshop title that should wrap on a phone instead of being cut off" } });
    mount();
    const h1 = await screen.findByRole("heading", { level: 1 });
    expect(h1.className).not.toMatch(/\btruncate\b/);
    expect(document.querySelectorAll('[class*="text-muted/"]')).toHaveLength(0);
  });

  it("moves focus into the agent drawer, keeps Tab inside it and returns focus on close", async () => {
    routes["/api/workshops/sessions/7/agent/"] = () => ({ name: "GST Helper", role: "", starter: "", servers: [], auto_approve: {}, runs_left: 40, mcp: null, aasan_tools: [] });
    current = base({
      stage_index: 1,
      stages: [
        { key: "build", kind: "agent_build", title: "Build your agent", minutes: 30, concepts: [], steps: [] },
        { key: "test", kind: "diy", title: "Test it", minutes: 10, concepts: [], steps: [{ text: "Ask it a sum", done: false }] },
      ],
    });
    mount();
    const opener = await screen.findByRole("button", { name: /^your agent$/i });
    opener.focus();
    fireEvent.click(opener);
    const drawer = await screen.findByRole("dialog", { name: /your agent/i });
    const close = within(drawer).getByRole("button", { name: /close/i });
    expect(close).toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(drawer.contains(document.activeElement)).toBe(true);
    fireEvent.click(close);
    await waitFor(() => expect(screen.queryByRole("dialog", { name: /your agent/i })).toBeNull());
    expect(opener).toHaveFocus();
  });
});
