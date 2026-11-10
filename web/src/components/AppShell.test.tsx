import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { useAuth } from "@/stores/auth";
import { apiRoutes, renderPage } from "@/test/render";

import { AppShell } from "./AppShell";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn(async () => null) }));
vi.mock("@/mascot/MascotDock", () => ({ MascotDock: () => null }));

const me = (extra: object = {}) => ({
  id: 1, email: "priya@example.com", email_verified: true, is_staff: false, staff_roles: [], is_creator: false, can_author: false,
  has_password: true, consent: { required: false },
  profile: { display_name: "Priya", language: "en", onboarding_completed: true },
  preferences: { appearance: {}, learning: { daily_goal_minutes: 15 }, mascot: { name: "Kili", chattiness: 0, color: "", outfit: "", accessories: [], character: "kili", position: "right" }, mentor: {} },
  ...extra,
});

function routes(user: object | null, brand: object = { orgs: [], primary: null, disabled: [] }) {
  vi.mocked(api).mockImplementation(apiRoutes({ "/api/users/me/": user, "/api/orgs/me/brand/": brand, "/api/": null }) as never);
}

/** The desktop sidebar (the phone bottom bar is the other "Main menu"). */
const sidebar = async () => (await screen.findAllByRole("navigation", { name: "Main menu" }))[0];

describe("AppShell navigation", () => {
  beforeEach(() => {
    useAuth.setState({ access: "token", signedIn: true });
    routes(me());
  });
  afterEach(() => useAuth.setState({ access: null, signedIn: false }));

  it("shows five plain sections, each with an accessible name", async () => {
    renderPage(<AppShell />);
    const nav = await sidebar();
    const sections = [...nav.querySelectorAll("[data-tour^=section-]")].map((a) => a.getAttribute("aria-label"));
    expect(sections).toEqual(["Home", "Learn", "Practice", "Progress", "Certificates"]);
    for (const a of within(nav).getAllByRole("link")) expect(a).toHaveAccessibleName();
  });

  it("the section you're in unfolds its pages; another one can be peeked, one at a time", async () => {
    renderPage(<AppShell />, { route: "/catalog", path: "*" });
    const nav = await sidebar();
    expect(within(nav).getByRole("link", { name: "Catalog" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "My notes" })).toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Mastery" })).toBeNull(); // Progress stays folded
    fireEvent.click(within(nav).getByRole("button", { name: "Show Progress pages" }));
    expect(within(nav).getByRole("link", { name: "Mastery" })).toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "My notes" })).toBeNull(); // only one open at a time
    fireEvent.click(within(nav).getByRole("button", { name: "Hide Progress pages" }));
    expect(within(nav).queryByRole("link", { name: "Mastery" })).toBeNull();
  });

  it("role-only items appear only for those roles", async () => {
    routes(me({ can_author: true, is_staff: true, staff_roles: ["superadmin"] }), { orgs: [{ name: "Vidya" }], primary: null, disabled: [] });
    renderPage(<AppShell />);
    const nav = await sidebar();
    await waitFor(() => expect(within(nav).getByRole("link", { name: "Admin console" })).toBeInTheDocument());
    expect(within(nav).getByRole("link", { name: "Creator Lab" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: /My school/ })).toBeInTheDocument();
    expect(nav.querySelectorAll("[data-tour^=section-]").length + 2).toBeLessThanOrEqual(9); // + My school, Admin
  });

  it("a section whose features the school switched off disappears; a partly-off one keeps the rest", async () => {
    routes(me(), { orgs: [{ name: "Vidya" }], primary: null, disabled: ["mentor", "roleplay", "live", "workshops", "leaderboard"] });
    renderPage(<AppShell />, { route: "/progress", path: "*" });
    const nav = await sidebar();
    await waitFor(() => expect(within(nav).queryByRole("link", { name: "Practice" })).toBeNull());
    const tabs = await screen.findByRole("navigation", { name: "Progress pages" });
    expect(within(tabs).queryByRole("link", { name: "Leaderboard" })).toBeNull();
    expect(within(tabs).getByRole("link", { name: "Mastery" })).toBeInTheDocument();
  });

  it("nested pages open their section at the right page (sidebar, and the tab row phones use)", async () => {
    renderPage(<AppShell />, { route: "/mastery/3", path: "*" });
    const nav = await sidebar();
    expect(within(nav).getByRole("link", { name: "Mastery" })).toHaveAttribute("aria-current", "page");
    const tabs = await screen.findByRole("navigation", { name: "Progress pages" });
    expect(within(tabs).getByRole("link", { name: "Mastery" })).toHaveAttribute("aria-current", "page");
  });

  it("the You menu holds account, plans, help and log out, and closes with Escape", async () => {
    renderPage(<AppShell />);
    const [you] = await screen.findAllByRole("button", { name: "You" });
    fireEvent.click(you);
    const menu = await screen.findByRole("menu", { name: "You" });
    for (const name of ["Account", "Personalize", "Plans", "Help", "Log out"]) expect(within(menu).getByRole("menuitem", { name: new RegExp(name) })).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: /Create an organisation/ })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
  });
});
