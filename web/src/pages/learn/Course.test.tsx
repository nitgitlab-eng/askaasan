import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";
import { apiRoutes, renderPage } from "@/test/render";

import CoursePage from "./Course";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

describe("Course page with a bad URL (R21, R24)", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
    vi.mocked(api).mockResolvedValue(null as never);
  });

  it("/learn/abc shows not-found and never calls /curriculums/NaN/", async () => {
    renderPage(<CoursePage />, { route: "/learn/abc", path: "/learn/:id" });
    expect(await screen.findByText(/couldn't find that page/)).toBeInTheDocument();
    expect(vi.mocked(api).mock.calls.some((c) => String(c[0]).includes("NaN"))).toBe(false);
  });

  it("a missing course shows not-found instead of loading forever", async () => {
    vi.mocked(api).mockImplementation((async (path: string) => {
      if (path === "/api/learn/curriculums/999/") throw new ApiError(404, { detail: "Not found." });
      return null;
    }) as never);
    renderPage(<CoursePage />, { route: "/learn/999", path: "/learn/:id" });
    expect(await screen.findByText(/couldn't find that page/)).toBeInTheDocument();
  });
});

const lesson = (id: number, title: string, state: string, locked: boolean, extra = {}) => ({
  id, title, objective: `Learn ${title}`, lesson_status: "ready", state, score: state === "completed" ? 1 : null, locked,
  skills: ["prompts"], activity_count: 3, activity_types: ["quiz"], minutes: 8, ...extra,
});
const ready = {
  id: 7, title: "AI Basics", goal: "AI", description: "", level: "beginner", language: "en", skills: ["prompts"], status: "ready", error: "",
  progress: { done: 1, total: 3 }, kind: "personal", is_owner: false,
  sections: [
    { id: 1, title: "Getting started", summary: "The basics", subsections: [lesson(11, "What is AI", "completed", false), lesson(12, "Prompts", "not_started", false)] },
    { id: 2, title: "Going further", summary: "", subsections: [lesson(21, "Agents", "not_started", true)] },
  ],
};

describe("Course map", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/learn/curriculums/7/": ready }) as never);
  });

  it("opens on the section you're in, with done, current and locked lessons", async () => {
    renderPage(<CoursePage />, { route: "/learn/7", path: "/learn/:id" });
    const done = await screen.findByRole("link", { name: "What is AI" });
    expect(done).toHaveAttribute("href", "/learn/7/lesson/11");
    expect(done).toHaveTextContent("100%");
    expect(screen.getByRole("link", { name: "Prompts" })).toHaveTextContent("Start");
    expect(screen.getAllByRole("link", { name: /Continue learning/ })[0]).toHaveAttribute("href", "/learn/7/lesson/12");
    expect(screen.queryByText("Agents")).not.toBeInTheDocument(); // other sections stay off the map until picked
  });

  it("picking another section shows its lessons, locked ones without a link", async () => {
    renderPage(<CoursePage />, { route: "/learn/7", path: "/learn/:id" });
    await screen.findByRole("link", { name: "What is AI" });
    screen.getAllByRole("button", { name: "Next section" })[0].click();
    expect(await screen.findByText("Agents")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Agents" })).not.toBeInTheDocument();
    expect(screen.getByText("Agents").closest("[aria-disabled]")).not.toBeNull();
  });

  it("switches to the classic path, saves the choice, and keeps the tracking panels", async () => {
    const patch = vi.fn(() => ({}));
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/learn/curriculums/7/": ready, "/api/users/preferences/": patch }) as never);
    renderPage(<CoursePage />, { route: "/learn/7", path: "/learn/:id" });
    await screen.findByRole("link", { name: "What is AI" });
    expect(screen.getByRole("radio", { name: /Map/ })).toHaveAttribute("aria-checked", "true");

    fireEvent.click(screen.getByRole("radio", { name: /Path/ }));
    expect(screen.getByRole("radio", { name: /Path/ })).toHaveAttribute("aria-checked", "true");
    await waitFor(() => expect(patch).toHaveBeenCalledWith({ method: "PATCH", json: { learning: { course_view: "path" } } }));
    // Every section is on the path at once, locked lessons without a link.
    expect(screen.getByRole("heading", { name: "Going further" })).toBeInTheDocument();
    expect(screen.getByText("Agents").closest("[aria-disabled]")).not.toBeNull();
    expect(screen.getByRole("link", { name: "What is AI" })).toHaveTextContent("100%");
    // The timeline and the up next / scores / skills panels stay in both views.
    expect(screen.getByRole("group", { name: "Course timeline" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Up next" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Scores" })).toBeInTheDocument();
    expect(screen.getByText("100%", { selector: "span.font-display" })).toBeInTheDocument(); // average score

    fireEvent.click(screen.getByRole("radio", { name: /Map/ }));
    expect(screen.queryByRole("heading", { name: "Going further" })).not.toBeInTheDocument();
  });
});
