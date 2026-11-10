import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderPage } from "@/test/render";

import { GameBar } from "./GameBar";

const navigate = vi.fn();
vi.mock("react-router-dom", async (orig) => ({ ...(await orig<typeof import("react-router-dom")>()), useNavigate: () => navigate }));
vi.mock("@/lib/api", async (orig) => {
  const real = await orig<typeof import("@/lib/api")>();
  const { apiRoutes: routes } = await import("@/test/render");
  return {
    ...real,
    api: vi.fn(routes({
      "/api/game/notifications/read/": { ok: true },
      "/api/game/notifications/": [
        { id: 1, kind: "workshop_announce", title: "New workshop: Prompt Engineering", body: "Sat 1 Nov, 3:30 pm", link: "/workshops/4", read: false },
        { id: 2, kind: "badge", title: "New badge", body: "", link: "", read: false },
      ],
      "/api/game/status/": { streak: 1, coins: 0, level: 1, xp: 0, level_floor: 0, level_next: 10, today_xp: 0, daily_goal_xp: 10, unread: 2 },
    })),
  };
});

describe("notification bell", () => {
  it("marks workshop notifications with an icon and opens the run", async () => {
    const { container } = renderPage(<GameBar />);
    fireEvent.click(screen.getByRole("button", { name: /notifications/i }));
    const item = await screen.findByRole("button", { name: /new workshop: prompt engineering/i });
    expect(item.querySelector("svg.lucide-presentation")).not.toBeNull();
    expect(within(container).getByRole("button", { name: /new badge/i }).querySelector("svg")).toBeNull();
    fireEvent.click(item);
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/workshops/4"));
  });
});
