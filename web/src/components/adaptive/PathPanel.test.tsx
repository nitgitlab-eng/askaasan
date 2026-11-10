import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { apiRoutes, renderPage } from "@/test/render";

import { PathPanel } from "./PathPanel";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

const sub = (id: number, title: string) => ({ id, title, objective: "" });
const path = {
  curriculum_id: 3,
  version: 2,
  changes: { practice: 1 },
  replanned_at: null,
  done: 1,
  remaining: 3,
  items: [
    { id: 1, kind: "lesson", status: "done", current: false, reason: "", subsection: sub(10, "AI around you"), concept: null },
    { id: 2, kind: "remediation", status: "pending", current: true, reason: "retry", subsection: sub(11, "Prompting"), concept: null },
    { id: 3, kind: "skip_check", status: "pending", current: false, reason: "known", subsection: sub(12, "Excel with AI"), concept: null },
    { id: 4, kind: "final", status: "pending", current: false, reason: "", subsection: null, concept: null },
  ],
};

describe("PathPanel", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(api).mockReset();
    vi.mocked(api).mockImplementation(
      apiRoutes({
        "/api/adaptive/courses/3/path/": path,
        "/api/adaptive/courses/3/skill-map/": {
          concepts: [{ key: "p", title: "Prompting", description: "", critical: true, p_known: 0.3, observations: 4, state: "weak", lessons: [11] }],
          edges: [],
          mastered: 0,
          total: 1,
          critical_mastered: 0,
          critical_total: 1,
        },
      }) as never,
    );
  });

  it("shows the next step with where it leads, and what comes after", async () => {
    renderPage(<PathPanel courseId={3} />);
    expect(await screen.findByRole("link", { name: /Practise/ })).toHaveAttribute("href", "/learn/3/lesson/11/practice");
    expect(screen.getByText(/practise, then finish/)).toBeInTheDocument();
    expect(screen.getByText("Excel with AI")).toBeInTheDocument();
    expect(screen.getByText(/1 of 4 steps done/)).toBeInTheDocument();
    expect(screen.queryByRole("status")).toBeNull(); // first visit: nothing "changed" yet
  });

  it("says what changed since the learner last looked", async () => {
    localStorage.setItem("aasan-path-v-3", "1");
    renderPage(<PathPanel courseId={3} />);
    expect(await screen.findByRole("status")).toHaveTextContent("Added 1 practice step.");
  });

  it("opens the skill map", async () => {
    renderPage(<PathPanel courseId={3} />);
    fireEvent.click(await screen.findByRole("button", { name: /skill map/ }));
    expect(await screen.findByText("Needs practice")).toBeInTheDocument();
    expect(screen.getByText(/0 of 1 goal skills mastered/)).toBeInTheDocument();
  });
});
