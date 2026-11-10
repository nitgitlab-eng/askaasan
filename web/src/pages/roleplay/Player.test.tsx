import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderPage } from "@/test/render";

import RolePlayPlayer from "./Player";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn(async () => null) }));

const scenario = { id: 1, source: "library", emoji: "🛒", title: "Shop", summary: "", learner_role: "customer", character: { name: "Ravi", persona: "" }, setting: "", objectives: [], competencies: [], difficulty: "easy", max_turns: 8 };
const socket = { messages: [{ id: 1, role: "assistant", content: "Hello, **welcome** to the shop!" }], send: vi.fn(), cancel: vi.fn(), busy: false, ready: true, error: null, turnsLeft: 8 };

vi.mock("@/lib/roleplay", async (orig) => ({
  ...(await orig<typeof import("@/lib/roleplay")>()),
  roleplay: { session: vi.fn(async () => ({ id: 5, status: "active", language: "en", scenario, turns: [] })) },
  useRolePlaySocket: () => socket,
}));

describe("Role-play player", () => {
  it("renders the character's Markdown instead of raw ** (R12)", async () => {
    renderPage(<RolePlayPlayer />, { route: "/roleplay/5", path: "/roleplay/:id" });
    const strong = await screen.findAllByText("welcome", { selector: "strong" });
    expect(strong.length).toBeGreaterThan(0);
    expect(screen.queryByText(/\*\*welcome\*\*/)).toBeNull();
  });

  it("explains why Finish is disabled before 2 replies (R13)", async () => {
    renderPage(<RolePlayPlayer />, { route: "/roleplay/5", path: "/roleplay/:id" });
    const finish = await screen.findByRole("button", { name: /Finish/ });
    expect(finish).toBeDisabled();
    expect(finish).toHaveAccessibleDescription(/at least 2 replies/);
  });

  it("a bad session id shows not-found instead of Loading forever (R21)", async () => {
    renderPage(<RolePlayPlayer />, { route: "/roleplay/abc", path: "/roleplay/:id" });
    expect(await screen.findByText(/couldn't find that page/)).toBeInTheDocument();
  });
});
