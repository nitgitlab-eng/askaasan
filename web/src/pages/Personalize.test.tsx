import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { renderPage } from "@/test/render";

import PersonalizePage from "./Personalize";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn(async () => null) }));

const mascot = { character: "kili", color: "#0ea5e9", name: "Kili", accessories: [], outfit: "none", position: "bottom-right", chattiness: 2, enabled: true };
vi.mock("@/lib/useMe", async (orig) => ({
  ...(await orig<typeof import("@/lib/useMe")>()),
  useMe: () => ({
    data: {
      profile: { language: "en" },
      preferences: {
        mascot,
        mentor: { personality: "friendly", depth: "simple", reply_language: "auto", example_style: "everyday" },
        appearance: { theme: "light", accent: "#f97316", font: "default", reduced_motion: false },
        learning: {},
        notifications: {},
      },
    },
  }),
}));

describe("Personalize theme", () => {
  it('offers "Follow my device" and saves it as theme=system', async () => {
    vi.mocked(api).mockClear();
    renderPage(<PersonalizePage />);
    fireEvent.click(screen.getByRole("radio", { name: "Follow my device" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/users/preferences/", expect.objectContaining({ method: "PATCH", json: { appearance: { theme: "system" } } })));
  });
});

describe("Personalize companion switch (R11)", () => {
  it("keeps a custom colour when switching companion", async () => {
    renderPage(<PersonalizePage />);
    fireEvent.click(screen.getByRole("radio", { name: /Mayil/ }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/users/preferences/", expect.objectContaining({ method: "PATCH" })));
    const patch = vi.mocked(api).mock.calls.find((c) => c[0] === "/api/users/preferences/")![1] as { json: { mascot: { character: string; color: string } } };
    expect(patch.json.mascot).toMatchObject({ character: "mayil", color: "#0ea5e9" });
  });
});
