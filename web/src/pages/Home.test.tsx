import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { apiRoutes, renderPage } from "@/test/render";

import HomePage from "./Home";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

const routes = (streak: number) =>
  apiRoutes({
    "/api/game/status/": { streak, owned_items: [] },
    "/api/assistant/conversations/": [],
    "/api/learn/continue/": null,
    "/api/review/overview/": { due: 0 },
    "/api/orgs/": [],
    "/api/": null,
  });

describe("Home streak card (R18)", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
  });

  it("shows the real streak from the game status, not a hard-coded 0", async () => {
    vi.mocked(api).mockImplementation(routes(4) as never);
    renderPage(<HomePage />);
    expect(await screen.findByText("4 days")).toBeInTheDocument();
  });

  it("uses the singular for a 1-day streak (R15)", async () => {
    vi.mocked(api).mockImplementation(routes(1) as never);
    renderPage(<HomePage />);
    expect(await screen.findByText("1 day")).toBeInTheDocument();
  });
});
