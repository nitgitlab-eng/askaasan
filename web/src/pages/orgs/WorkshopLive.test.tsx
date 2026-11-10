import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { downloadFile } from "@/lib/download";
import type { Tile } from "@/lib/orgWorkshops";
import { apiRoutes, renderPage } from "@/test/render";

import WorkshopLivePage from "./WorkshopLive";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn(), ensureFreshAccess: vi.fn(async () => "tok") }));
vi.mock("@/lib/download", () => ({ downloadFile: vi.fn(async () => {}) }));

class FakeSocket {
  static all: FakeSocket[] = [];
  static OPEN = 1;
  readyState = 0;
  sent: Record<string, unknown>[] = [];
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

const tile = (id: number, name: string, over: Partial<Tile> = {}): Tile => ({
  session_id: id, learner: { id: 100 + id, name }, status: "engaged", stage: { index: 1, title: "Tools and loops", kind: "teach" }, concept: "What a tool call is",
  diy: null, score_so_far: 0.5, attention: null, help_summaries: [], raised_hand: false, last_activity_at: null, pace: "on_track", ...over,
});

const apiMock = vi.mocked(api);
const RUNS = [{ id: 5, workshop: { slug: "agentic", title: "AI Agentic Workshop" }, starts_at: "2026-10-18T05:00:00Z", status: "live", proctoring: "off", late_join_minutes: 15, lobby_opens_minutes: 15 }];
let role = "admin";

beforeEach(() => {
  FakeSocket.all = [];
  role = "admin";
  vi.stubGlobal("WebSocket", FakeSocket);
  apiMock.mockImplementation(apiRoutes({
    "/api/orgs/acme/workshops/runs/5/learners/2/": {
      learner: { id: 102, name: "Bala" },
      stages: [{ index: 0, title: "What an agent is", status: "done", score: 0.8, minutes: 12 }],
      answers: [{ question: "What is a tool?", answer: "<img src=x onerror=alert(1)>", score: 0.4 }],
      help: [{ at: "2026-10-18T05:20:00Z", summary: "pip install failed: no internet proxy" }],
      attention: null,
      transcript: [{ role: "learner", text: "I am stuck" }],
    },
    "/api/orgs/acme/workshops/runs/": RUNS,
    "/api/orgs/acme/": () => ({ id: 1, slug: "acme", name: "Acme College", kind: "college", role, members: 3, groups: 1 }),
  }) as typeof api);
});
afterEach(() => {
  vi.unstubAllGlobals();
  apiMock.mockReset();
});

async function mount() {
  renderPage(<WorkshopLivePage />, { route: "/org/acme/workshops/5/live", path: "/org/:slug/workshops/:runId/live" });
  await waitFor(() => expect(FakeSocket.all.length).toBe(1));
  const s = FakeSocket.all[0];
  act(() => s.open());
  return s;
}

const tileNames = () => screen.getAllByTestId(/^tile-/).map((el) => el.getAttribute("aria-label")!.split(" · ")[0]);

describe("live faculty dashboard", () => {
  it("shows the snapshot, then applies a single tile update", async () => {
    const s = await mount();
    expect(s.url).toMatch(/\/ws\/workshop-runs\/5\/monitor\/$/);
    expect(s.sent[0]).toEqual({ type: "auth", token: "tok" });
    s.msg({ type: "snapshot", tiles: [tile(1, "Anu"), tile(2, "Bala", { help_summaries: ["missing API key"] })] });
    expect(await screen.findByText("Anu")).toBeInTheDocument();
    expect(screen.getByText("missing API key")).toBeInTheDocument();
    expect(screen.getByText("2 learners")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "AI Agentic Workshop" })).toBeInTheDocument();
    s.msg({ type: "tile", tile: tile(2, "Bala", { status: "stuck", diy: { done: 2, total: 5 } }) });
    await waitFor(() => expect(within(screen.getByTestId("tile-2")).getByText("Stuck")).toBeInTheDocument());
    expect(within(screen.getByTestId("tile-2")).getByText("2/5 steps")).toBeInTheDocument();
    expect(within(screen.getByTestId("tile-1")).getByText("Engaged")).toBeInTheDocument();
  });

  it("lists enrolled learners who haven't joined, as plain text, and drops them when their tile arrives", async () => {
    const s = await mount();
    s.msg({ type: "snapshot", run: { id: 5, proctoring: "off" }, tiles: [tile(1, "Anu")], not_joined: [{ id: 102, name: "<i>Bala</i>", roll_no: "21CS02" }, { id: 103, name: "Chitra" }] });
    const box = await screen.findByTestId("not-joined");
    expect(within(box).getByText("Enrolled, not joined yet (2)")).toBeInTheDocument();
    expect(within(box).getByText("<i>Bala</i>")).toBeInTheDocument();
    expect(box.querySelector("i")).toBeNull();
    s.msg({ type: "tile", tile: tile(2, "<i>Bala</i>") });
    await waitFor(() => expect(within(screen.getByTestId("not-joined")).getByText("Enrolled, not joined yet (1)")).toBeInTheDocument());
    expect(within(screen.getByTestId("not-joined")).queryByText("<i>Bala</i>")).toBeNull();
    s.msg({ type: "tile", tile: tile(3, "Chitra") });
    await waitFor(() => expect(screen.queryByTestId("not-joined")).toBeNull());
  });

  it("filters by status chips and sorts needs-attention first", async () => {
    const s = await mount();
    s.msg({ type: "snapshot", tiles: [tile(1, "Anu"), tile(2, "Bala", { status: "stuck" }), tile(3, "Chitra", { status: "needs_help" }), tile(4, "Divya", { raised_hand: true })] });
    await screen.findByText("Anu");
    expect(tileNames()).toEqual(["Divya", "Chitra", "Bala", "Anu"]);
    expect(screen.getByText("1 hand raised")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "By name" }));
    expect(tileNames()).toEqual(["Anu", "Bala", "Chitra", "Divya"]);
    fireEvent.click(screen.getByTestId("chip-stuck"));
    expect(tileNames()).toEqual(["Bala"]);
    fireEvent.click(screen.getByTestId("chip-needs_help"));
    expect(tileNames()).toEqual(["Bala", "Chitra"]);
    fireEvent.click(screen.getByRole("button", { name: /^All/ }));
    expect(tileNames()).toHaveLength(4);
  });

  it("shows attention only when the server sends it (proctoring on)", async () => {
    const s = await mount();
    s.msg({ type: "snapshot", tiles: [tile(1, "Anu"), tile(2, "Bala", { attention: { hidden_s: 120, idle_s: 60, focus_losses: 3 } })] });
    await screen.findByText("Anu");
    expect(within(screen.getByTestId("tile-1")).queryByTestId("attention")).toBeNull();
    expect(within(screen.getByTestId("tile-2")).getByTestId("attention")).toHaveTextContent("Away 2 min · Idle 1 min · Left the window 3×");
  });

  it("drawer: timeline as plain text, a nudge over the socket, and acknowledge hand", async () => {
    const s = await mount();
    s.msg({ type: "snapshot", tiles: [tile(1, "Anu"), tile(2, "Bala", { raised_hand: true, status: "needs_help" })] });
    fireEvent.click(await screen.findByTestId("tile-2"));
    const dialog = await screen.findByRole("dialog", { name: "Bala" });
    expect(await within(dialog).findByText("pip install failed: no internet proxy")).toBeInTheDocument();
    expect(within(dialog).getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument(); // text, not markup
    expect(dialog.querySelector("img")).toBeNull();
    expect(apiMock).toHaveBeenCalledWith("/api/orgs/acme/workshops/runs/5/learners/2/");
    fireEvent.change(within(dialog).getByLabelText("Send a nudge"), { target: { value: "Try the next step yourself first" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /^Send$/ }));
    expect(s.sent).toContainEqual({ type: "nudge", session_id: 2, text: "Try the next step yourself first" });
    expect(within(dialog).getByRole("status")).toHaveTextContent("Sent.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Acknowledge hand" }));
    expect(s.sent).toContainEqual({ type: "ack_hand", session_id: 2 });
    expect(within(dialog).queryByRole("button", { name: "Acknowledge hand" })).toBeNull();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("drawer: focus moves in, Tab wraps inside, focus returns to the tile; a failed nudge is an alert", async () => {
    const s = await mount();
    s.msg({ type: "snapshot", tiles: [tile(1, "Anu"), tile(2, "Bala")] });
    const opener = await screen.findByTestId("tile-2");
    opener.focus();
    fireEvent.click(opener);
    const dialog = await screen.findByRole("dialog", { name: "Bala" });
    const close = within(dialog).getByRole("button", { name: "Close" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true }); // from the first control back to the last
    expect(dialog.contains(document.activeElement)).toBe(true);
    expect(close).not.toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab" });
    s.readyState = 3; // the socket dropped: the nudge can't go
    fireEvent.change(within(dialog).getByLabelText("Send a nudge"), { target: { value: "Hello" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /^Send$/ }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent(/Not connected/);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
  });

  it("drawer: attention events without durations when proctoring is on", async () => {
    apiMock.mockImplementation(apiRoutes({
      "/api/orgs/acme/workshops/runs/5/learners/1/": { learner: { id: 101, name: "Anu" }, stages: [], answers: [], help: [], transcript: [],
        attention: [{ at: "2026-10-18T05:10:00Z", kind: "tab_hidden", seconds: null }], attention_summary: { hidden_s: 40, idle_s: 0, focus_losses: 1 } },
      "/api/orgs/acme/workshops/runs/": RUNS,
      "/api/orgs/acme/": { id: 1, slug: "acme", name: "Acme College", kind: "college", role: "admin", members: 3, groups: 1 },
    }) as typeof api);
    const s = await mount();
    s.msg({ type: "snapshot", tiles: [tile(1, "Anu", { attention: { hidden_s: 40, idle_s: 0, focus_losses: 1 } })], not_joined: [] });
    fireEvent.click(await screen.findByTestId("tile-1"));
    const dialog = await screen.findByRole("dialog", { name: "Anu" });
    const item = await within(dialog).findByText(/Switched tab/);
    expect(item.textContent).not.toMatch(/second/);
  });

  it("a teacher sees only the tiles the server scoped to their classes", async () => {
    role = "manager";
    const s = await mount();
    s.msg({ type: "snapshot", tiles: [tile(7, "Ezhil")] });
    s.msg({ type: "tile", tile: tile(7, "Ezhil", { status: "idle" }) });
    await screen.findByText("Ezhil");
    expect(screen.getAllByTestId(/^tile-/)).toHaveLength(1);
    expect(screen.getByText("1 learner")).toBeInTheDocument();
  });

  it("is refused for someone without access (4403), without retrying", async () => {
    const s = await mount();
    act(() => s.onclose?.({ code: 4403 }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Only your institution's staff can see this dashboard.");
    expect(FakeSocket.all).toHaveLength(1);
  });

  it("downloads the report files", async () => {
    await mount();
    fireEvent.click(await screen.findByRole("button", { name: "Download the report as PDF" }));
    await waitFor(() => expect(downloadFile).toHaveBeenCalledWith("/api/orgs/acme/workshops/runs/5/report.pdf", "workshop-report-5.pdf"));
    fireEvent.click(screen.getByRole("button", { name: "Download the report as CSV" }));
    await waitFor(() => expect(downloadFile).toHaveBeenCalledWith("/api/orgs/acme/workshops/runs/5/report.csv", "workshop-report-5.csv"));
    expect(screen.getByRole("button", { name: "Download the report as PPTX" })).toBeInTheDocument();
  });
});
