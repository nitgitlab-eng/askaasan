import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";
import { apiRoutes, renderPage } from "@/test/render";
import AdminWorkshops from "@/pages/admin/Workshops";

import WorkshopsPage from "./Workshops";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));
const navigate = vi.fn();
vi.mock("react-router-dom", async (orig) => ({ ...(await orig<typeof import("react-router-dom")>()), useNavigate: () => navigate }));

const NOW = Date.parse("2026-10-18T10:00:00Z");
const at = (mins: number) => new Date(NOW + mins * 60_000).toISOString();
const ws = { slug: "quick-check", title: "Quick Check Workshop", summary: "Ten minutes, end to end.", level: "beginner", duration_minutes: 10 };
/** A public run starting `start` minutes from now, with a 15-minute lobby and late join. */
const run = (over: object = {}, start = 120) => ({
  id: 1, workshop: ws, starts_at: at(start), status: "scheduled", price_paise: 0, enrolled: false, session_id: null, audience: "public", my_status: "none", seats_left: null,
  lobby_opens_at: at(start - 15), join_opens_at: at(start - 15), join_closes_at: at(start + 15), ...over,
});

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  navigate.mockReset();
});
afterEach(() => vi.useRealTimers());

describe("workshops list", () => {
  it("splits runs into My workshops, Upcoming and Past, with price, seats and a countdown", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/workshops/runs/": [
        run({ id: 1, workshop: { ...ws, title: "Prompt Engineering" }, price_paise: 49900, seats_left: 3 }, 26 * 60 + 5),
        run({ id: 2, workshop: { ...ws, title: "AI in Your World" }, enrolled: true, my_status: "enrolled" }, 10),
        run({ id: 3, workshop: { ...ws, title: "Old one" }, enrolled: true, status: "ended" }, -600),
        run({ id: 4, workshop: { ...ws, title: "Agentic" }, my_status: "paid_pending" }, 300),
      ],
    }) as typeof api);
    renderPage(<WorkshopsPage />);
    const mine = await screen.findByRole("region", { name: "My workshops" });
    const upcoming = screen.getByRole("region", { name: "Upcoming" });
    const past = screen.getByRole("region", { name: "Past workshops" });

    expect(within(upcoming).getByText("Prompt Engineering")).toBeInTheDocument();
    expect(within(upcoming).getByText("₹499")).toBeInTheDocument();
    expect(within(upcoming).getByText("3 seats left")).toBeInTheDocument();
    expect(within(upcoming).getByRole("timer")).toHaveTextContent("1 d 2 h");
    expect(within(upcoming).getByRole("link", { name: /see details/i })).toHaveAttribute("href", "/workshops/1");

    // in the lobby window: straight to the lobby
    expect(within(mine).getByText("AI in Your World")).toBeInTheDocument();
    expect(within(mine).getByRole("link", { name: /go to the lobby/i })).toHaveAttribute("href", "/workshops/2/lobby");
    expect(within(mine).getAllByRole("timer").map((x) => x.textContent)).toEqual(["10 min 00 s", "5 h 0 min"]);
    expect(within(mine).getByText(/confirming your payment/i)).toBeInTheDocument();

    expect(within(past).getByText("Old one")).toBeInTheDocument();
    expect(within(past).getByText("Ended")).toBeInTheDocument();
  });

  it("joins once the run has started, and opens the session", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/workshops/runs/2/session/": { id: 9 },
      "/api/workshops/runs/": [run({ id: 2, enrolled: true, my_status: "enrolled", status: "live" }, -5)],
    }) as typeof api);
    renderPage(<WorkshopsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /join now/i }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/workshops/session/9"));
  });

  it("staff test runs (no join window) open any time", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/workshops/runs/1/session/": { id: 9 },
      "/api/workshops/runs/": [run({ enrolled: true, audience: "test", lobby_opens_at: null, join_opens_at: null, join_closes_at: null })],
    }) as typeof api);
    renderPage(<WorkshopsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /open workshop/i }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/workshops/session/9"));
  });
});

describe("past runs (M5 polish)", () => {
  it("are not faded with opacity (which dropped muted text below AA contrast)", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/workshops/runs/": [run({ status: "ended" }, -600)] }) as typeof api);
    renderPage(<WorkshopsPage />);
    await screen.findByRole("region", { name: "Past workshops" });
    const card = document.querySelector('[data-section="past"]')!;
    expect(card).not.toBeNull();
    expect(card.className).not.toMatch(/opacity-/);
  });
});

describe("join errors", () => {
  it.each([
    [{ code: "too_early", opens_at: "2026-10-20T04:30:00Z" }, 409, /opens at .*2026/],
    [{ code: "too_late" }, 409, /joining has closed/i],
    [{ code: "run_cancelled" }, 409, /was cancelled/i],
    [{ code: "run_full" }, 409, /is full/i],
    [{ code: "run_closed" }, 409, /has ended/i],
    [{ code: "not_enrolled" }, 403, /enrol first/i],
  ])("%o", async (data, status, text) => {
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/workshops/runs/1/session/": () => {
        throw new ApiError(status, data);
      },
      "/api/workshops/runs/": [run({ enrolled: true, status: "live" }, -1)],
    }) as typeof api);
    renderPage(<WorkshopsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /join now/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });
});

describe("admin workshops", () => {
  const templates = [{ slug: "quick-check", title: "Quick Check Workshop", duration_minutes: 10, proctoring: "off" }];
  const adminRun = (over: object = {}) => ({
    id: 5, workshop: { slug: "quick-check", title: "Quick Check Workshop" }, starts_at: "2026-11-01T10:00:00Z", status: "scheduled", capacity: 100, price_paise: 0,
    proctoring: "", late_join_minutes: 15, lobby_opens_minutes: 15, announced_at: null, enrolled: 0, sessions_started: 0, sessions_passed: 0, ...over,
  });

  it("creates a test run and drops the admin into its session", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/admin/workshops/quick-check/test-run/": { run_id: 5, session_id: 11 },
      "/api/admin/workshops/": templates,
    }) as typeof api);
    renderPage(<AdminWorkshops />);
    fireEvent.click(await screen.findByRole("button", { name: /test run/i }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/workshops/session/11"));
  });

  it("validates the run form: free needs no price, paid needs ₹1–₹10,000, then posts paise and IST", async () => {
    const posts: unknown[] = [];
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/admin/workshops/runs/": (init?: { method?: string; json?: unknown }) => (init?.method === "POST" ? (posts.push(init.json), adminRun()) : []),
      "/api/admin/workshops/": templates,
    }) as typeof api);
    renderPage(<AdminWorkshops />);
    fireEvent.click(await screen.findByRole("tab", { name: "Scheduled runs" }));
    fireEvent.click(await screen.findByRole("button", { name: /schedule a run/i }));

    fireEvent.click(screen.getByRole("button", { name: /create draft/i }));
    expect(await screen.findByText("Choose a workshop.")).toBeInTheDocument();
    expect(screen.getByText("Pick a date and a start time.")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Workshop" }), { target: { value: "quick-check" } });
    fireEvent.change(screen.getByLabelText(/^Date/), { target: { value: "2026-11-01" } });
    fireEvent.change(screen.getByLabelText("Start time (IST)"), { target: { value: "15:30" } });
    expect(screen.queryByLabelText("Price (₹)")).toBeNull(); // free: no price box

    fireEvent.click(screen.getByRole("radio", { name: "Paid" }));
    fireEvent.change(screen.getByLabelText(/^Price \(₹\)/), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: /create draft/i }));
    expect(await screen.findByText("Enter a price from ₹1 to ₹10,000.")).toBeInTheDocument();
    expect(posts).toHaveLength(0);

    fireEvent.change(screen.getByLabelText(/^Price \(₹\)/), { target: { value: "499" } });
    fireEvent.click(screen.getByRole("button", { name: /create draft/i }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({ workshop_slug: "quick-check", starts_at: "2026-11-01T10:00:00.000Z", price_paise: 49900, capacity: 0 });

    // free again: price 0 whatever was typed
    fireEvent.click(await screen.findByRole("button", { name: /schedule a run/i }));
    fireEvent.change(screen.getByRole("combobox", { name: "Workshop" }), { target: { value: "quick-check" } });
    fireEvent.change(screen.getByLabelText(/^Date/), { target: { value: "2026-11-01" } });
    fireEvent.change(screen.getByLabelText("Start time (IST)"), { target: { value: "15:30" } });
    fireEvent.click(screen.getByRole("button", { name: /create draft/i }));
    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1]).toMatchObject({ price_paise: 0 });
  });

  it("shows the server's {code} beside its field, or under the form when it has none", async () => {
    let reply: Record<string, unknown> = { code: "bad_price" };
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/admin/workshops/runs/": (init?: { method?: string }) => {
        if (init?.method === "POST") throw new ApiError(400, reply);
        return [];
      },
      "/api/admin/workshops/": templates,
    }) as typeof api);
    renderPage(<AdminWorkshops />);
    fireEvent.click(await screen.findByRole("tab", { name: "Scheduled runs" }));
    fireEvent.click(await screen.findByRole("button", { name: /schedule a run/i }));
    fireEvent.change(screen.getByRole("combobox", { name: "Workshop" }), { target: { value: "quick-check" } });
    fireEvent.change(screen.getByLabelText(/^Date/), { target: { value: "2026-11-01" } });
    fireEvent.change(screen.getByLabelText("Start time (IST)"), { target: { value: "15:30" } });
    fireEvent.click(screen.getByRole("radio", { name: "Paid" }));
    fireEvent.change(screen.getByLabelText(/^Price \(₹\)/), { target: { value: "499" } });
    fireEvent.click(screen.getByRole("button", { name: /create draft/i }));
    expect(await screen.findByLabelText(/^Price \(₹\)/)).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("Enter 0 for free, or a price from ₹1 to ₹10,000.");

    reply = { code: "not_editable" };
    fireEvent.click(screen.getByRole("button", { name: /create draft/i }));
    expect(await screen.findByText(/can't be edited any more/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Price \(₹\)/)).toHaveAttribute("aria-invalid", "false");
  });

  it("edits a scheduled run: template locked, PATCH without the template", async () => {
    const patches: unknown[] = [];
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/admin/workshops/runs/5/": (init?: { json?: unknown }) => (patches.push(init?.json), adminRun()),
      "/api/admin/workshops/runs/": [adminRun({ capacity: 0 })],
      "/api/admin/workshops/": templates,
    }) as typeof api);
    renderPage(<AdminWorkshops />);
    fireEvent.click(await screen.findByRole("tab", { name: "Scheduled runs" }));
    fireEvent.click(await screen.findByRole("button", { name: /^edit$/i }));
    expect(screen.getByRole("combobox", { name: "Workshop" })).toBeDisabled();
    expect(screen.getByLabelText("Start time (IST)")).toHaveValue("15:30");
    fireEvent.change(screen.getByLabelText(/^Capacity/), { target: { value: "50" } });
    fireEvent.click(screen.getByRole("button", { name: /save changes/i }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({ capacity: 50, starts_at: "2026-11-01T10:00:00.000Z" });
    expect(patches[0]).not.toHaveProperty("workshop_slug");
  });

  it("asks before announcing to every user, and only announces on OK", async () => {
    const announce = vi.fn(() => adminRun({ announced_at: "2026-10-18T10:00:00Z" }));
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/admin/workshops/runs/5/announce/": announce,
      "/api/admin/workshops/runs/": [adminRun()],
      "/api/admin/workshops/": templates,
    }) as typeof api);
    renderPage(<AdminWorkshops />);
    fireEvent.click(await screen.findByRole("tab", { name: "Scheduled runs" }));

    fireEvent.click(await screen.findByRole("button", { name: /^announce$/i }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/this notifies every user/i);
    fireEvent.click(within(dialog).getByRole("button", { name: /cancel/i }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(announce).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /^announce$/i }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: /^announce$/i }));
    await waitFor(() => expect(announce).toHaveBeenCalledTimes(1));
  });

  it("shows aggregate stats per run, and publishes drafts", async () => {
    const publish = vi.fn(() => adminRun());
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/admin/workshops/runs/5/stats/": { id: 5, status: "draft", enrolled: 40, joined: 31, started: 28, finished: 25, passed: 20, avg_score: 0.72, avg_minutes: 74.4, help_requests: 9 },
      "/api/admin/workshops/runs/5/publish/": publish,
      "/api/admin/workshops/runs/": [adminRun({ status: "draft", price_paise: 49900, enrolled: 40 })],
      "/api/admin/workshops/": templates,
    }) as typeof api);
    renderPage(<AdminWorkshops />);
    fireEvent.click(await screen.findByRole("tab", { name: "Scheduled runs" }));
    expect(await screen.findByText("₹499")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^stats$/i }));
    const stats = await screen.findByTestId("stats-5");
    expect(stats).toHaveTextContent("72%");
    expect(stats).toHaveTextContent(/Started28/);
    expect(stats).toHaveTextContent("74 min");
    expect(stats).toHaveTextContent(/never show individual learners/i);
    fireEvent.click(screen.getByRole("button", { name: /publish/i }));
    await waitFor(() => expect(publish).toHaveBeenCalled());
    // Valid markup: the note sits outside the <dl>, whose children are only term/value groups.
    const dl = stats.querySelector("dl")!;
    expect([...dl.children].every((c) => c.tagName === "DIV" && c.querySelector("dt") && c.querySelector("dd"))).toBe(true);
  });

  it("tabs follow the ARIA pattern: one tab stop, arrow keys, Home and End", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/admin/workshops/runs/": [], "/api/admin/workshops/": templates }) as typeof api);
    renderPage(<AdminWorkshops />);
    const first = await screen.findByRole("tab", { name: "Templates" });
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((x) => x.getAttribute("tabindex"))).toEqual(["0", "-1", "-1"]);
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    expect(tabs[1]).toHaveFocus();
    expect(tabs.map((x) => x.getAttribute("tabindex"))).toEqual(["-1", "0", "-1"]);
    fireEvent.keyDown(tabs[1], { key: "End" });
    expect(tabs[2]).toHaveFocus();
    fireEvent.keyDown(tabs[2], { key: "ArrowRight" });
    expect(tabs[0]).toHaveFocus(); // wraps
    fireEvent.keyDown(tabs[0], { key: "ArrowLeft" });
    expect(tabs[2]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(tabs[2], { key: "Home" });
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
  });
});
