import { fireEvent, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { renderPage } from "@/test/render";

import PathsPage from "./Paths";

vi.mock("@/lib/api", async (orig) => {
  const real = await orig<typeof import("@/lib/api")>();
  return {
    ...real,
    api: vi.fn(async (path: string, init?: { method?: string }) => {
      if (path.endsWith("/join/") && init?.method === "POST") throw new real.ApiError(500, null);
      if (path === "/api/paths/curated/ai/") return { slug: "ai", title: "AI for everyone", description: "d", emoji: "🤖", level: "beginner", steps_n: 1, joined: false, steps: [{ index: 0, title: "Step", goal: "g", course: null }] };
      return [];
    }),
  };
});

it("a failed join shows an error instead of an unhandled rejection", async () => {
  renderPage(<PathsPage />, { route: "/paths/ai", path: "/paths/:slug" });
  fireEvent.click(await screen.findByRole("button", { name: /Join this path/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong");
});
