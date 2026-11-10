import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { apiRoutes, renderPage } from "@/test/render";

import { GoalWizard } from "./GoalWizard";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

const card = (title: string, foundations = false) => ({ title, deliverable: `${title} — done`, level: "beginner", weeks: 3, foundations });
const goal = {
  id: 7,
  topic: "AI",
  about: "",
  status: "suggested",
  suggestions: [card("Build a WhatsApp helper"), card("Forecast stock"), card("Write listings"), card("Understand AI basics first", true)],
  scenario: {},
  prior: [],
  constraints: {},
  level: "beginner",
  curriculum_id: null,
  ai_left: 3,
};

describe("GoalWizard: topic → scenarios → constraints → course", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
  });

  it("suggests real uses for a bare topic and builds a course from the chosen one", async () => {
    const calls: [string, unknown][] = [];
    vi.mocked(api).mockImplementation(((path: string, init?: { json?: unknown }) => {
      calls.push([path, init?.json]);
      return apiRoutes({
        "/api/adaptive/goals/7/choose/": { ...goal, status: "chosen", scenario: goal.suggestions[0], verdict: "chosen" },
        "/api/adaptive/goals/7/constraints/": { ...goal, status: "ready" },
        "/api/adaptive/goals/": goal,
        "/api/learn/curriculums/": { id: 55 },
      })(path, init as never);
    }) as never);
    renderPage(<GoalWizard />);
    fireEvent.change(screen.getByLabelText(/What do you want to learn/), { target: { value: "AI" } });
    fireEvent.click(screen.getByRole("button", { name: /Show me ways/ }));
    expect(await screen.findByText("Build a WhatsApp helper")).toBeInTheDocument();
    expect(screen.getByText(/Foundations/)).toBeInTheDocument();

    fireEvent.click(screen.getByText("Build a WhatsApp helper"));
    expect(await screen.findByText("Your goal")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/already know/), { target: { value: "Excel, typing" } });
    fireEvent.click(screen.getByRole("button", { name: /Build my course/ }));
    await waitFor(() => expect(calls.some(([p]) => p === "/api/learn/curriculums/")).toBe(true));
    expect(calls.find(([p]) => p === "/api/adaptive/goals/7/constraints/")?.[1]).toMatchObject({ prior: ["Excel", "typing"], hours_week: 3, level: "beginner" });
    expect(calls.find(([p]) => p === "/api/learn/curriculums/")?.[1]).toEqual({ goal_id: 7 });
  });

  it("shows narrower first steps when the learner's own idea is too big", async () => {
    vi.mocked(api).mockImplementation(
      apiRoutes({
        "/api/adaptive/goals/7/choose/": { ...goal, suggestions: [card("Build a menu page"), card("Understand AI basics first", true)], verdict: "split", reason: "Start smaller." },
        "/api/adaptive/goals/": goal,
      }) as never,
    );
    renderPage(<GoalWizard />);
    fireEvent.change(screen.getByLabelText(/What do you want to learn/), { target: { value: "AI" } });
    fireEvent.click(screen.getByRole("button", { name: /Show me ways/ }));
    fireEvent.change(await screen.findByLabelText(/describe your own/), { target: { value: "build an app like Swiggy" } });
    fireEvent.click(screen.getByRole("button", { name: /Check my idea/ }));
    expect(await screen.findByRole("status")).toHaveTextContent("Start smaller.");
    expect(screen.getByText("Build a menu page")).toBeInTheDocument();
    expect(screen.queryByText("Your goal")).toBeNull();
  });
});
