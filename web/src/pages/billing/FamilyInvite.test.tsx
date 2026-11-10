import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "@/lib/api";
import { apiRoutes, renderPage } from "@/test/render";

import FamilyInvitePage from "./FamilyInvite";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

const preview = { owner_name: "Amma", plan: "Family Plus", email_hint: "ap…@home.in", for_you: true, problem: null, expires_at: "2026-10-30" };

describe("FamilyInvite page", () => {
  beforeEach(() => { vi.mocked(api).mockReset(); });

  it("shows who invited you and joins only on click", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/billing/family/invites/": preview,
      "/api/billing/family/accept/": { role: "member", can_create: false, plan: { code: "family", name: "Family Plus" }, max_members: 4 },
    }) as never);
    renderPage(<FamilyInvitePage />, { route: "/family/tok123", path: "/family/:token" });
    expect(await screen.findByText("Amma invited you to share Family Plus")).toBeInTheDocument();
    expect(vi.mocked(api)).not.toHaveBeenCalledWith("/api/billing/family/accept/", expect.anything());
    fireEvent.click(screen.getByRole("button", { name: "Join the family plan" }));
    expect(await screen.findByText("You're in! Family Plus from Amma is now yours too.")).toBeInTheDocument();
    expect(vi.mocked(api)).toHaveBeenCalledWith("/api/billing/family/accept/", { method: "POST", json: { token: "tok123" } });
  });

  it("an invite for another address says which one", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/billing/family/invites/": { ...preview, for_you: false } }) as never);
    renderPage(<FamilyInvitePage />, { route: "/family/tok123", path: "/family/:token" });
    expect(await screen.findByText(/This invitation was sent to ap…@home.in/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Join the family plan" })).toBeNull();
  });

  it("explains a refusal from the server", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/billing/family/invites/": preview,
      "/api/billing/family/accept/": () => { throw new ApiError(409, { code: "family_full" }); },
    }) as never);
    renderPage(<FamilyInvitePage />, { route: "/family/tok123", path: "/family/:token" });
    fireEvent.click(await screen.findByRole("button", { name: "Join the family plan" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Every place in this family plan is taken."));
  });

  it("a dead link is invalid", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/billing/family/invites/": () => { throw new ApiError(404, { code: "invite_invalid" }); } }) as never);
    renderPage(<FamilyInvitePage />, { route: "/family/nope", path: "/family/:token" });
    expect(await screen.findByText(/This invitation link isn't valid/)).toBeInTheDocument();
  });
});
