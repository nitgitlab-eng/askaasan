import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Session } from "@/lib/workshops";

import { StageRail, StageStrip } from "./StageRail";

const stage = (key: string, title: string, kind: Session["stages"][number]["kind"] = "teach", done = 0, total = 2) => ({
  key, kind, title, minutes: 5, steps: [],
  concepts: Array.from({ length: total }, (_, i) => ({ text: `${key}${i}`, done: i < done })),
});
const session = (stage_index: number): Session =>
  ({
    id: 1, stage_index,
    stages: [stage("a", "Basics"), stage("b", "Tools and loops", "teach", 1, 2), stage("c", "Build", "agent_build"), stage("d", "Final", "assessment", 0, 0)],
  }) as unknown as Session;

describe("stage rail (desktop)", () => {
  it("shows done, current and upcoming stages distinctly, following stage_index", () => {
    render(<StageRail session={session(1)} />);
    const rail = screen.getByTestId("stage-rail");
    const items = within(rail).getAllByRole("listitem");
    expect(items.map((li) => li.dataset.state)).toEqual(["done", "current", "upcoming", "upcoming"]);
    // done: a green tick
    expect(within(items[0]).getByLabelText("Done")).toBeInTheDocument();
    // current: marked as the step, with the Now tag
    expect(items[1]).toHaveAttribute("aria-current", "step");
    expect(items[1]).toHaveTextContent(/now/i);
    expect(items[1].className).toMatch(/font-bold/);
    // upcoming: numbered, locked, not clickable
    expect(items[2]).toHaveAttribute("aria-disabled", "true");
    expect(items[2]).toHaveTextContent("3");
    expect(within(items[2]).getByLabelText(/opens when you get here/i)).toBeInTheDocument();
    expect(within(items[2]).queryByRole("button")).toBeNull();
    expect(within(items[3]).queryByRole("button")).toBeNull();
  });

  it("is a solid sticky card with its own scroll and a progress bar", () => {
    render(<StageRail session={session(1)} />);
    const rail = screen.getByTestId("stage-rail");
    expect(rail.className).toMatch(/\bsticky\b/);
    expect(rail.className).toMatch(/overflow-y-auto/);
    expect(rail.className).toMatch(/border-2/);
    expect(rail).toHaveTextContent("Stage 2 of 4 · 38%"); // 1 stage + half of the current one, of 4
    expect(within(rail).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "38");
  });

  it("the current stage can scroll to the Now card; nothing else is a control", () => {
    const onCurrent = vi.fn();
    render(<StageRail session={session(2)} onCurrent={onCurrent} />);
    const buttons = within(screen.getByTestId("stage-rail")).getAllByRole("button");
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]);
    expect(onCurrent).toHaveBeenCalled();
  });
});

describe("stage strip (phones)", () => {
  it("pins the current stage and progress, and opens the full plan on tap", () => {
    const { rerender } = render(<StageStrip session={session(1)} />);
    const strip = screen.getByTestId("stage-strip");
    expect(strip.className).toMatch(/\bsticky\b/);
    expect(strip.className).toMatch(/lg:hidden/);
    expect(strip).toHaveTextContent("Tools and loops");
    expect(strip).toHaveTextContent("Stage 2 of 4 · 38%");
    expect(within(strip).getByRole("progressbar")).toBeInTheDocument();
    expect(within(strip).queryByRole("list")).toBeNull();

    const toggle = within(strip).getByRole("button", { expanded: false });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const items = within(within(strip).getByRole("list")).getAllByRole("listitem");
    expect(items.map((li) => li.dataset.state)).toEqual(["done", "current", "upcoming", "upcoming"]);

    // moving on folds the plan away again, and the strip follows the server's stage
    rerender(<StageStrip session={session(2)} />);
    expect(within(strip).queryByRole("list")).toBeNull();
    expect(strip).toHaveTextContent("Build");
    expect(strip).toHaveTextContent("Stage 3 of 4");
  });
});

describe("stage rail contrast (M5 polish)", () => {
  it("never fades stage text with opacity (muted text at 80% fell below 4.5:1)", () => {
    render(<StageRail session={session(1)} />);
    const rail = screen.getByTestId("stage-rail");
    expect(rail.querySelectorAll('[class*="opacity-"]')).toHaveLength(0);
    expect(rail.querySelectorAll('[class*="text-muted/"]')).toHaveLength(0);
  });
});
