import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/stores/auth";
import { renderPage } from "@/test/render";

import LeaderboardPage from "./Leaderboard";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

const row = (rank: number, name: string, xp: number, me = false) => ({ rank, name, xp, me, league: { name: "bronze", icon: "🥉" } });
const scopes = [
  { scope: "global", name: "" },
  { scope: "org", org: "vidya", name: "Vidya" },
  { scope: "class", org: "vidya", class: 7, name: "8A" },
];
const board = (rows: ReturnType<typeof row>[], extra: object = {}) => ({ ends_in_days: 3, rows, me: { xp: 50, league: { name: "bronze", icon: "🥉" } }, my_rank: 2, scopes, ...extra });

function route(fn: (path: string) => unknown) {
  vi.mocked(api).mockImplementation((async (path: string) => {
    if (path === "/api/game/status/") return { show_on_leaderboard: true };
    return fn(path);
  }) as never);
}

describe("Leaderboard scopes", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
    useAuth.setState({ access: "tok", signedIn: true });
  });

  it("no tabs when only the global board exists", async () => {
    route(() => board([row(1, "Arun", 300)], { scopes: [{ scope: "global", name: "" }] }));
    renderPage(<LeaderboardPage />);
    expect(await screen.findByText("Arun")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });

  it("switches to the class board", async () => {
    route((path) => (path.includes("scope=class") ? board([row(1, "Kavya", 120, true)], { my_rank: 1 }) : board([row(1, "Ravi", 900), row(2, "Kavya", 120, true)])));
    renderPage(<LeaderboardPage />);
    expect(await screen.findByText("Ravi")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Everyone" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: "Class: 8A" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/game/leaderboard/?scope=class&class=7"));
    expect(await screen.findByRole("tab", { name: "Class: 8A" })).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(screen.queryByText("Ravi")).not.toBeInTheDocument());
  });

  it("reads the scope from the URL and shows my rank when I'm below the top rows", async () => {
    route((path) => (path.includes("scope=org") ? board([row(1, "Arun", 300)], { my_rank: 14 }) : board([])));
    renderPage(<LeaderboardPage />, { route: "/leaderboard?scope=org&org=vidya" });
    expect(await screen.findByText("You're #14 here this week")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith("/api/game/leaderboard/?scope=org&org=vidya");
    expect(screen.getByRole("tab", { name: "Vidya" })).toHaveAttribute("aria-selected", "true");
  });

  it("a board I can't open says so and keeps the tabs", async () => {
    route((path) => {
      if (path.includes("scope=class")) throw new ApiError(404, { code: "not_found" });
      return board([row(1, "Arun", 300)]);
    });
    renderPage(<LeaderboardPage />, { route: "/leaderboard?scope=class&class=99" });
    expect(await screen.findByText("This leaderboard isn't available to you.")).toBeInTheDocument();
    expect(await screen.findByRole("tab", { name: "Everyone" })).toBeInTheDocument();
  });
});
