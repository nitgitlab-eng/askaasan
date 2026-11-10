import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "@/lib/api";
import type { FamilyState } from "@/lib/billing";
import { apiRoutes, renderPage } from "@/test/render";

import { ManageFamily } from "./ManageFamily";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

const owner: FamilyState = {
  role: "owner", can_create: false, plan: { code: "family", name: "Family Plus" }, max_members: 4, active_until: "2026-11-20", owner_name: "Amma",
  members: [
    { id: 1, name: "Amma", is_owner: true, is_me: true, joined_at: "2026-10-01", email: "amma@home.in" },
    { id: 2, name: "Appa", is_owner: false, is_me: false, joined_at: "2026-10-02", email: "appa@home.in" },
  ],
  invites: [{ id: 5, email: "kid@home.in", expires_at: "2026-10-30" }],
  seats_left: 1,
};

describe("ManageFamily", () => {
  beforeEach(() => { vi.mocked(api).mockReset(); });

  it("owner sees members and invites, and gets a link to share when email isn't set up", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/billing/family/invite/": { invite: { id: 6, email: "paati@home.in", expires_at: "2026-10-31" }, emailed: false, links: [{ email: "paati@home.in", link: "http://x/family/tok", code: "ABC234" }] },
      "/api/billing/family/": owner,
      "/api/billing/": {},
    }) as never);
    renderPage(<ManageFamily />);
    expect(await screen.findByText("Your family plan")).toBeInTheDocument();
    expect(screen.getByText(/appa@home.in/)).toBeInTheDocument();
    expect(screen.getByText(/kid@home.in/)).toBeInTheDocument();
    expect(screen.getByText("3 of 4 places used")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Invite by email"), { target: { value: "paati@home.in" } });
    fireEvent.click(screen.getByRole("button", { name: "Send invite" }));
    expect(await screen.findByText("For paati@home.in · code ABC234")).toBeInTheDocument();
    expect(screen.getByText("http://x/family/tok")).toBeInTheDocument();
  });

  it("owner removes a member after confirming", async () => {
    const after = { ...owner, members: owner.members!.slice(0, 1) };
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/billing/family/members/2/remove/": after, "/api/billing/family/": owner, "/api/billing/": {} }) as never);
    renderPage(<ManageFamily />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
    fireEvent.click(await screen.findByRole("button", { name: "OK" }));
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledWith("/api/billing/family/members/2/remove/", { method: "POST" }));
    expect(await screen.findByText("Removed.")).toBeInTheDocument();
  });

  it("member sees the banner and can leave", async () => {
    const member: FamilyState = { role: "member", can_create: false, plan: { code: "family", name: "Family Plus" }, max_members: 4, active_until: "2026-11-20", owner_name: "Amma", members: [] };
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/billing/family/leave/": { role: null, can_create: false, plan: null, max_members: 0 }, "/api/billing/family/": member, "/api/billing/": {} }) as never);
    renderPage(<ManageFamily />);
    expect(await screen.findByText("You're on Amma's family plan: Family Plus")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Leave family plan" }));
    fireEvent.click(await screen.findByRole("button", { name: "OK" }));
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledWith("/api/billing/family/leave/", { method: "POST" }));
  });

  it("anyone else can join with a code and sees why it failed", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/billing/family/accept/": () => { throw new ApiError(403, { code: "seat_covered" }); },
      "/api/billing/family/": { role: null, can_create: false, plan: null, max_members: 0 },
    }) as never);
    renderPage(<ManageFamily />);
    fireEvent.change(await screen.findByLabelText(/6-character code/), { target: { value: "abc-234" } });
    fireEvent.click(screen.getByRole("button", { name: "Join" }));
    expect(await screen.findByText(/already gives you this plan/)).toBeInTheDocument();
    expect(vi.mocked(api)).toHaveBeenCalledWith("/api/billing/family/accept/", { method: "POST", json: { code: "ABC234" } });
  });
});
