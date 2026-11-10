import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderPage } from "@/test/render";

import LessonPage from "./Lesson";

const lesson = {
  id: 9, title: "Reading only", objective: "Read", lesson_status: "ready", error: "", explanation_md: "Just read this.", key_points: ["Point A"],
  activities: [], state: "in_progress", curriculum: { id: 1, title: "Course", language: "en" }, section: { id: 2, title: "S" },
};

vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  api: vi.fn(async (path: string) => {
    if (path.startsWith("/api/learn/subsections/9/start/") || path === "/api/learn/subsections/9/") return lesson;
    if (path === "/api/learn/subsections/9/complete/") return { score: null, answered: 0, total: 0, correct: 0, key_points: ["Point A"], next_subsection_id: null };
    throw new Error(`unmocked ${path}`);
  }),
}));

const send = vi.fn(() => true);
vi.mock("@/lib/useMentorSocket", () => ({
  useMentorSocket: () => ({ status: "ready", messages: [], setMessages: () => {}, busy: false, error: null, send, cancel: () => {} }),
}));

describe("Ask Aasan about this (R29)", () => {
  it("opens an inline chat inside the lesson instead of leaving for /mentor", async () => {
    renderPage(<LessonPage />, { route: "/learn/1/lesson/9", path: "/learn/:courseId/lesson/:lessonId" });
    fireEvent.click(await screen.findByRole("button", { name: "Ask Aasan about this" }));
    expect(await screen.findByRole("region", { name: "Ask Aasan about this" })).toBeInTheDocument();
    expect(screen.getByText("Just read this.")).toBeInTheDocument(); // still on the lesson
    expect(send).toHaveBeenCalledWith(expect.stringContaining("Reading only"));
  });
});

describe("Lesson recap for a reading-only lesson", () => {
  it("shows no percentage or score line when the score is null", async () => {
    const { container } = renderPage(<LessonPage />, { route: "/learn/1/lesson/9", path: "/learn/:courseId/lesson/:lessonId" });
    fireEvent.click(await screen.findByRole("button", { name: /Finish lesson|Finish/ }));
    expect(await screen.findByText("Point A")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/NaN|\d+%/);
    expect(screen.queryByText(/activities correct/)).toBeNull();
  });
});
