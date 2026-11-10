import { describe, expect, it } from "vitest";

import { defaultRange, dueState, fmtDuration, points, sortAssignments, validRange } from "./teachUtils";

const now = Date.parse("2026-10-17T10:00:00Z");
const day = 86_400_000;
const iso = (ms: number) => new Date(ms).toISOString();

describe("dueState", () => {
  it("classifies done, overdue, soon, later and no due date", () => {
    expect(dueState({ due_at: iso(now - day), done: 3, total: 3 }, now)).toBe("done");
    expect(dueState({ due_at: iso(now - 1000), done: 0, total: 1 }, now)).toBe("overdue");
    expect(dueState({ due_at: iso(now + day), done: 0, total: 1 }, now)).toBe("soon");
    expect(dueState({ due_at: iso(now + 5 * day), done: 0, total: 1 }, now)).toBe("later");
    expect(dueState({ due_at: null, done: 0, total: 1 }, now)).toBe("none");
    expect(dueState({ due_at: "garbage", done: 0, total: 1 }, now)).toBe("none");
  });
});

describe("sortAssignments", () => {
  it("puts unfinished mandatory overdue work first and finished work last", () => {
    const list = [
      { id: 1, due_at: iso(now + 5 * day), done: 0, total: 1, mandatory: false },
      { id: 2, due_at: null, done: 1, total: 1, mandatory: true },
      { id: 3, due_at: iso(now + 9 * day), done: 0, total: 1, mandatory: true },
      { id: 4, due_at: iso(now - day), done: 0, total: 1, mandatory: true },
      { id: 5, due_at: iso(now + 6 * day), done: 0, total: 1, mandatory: true },
    ];
    expect(sortAssignments(list, now).map((x) => x.id)).toEqual([4, 5, 3, 1, 2]);
  });
});

describe("formatting and ranges", () => {
  it("formats durations and gain points", () => {
    expect(fmtDuration(240)).toBe("4:00");
    expect(fmtDuration(65)).toBe("1:05");
    expect(fmtDuration(null)).toBe("—");
    expect(points(0.6)).toBe("+60");
    expect(points(-0.05)).toBe("-5");
  });
  it("builds and validates the report range", () => {
    const r = defaultRange(new Date(2026, 9, 17), 90);
    expect(r).toEqual({ from: "2026-07-20", to: "2026-10-17" });
    expect(validRange(r.from, r.to)).toBe(true);
    expect(validRange("2026-10-17", "2026-01-01")).toBe(false);
    expect(validRange("2024-01-01", "2026-01-01")).toBe(false);
  });
});

describe("competency cells", () => {
  it("tones and text never rely on colour alone", async () => {
    const { cellTone, cellText } = await import("./teachUtils");
    expect(cellTone(null, 3, 3)).toBe("none");
    expect(cellTone(3, 3, 3)).toBe("pass");
    expect(cellTone(2, 3, 3)).toBe("mid");
    expect(cellTone(1, 3, 3)).toBe("low");
    expect(cellTone(0, 3, 3)).toBe("low");
    expect(cellTone(3, 5, 3)).toBe("pass");
    expect(cellTone(2, 5, 3)).toBe("low");
    expect(cellText(null, 3, false)).toBe("—");
    expect(cellText(2, 3, false)).toBe("2/3");
    expect(cellText(3, 3, true)).toBe("3/3 ✓");
  });
});
