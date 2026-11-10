import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { useAuth } from "@/stores/auth";
import { apiRoutes, renderPage } from "@/test/render";

import AdminFamilyGroups from "./FamilyGroups";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

const groups = { results: [{ id: 1, owner: "amma@home.in", plan: "Family Plus", active_until: "2026-11-20", max_members: 4, members_count: 2, members: ["appa@home.in"], pending_invites: 1, created_at: "2026-10-01" }], count: 1, page: 1, pages: 1, groups: 1, members: 2 };
const gifts = { results: [{ id: 1, order_id: 9, buyer: "magan@home.in", recipient: "paati@home.in", plan: "Plus", amount_paise: 149900, mode: "live", status: "claimed", code_last4: "AB12", expires_at: "2027-10-01", created_at: "2026-10-01", sent_at: "2026-10-01", claimed_at: "2026-10-03" }], count: 1, page: 1, pages: 1 };
const me = (roles: string[]) => ({ id: 1, email: "s@aasan.in", is_staff: true, staff_roles: roles, profile: { display_name: "", language: "en" }, preferences: { appearance: {}, mascot: {}, learning: {} }, consent: {} });

describe("Admin families & gifts", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
    useAuth.setState({ access: "token", signedIn: true });
  });
  afterEach(() => { useAuth.setState({ access: null, signedIn: false }); });

  it("finance sees groups and gifts", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/users/me/": me(["finance"]), "/api/admin/family-groups/": groups, "/api/admin/gifts/": gifts }) as never);
    renderPage(<AdminFamilyGroups />);
    expect(await screen.findByText("amma@home.in")).toBeInTheDocument();
    expect(screen.getByText("appa@home.in")).toBeInTheDocument();
    expect(screen.getByText("Family groups: 1 · People in families: 2")).toBeInTheDocument();
    expect(await screen.findByText("paati@home.in")).toBeInTheDocument();
    expect(screen.getByText("Redeemed")).toBeInTheDocument();
    expect(screen.getByText("…AB12")).toBeInTheDocument();
  });

  it("support sees groups but never asks for gifts", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/users/me/": me(["support"]), "/api/admin/family-groups/": groups }) as never);
    renderPage(<AdminFamilyGroups />);
    expect(await screen.findByText("amma@home.in")).toBeInTheDocument();
    expect(screen.queryByText("Gifted plans")).toBeNull();
    expect(vi.mocked(api).mock.calls.some(([p]) => String(p).startsWith("/api/admin/gifts/"))).toBe(false);
  });
});
