import { describe, expect, it } from "vitest";

import { columnsFor, elbow, layoutMap } from "./mapLayout";

describe("course map layout", () => {
  it("picks fewer columns on narrow screens", () => {
    expect([columnsFor(360), columnsFor(600), columnsFor(1000)]).toEqual([1, 2, 3]);
  });

  it("stacks cards in one column on a phone, joined by straight lines", () => {
    const m = layoutMap(3, 340);
    expect(m.cols).toBe(1);
    expect(m.cards.map((c) => c.x)).toEqual([0, 0, 0]);
    expect(m.links).toHaveLength(2);
    expect(m.links.every((l) => /^M [\d.]+ [\d.]+ V [\d.]+$/.test(l))).toBe(true);
  });

  it("snakes: row two runs right to left and joins row one straight down", () => {
    const m = layoutMap(6, 1000);
    const cols = m.cards.map((c) => Math.round(c.x / (m.cardW + 40)));
    expect(cols).toEqual([0, 1, 2, 2, 1, 0]);
    expect(m.links[2]).toMatch(/ V /); // card 3 → card 4 drops down
    expect(m.links[2]).not.toMatch(/Q/);
    expect(m.links[0]).toMatch(/Q/); // the staggered middle column makes an elbow
  });

  it("never uses more columns than cards", () => {
    expect(layoutMap(1, 1000).cols).toBe(1);
    expect(layoutMap(0, 1000)).toMatchObject({ height: 0, cards: [], links: [] });
  });

  it("draws a flat line when both ends are level", () => {
    expect(elbow(0, 10, 50, 10, 25)).toBe("M 0 10 H 50");
  });
});
