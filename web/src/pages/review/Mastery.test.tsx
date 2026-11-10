import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { apiRoutes, renderPage } from "@/test/render";

import MasteryPage from "./Mastery";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

describe("Mastery page (R14, R28)", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/learn/curriculums/": [], "/api/review/mastery/": { nodes: [], edges: [], skills: [] } }) as never);
  });

  it("with no course yet, never asks for /api/review/mastery/0/", async () => {
    renderPage(<MasteryPage />, { route: "/mastery", path: "/mastery" });
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/learn/curriculums/"));
    await new Promise((r) => setTimeout(r, 20));
    expect(vi.mocked(api).mock.calls.map((c) => c[0])).not.toContain("/api/review/mastery/0/");
  });

  it("explains that mastery grows with practice while the certificate shows completion", async () => {
    renderPage(<MasteryPage />, { route: "/mastery", path: "/mastery" });
    expect(await screen.findByText(/certificate shows that you completed/)).toBeInTheDocument();
  });
});
