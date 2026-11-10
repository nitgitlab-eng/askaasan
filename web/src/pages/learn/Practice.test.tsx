import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderPage } from "@/test/render";

import PracticePage from "./Practice";

vi.mock("@/lib/api", async (orig) => {
  const real = await orig<typeof import("@/lib/api")>();
  return {
    ...real,
    api: vi.fn(async (_path: string, init?: { method?: string }) => {
      if (init?.method === "POST") throw new real.ApiError(429, { code: "practice_budget_exceeded" });
      return { status: "empty", title: "Loops", activities: [] };
    }),
  };
});

describe("Practice daily limit", () => {
  it("explains the daily limit instead of spinning forever", async () => {
    renderPage(<PracticePage />, { route: "/learn/1/lesson/9/practice", path: "/learn/:courseId/lesson/:lessonId/practice" });
    expect(await screen.findByRole("alert")).toHaveTextContent("today's practice limit");
    expect(screen.queryByText(/writing fresh practice/)).toBeNull();
  });
});
