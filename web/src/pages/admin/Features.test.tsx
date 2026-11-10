import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { canSee } from "@/lib/admin";
import { api } from "@/lib/api";
import { apiRoutes, renderPage } from "@/test/render";

import AdminFeatures from "./Features";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

describe("admin lesson media switches", () => {
  it("shows the three switches, all off, and saves a change", async () => {
    let state = { podcast: false, explainer: false, listen: false, updated_at: null, updated_by: null };
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/admin/features/": (init?: { method?: string; json?: unknown }) => {
        if (init?.method === "PATCH") state = { ...state, ...(init.json as object) };
        return state;
      },
    }) as never);
    renderPage(<AdminFeatures />);
    const podcast = await screen.findByRole("switch", { name: "Lesson podcast" });
    expect(podcast).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("switch", { name: "Explainer video" })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("switch", { name: "Listen to this lesson" })).toHaveAttribute("aria-checked", "false");
    fireEvent.click(podcast);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/admin/features/", { method: "PATCH", json: { podcast: true } }));
    await waitFor(() => expect(screen.getByRole("switch", { name: "Lesson podcast" })).toHaveAttribute("aria-checked", "true"));
  });

  it("is a content (and superadmin) section", () => {
    expect(canSee(["content"], "features")).toBe(true);
    expect(canSee(["finance"], "features")).toBe(false);
    expect(canSee(["superadmin"], "features")).toBe(true);
  });
});
