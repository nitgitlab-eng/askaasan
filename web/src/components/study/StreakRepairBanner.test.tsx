import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/stores/auth";
import { apiRoutes, renderPage } from "@/test/render";

import { StreakRepairBanner } from "./StreakRepairBanner";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));
vi.mock("canvas-confetti", () => ({ default: vi.fn() }));

const offer = {
  last_streak: 9,
  broken_at: "2026-10-22",
  expires_on: "2026-10-29",
  price: 300,
  revive_goal: 3,
  revive_progress: 1,
  revive_ends_at: "2026-10-25T10:00:00Z",
  revive_open: true,
  coins_ok: true,
};
const status = (over: object = {}) => ({ xp: 0, coins: 500, streak: 0, repair: offer, ...over });
const me = { preferences: { appearance: { reduced_motion: true } } };

describe("StreakRepairBanner", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
    useAuth.setState({ access: "tok", signedIn: true });
  });

  it("renders nothing without an offer", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/game/status/": status({ repair: null }), "/api/users/me/": me }) as never);
    const { container } = renderPage(<StreakRepairBanner />);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/game/status/"));
    expect(container.textContent).toBe("");
  });

  it("shows the revival progress and repairs for coins", async () => {
    vi.mocked(api).mockImplementation(
      apiRoutes({
        "/api/game/status/": status(),
        "/api/users/me/": me,
        "/api/game/streak/repair/": { repaired: { streak: 9, how: "coins", badges: [] }, status: status({ repair: null, streak: 9, coins: 200 }) },
      }) as never,
    );
    renderPage(<StreakRepairBanner />, { route: "/achievements?repair=1" });
    expect(await screen.findByText("Your 9-day streak broke. Bring it back!")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "1 of 3 done" })).toHaveAttribute("aria-valuenow", "1");
    expect(screen.getByRole("link", { name: "Start a lesson" })).toHaveAttribute("href", "/learn");
    fireEvent.click(screen.getByRole("button", { name: "Repair for 300 coins" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/game/streak/repair/", { method: "POST", json: { how: "coins" } }));
    await waitFor(() => expect(screen.queryByText(/streak broke/)).not.toBeInTheDocument());
  });

  it("disables paying without enough coins and hides it when the school turned the shop off", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/game/status/": status({ coins: 120 }), "/api/users/me/": me }) as never);
    const first = renderPage(<StreakRepairBanner />);
    expect(await screen.findByRole("button", { name: "Repair for 300 coins" })).toBeDisabled();
    expect(screen.getByText("You have 120 coins.")).toBeInTheDocument();
    first.unmount();
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/game/status/": status({ repair: { ...offer, coins_ok: false } }), "/api/users/me/": me }) as never);
    renderPage(<StreakRepairBanner />);
    await screen.findByText(/streak broke/);
    expect(screen.queryByRole("button", { name: /Repair for/ })).not.toBeInTheDocument();
  });

  it("explains a refused payment", async () => {
    vi.mocked(api).mockImplementation(
      apiRoutes({
        "/api/game/status/": status(),
        "/api/users/me/": me,
        "/api/game/streak/repair/": () => {
          throw new ApiError(402, { code: "not_enough_coins" });
        },
      }) as never,
    );
    renderPage(<StreakRepairBanner />);
    fireEvent.click(await screen.findByRole("button", { name: "Repair for 300 coins" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Not enough coins yet");
  });
});
