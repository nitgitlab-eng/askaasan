import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";
import { downloadFile } from "@/lib/download";
import { apiRoutes, renderPage } from "@/test/render";

import Cockpit from "./Cockpit";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));
vi.mock("@/lib/download", () => ({ downloadFile: vi.fn(async () => {}) }));
vi.mock("@/components/tour/tourStore", () => ({ useAutoTour: () => {} }));

const apiMock = vi.mocked(api);
const run = (id: number, status: string, starts: string, over: object = {}) => ({
  id, status, starts_at: starts, workshop: { slug: "quick-check", title: `Quick Check ${id}` }, proctoring: "off", late_join_minutes: 15, lobby_opens_minutes: 15,
  groups: [{ id: 3, name: "BSc CS A" }], cohorts: [], enrolled: 40, ...over,
});
let role = "admin";
let features: Record<string, boolean> | undefined;
let runs: unknown = [];
let posted: unknown = null;
let postError: Error | null = null;

beforeEach(() => {
  role = "admin";
  features = undefined;
  posted = null;
  postError = null;
  runs = { runs: [run(1, "scheduled", "2099-01-05T05:00:00Z"), run(2, "ended", "2026-09-01T05:00:00Z", { started: 38, passed: 30 })], quota: { limit: 500, used: 40 } };
  apiMock.mockImplementation(apiRoutes({
    "/api/orgs/acme/workshops/templates/": [{ slug: "quick-check", title: "Quick Check Workshop", duration_minutes: 10, proctoring: "off" }],
    "/api/orgs/acme/workshops/runs/1/cancel/": () => ({ ...run(1, "cancelled", "2099-01-05T05:00:00Z") }),
    "/api/orgs/acme/workshops/runs/": (init?: { method?: string; json?: unknown }) => {
      if (runs instanceof Error) throw runs;
      if (init?.method === "POST") {
        if (postError) throw postError;
        posted = init.json;
        return run(9, "scheduled", "2099-02-01T05:00:00Z");
      }
      return runs;
    },
    "/api/orgs/acme/groups/": [{ id: 3, name: "BSc CS A", join_code: "AAA", members: 40 }, { id: 4, name: "BSc CS B", join_code: "BBB", members: 38 }],
    "/api/orgs/acme/cohorts/": [{ id: 9, name: "Summer AI cohort" }],
    "/api/orgs/acme/analytics/": () => {
      throw new ApiError(500, {});
    },
    "/api/orgs/acme/setup/": { steps: [], complete: true },
    "/api/orgs/acme/dpa/": {},
    "/api/orgs/acme/": () => ({ id: 1, slug: "acme", name: "Acme College", kind: "college", role, members: 80, groups: 2, ...(features ? { features } : {}) }),
  }) as typeof api);
});
afterEach(() => apiMock.mockReset());

async function openTab() {
  renderPage(<Cockpit />, { route: "/org/acme", path: "/org/:slug" });
  fireEvent.click(await screen.findByRole("tab", { name: /Workshops/ }));
}

describe("cockpit Workshops tab", () => {
  it("is hidden when the org feature is off (the runs list answers 403)", async () => {
    runs = new ApiError(403, { code: "feature_off", feature: "workshops" });
    renderPage(<Cockpit />, { route: "/org/acme", path: "/org/:slug" });
    await screen.findByRole("tab", { name: /Overview/ });
    await waitFor(() => expect(apiMock).toHaveBeenCalledWith("/api/orgs/acme/workshops/runs/"));
    expect(screen.queryByRole("tab", { name: /Workshops/ })).toBeNull();
  });

  it("follows the org's features.workshops when the server sends it, without probing", async () => {
    features = { workshops: false };
    renderPage(<Cockpit />, { route: "/org/acme", path: "/org/:slug" });
    await screen.findByRole("tab", { name: /Overview/ });
    expect(screen.queryByRole("tab", { name: /Workshops/ })).toBeNull();
    expect(apiMock).not.toHaveBeenCalledWith("/api/orgs/acme/workshops/runs/");
  });

  it("shows the tab from features.workshops = true", async () => {
    features = { workshops: true };
    await openTab();
    expect(await screen.findByTestId("org-run-1")).toBeInTheDocument();
  });

  it("lists upcoming and past runs with the quota, dashboard links and reports", async () => {
    await openTab();
    expect(await screen.findByText("Workshop seats this month: 40 of 500")).toBeInTheDocument();
    const upcoming = screen.getByTestId("org-run-1");
    expect(within(upcoming).getByRole("link", { name: /Open live dashboard/ })).toHaveAttribute("href", "/org/acme/workshops/1/live");
    expect(within(upcoming).queryByRole("button", { name: /Download the report/ })).toBeNull();
    const past = screen.getByTestId("org-run-2");
    fireEvent.click(within(past).getByRole("button", { name: "Download the report as PPTX" }));
    await waitFor(() => expect(downloadFile).toHaveBeenCalledWith("/api/orgs/acme/workshops/runs/2/report.pptx", "workshop-report-2.pptx"));
  });

  it("says when no seats are set for the month (limit 0)", async () => {
    runs = { runs: [], quota: { limit: 0, used: 0, month: "2026-10" }, can_manage: true };
    await openTab();
    expect(await screen.findByTestId("seat-quota")).toHaveTextContent("No workshop seats are set for this month yet.");
  });

  it("validates the schedule form, then posts classes, cohorts and proctoring", async () => {
    await openTab();
    fireEvent.click(await screen.findByRole("button", { name: /Schedule a workshop/ }));
    fireEvent.click(screen.getByRole("button", { name: "Schedule and enrol" }));
    expect(await screen.findByText("Choose a workshop.")).toBeInTheDocument();
    expect(screen.getByText("Pick a date and a start time.")).toBeInTheDocument();
    expect(screen.getByText("Pick at least one class or cohort.")).toBeInTheDocument();
    expect(posted).toBeNull();

    await screen.findByRole("option", { name: /Quick Check Workshop/ });
    fireEvent.change(screen.getByLabelText("Workshop"), { target: { value: "quick-check" } });
    fireEvent.change(screen.getByLabelText(/^Date/), { target: { value: "2099-03-01" } });
    fireEvent.change(screen.getByLabelText("Start time (IST)"), { target: { value: "10:00" } });
    fireEvent.click(await screen.findByRole("checkbox", { name: "BSc CS B" }));
    fireEvent.click(await screen.findByRole("checkbox", { name: "Summer AI cohort" }));
    const proctor = screen.getByRole("switch", { name: /Activity tracking/ });
    expect(proctor).toHaveAttribute("aria-checked", "false");
    fireEvent.click(proctor);
    fireEvent.click(screen.getByRole("button", { name: "Schedule and enrol" }));
    await waitFor(() => expect(posted).toEqual({
      workshop_slug: "quick-check", starts_at: "2099-03-01T04:30:00.000Z", groups: [4], cohorts: [9], proctoring: "activity", late_join_minutes: 15, lobby_opens_minutes: 15,
    }));
  });

  it("shows the server's quota error beside the classes", async () => {
    await openTab();
    postError = new ApiError(400, { code: "quota_exceeded" });
    fireEvent.click(await screen.findByRole("button", { name: /Schedule a workshop/ }));
    await screen.findByRole("option", { name: /Quick Check Workshop/ });
    fireEvent.change(screen.getByLabelText("Workshop"), { target: { value: "quick-check" } });
    fireEvent.change(screen.getByLabelText(/^Date/), { target: { value: "2099-03-01" } });
    fireEvent.change(screen.getByLabelText("Start time (IST)"), { target: { value: "10:00" } });
    fireEvent.click(await screen.findByRole("checkbox", { name: "BSc CS A" }));
    fireEvent.click(screen.getByRole("button", { name: "Schedule and enrol" }));
    expect(await screen.findByText("That's more learners than this month's workshop seats allow.")).toBeInTheDocument();
  });

  it("cancels an upcoming run after confirming", async () => {
    await openTab();
    fireEvent.click(within(await screen.findByTestId("org-run-1")).getByRole("button", { name: /Cancel workshop/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /Cancel workshop/ }));
    await waitFor(() => expect(apiMock).toHaveBeenCalledWith("/api/orgs/acme/workshops/runs/1/cancel/", { method: "POST" }));
  });

  it("teachers open dashboards but can't schedule or cancel", async () => {
    role = "manager";
    await openTab();
    expect(await screen.findByText(/You see your own classes only/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Schedule a workshop/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Cancel workshop/ })).toBeNull();
    expect(within(screen.getByTestId("org-run-1")).getByRole("link", { name: /Open live dashboard/ })).toBeInTheDocument();
  });
});
