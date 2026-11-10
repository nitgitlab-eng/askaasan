import { fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { AuthLayout } from "@/pages/AuthLayout";
import { useAuth } from "@/stores/auth";
import { apiRoutes, renderPage } from "@/test/render";

import { AppShell } from "./AppShell";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn(async () => null) }));
vi.mock("@/mascot/MascotDock", () => ({ MascotDock: () => null }));

const FOCUSABLE = "a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex='-1'])";

/** Shared expectations: first in tab order, hidden until focused, and activating it lands focus on #main. */
async function expectSkipLink() {
  const link = await screen.findByRole("link", { name: "Skip to content" });
  expect(document.body.querySelector(FOCUSABLE)).toBe(link);
  expect(link).toHaveAttribute("href", "#main");
  expect(link.className).toContain("sr-only");
  expect(link.className).toContain("focus:not-sr-only");
  const main = document.getElementById("main");
  expect(main?.tagName).toBe("MAIN");
  expect(main).toHaveAttribute("tabindex", "-1");
  link.focus();
  expect(document.activeElement).toBe(link);
  fireEvent.click(link);
  expect(document.activeElement).toBe(main);
}

describe("skip to content", () => {
  beforeEach(() => {
    useAuth.setState({ access: "token", signedIn: true });
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/users/me/": {
        id: 1, email: "priya@example.com", email_verified: true, is_staff: false, staff_roles: [], is_creator: false, can_author: false,
        has_password: true, consent: { required: false },
        profile: { display_name: "Priya", language: "en", onboarding_completed: true },
        preferences: { appearance: {}, learning: { daily_goal_minutes: 15 }, mascot: { name: "Kili", chattiness: 0, color: "", outfit: "", accessories: [], character: "kili", position: "right" }, mentor: {} },
      },
      "/api/orgs/me/brand/": { orgs: [], primary: null, disabled: [] },
      "/api/": null,
    }) as never);
  });
  afterEach(() => useAuth.setState({ access: null, signedIn: false }));

  it("AppShell: the skip link is first, hidden until focused, and focuses #main", async () => {
    renderPage(<AppShell />);
    await expectSkipLink();
  });

  it("AuthLayout: the skip link is first, hidden until focused, and focuses #main", async () => {
    renderPage(
      <AuthLayout title="Welcome">
        <button>Sign in</button>
      </AuthLayout>,
    );
    await expectSkipLink();
  });
});
