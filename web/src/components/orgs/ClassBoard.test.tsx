import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { renderPage } from "@/test/render";

import { ClassBoardToggle } from "./ClassBoard";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

const data = (over: object = {}) => ({
  class: { id: 4, name: "8A" },
  week_start: "2026-10-19",
  week_end: "2026-10-25",
  enabled: true,
  members: 3,
  hidden: 1,
  rows: [
    { rank: 1, user_id: 1, name: "Arun Kumar", xp: 320 },
    { rank: 2, user_id: 2, name: "Kavya R", xp: 120 },
  ],
  ...over,
});

describe("Cockpit class board", () => {
  beforeEach(() => vi.mocked(api).mockReset());

  it("loads only when opened and lists the week's top learners", async () => {
    vi.mocked(api).mockResolvedValue(data() as never);
    renderPage(<ClassBoardToggle slug="vidya" id={4} />);
    expect(api).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /This week's top learners/ }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/orgs/vidya/groups/4/board/"));
    expect(await screen.findByText("Arun Kumar")).toBeInTheDocument();
    expect(screen.getByText("320 XP")).toBeInTheDocument();
    expect(screen.getByText("1 learner chose not to appear on leaderboards.")).toBeInTheDocument();
  });

  it("empty week and boards switched off", async () => {
    vi.mocked(api).mockResolvedValue(data({ rows: [], hidden: 0, enabled: false }) as never);
    renderPage(<ClassBoardToggle slug="vidya" id={4} />);
    fireEvent.click(screen.getByRole("button", { name: /This week's top learners/ }));
    expect(await screen.findByText("No XP earned in this class yet this week.")).toBeInTheDocument();
    expect(screen.getByText(/switched off for learners/)).toBeInTheDocument();
  });
});
