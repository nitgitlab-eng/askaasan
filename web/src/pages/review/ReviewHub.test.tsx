import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderPage } from "@/test/render";

import ReviewHub from "./ReviewHub";

vi.mock("@/lib/api", async (orig) => {
  const real = await orig<typeof import("@/lib/api")>();
  return {
    ...real,
    api: vi.fn(async (path: string) => {
      if (path.startsWith("/api/review/session/")) throw new real.ApiError(404, { detail: "Not found." });
      if (path === "/api/review/overview/") return { due: 0, total: 0, reviewed_today: 0, by_course: [], next_due_at: null };
      return null;
    }),
  };
});

describe("Review hub errors (R21)", () => {
  it("a checkpoint for a bad section shows an error instead of spinning forever", async () => {
    renderPage(<ReviewHub />, { route: "/review?mode=section&section=999", path: "/review" });
    expect(await screen.findByRole("alert")).toHaveTextContent(/Something went wrong/);
  });
});
