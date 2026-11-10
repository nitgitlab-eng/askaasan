import { describe, expect, it } from "vitest";

import { planPct } from "./careerPlan";
import { byDay, dayLabel, draftToInput, phaseIndex, splitItems, type LearnerItem } from "./journeys";

const item = (id: number, day: number, extra: Partial<LearnerItem> = {}): LearnerItem => ({
  id, day, order: 0, kind: "note", title: `i${id}`, notes: "", course: null, lesson: null, scenario: null, document: null,
  colleague_name: "", colleague_role: "", link: "", due_date: "2026-10-17", done: false, overdue: false, auto: false, ...extra,
});

describe("journey helpers", () => {
  it("splits items into today, upcoming and past with overdue first", () => {
    const items = [item(1, 1, { done: true }), item(2, 2, { overdue: true }), item(3, 3), item(4, 5), item(5, 1, { overdue: true })];
    const { today, upcoming, past } = splitItems(items, 3);
    expect(today.map((i) => i.id)).toEqual([3]);
    expect(upcoming.map((i) => i.id)).toEqual([4]);
    expect(past.map((i) => i.id)).toEqual([2, 5, 1]);
  });

  it("groups by day in order and finds phases", () => {
    expect(byDay([{ day: 3 }, { day: 1 }, { day: 3 }]).map(([d, r]) => [d, r.length])).toEqual([[1, 1], [3, 2]]);
    const phases = [{ title: "A", start_day: 1, end_day: 7 }, { title: "B", start_day: 8, end_day: 30 }];
    expect(phaseIndex(phases, 7)).toBe(0);
    expect(phaseIndex(phases, 8)).toBe(1);
    expect(phaseIndex(phases, 31)).toBeNull();
  });

  it("labels the day and keeps only item fields from a draft", () => {
    const t = (k: string, o?: Record<string, unknown>) => `${k}:${JSON.stringify(o ?? {})}`;
    const status = { day: 3, length_days: 30, started: true, ended: false, done: 0, total: 1, overdue: 0, finished: false, stuck: false, phase: 0, phases: [] };
    expect(dayLabel(t, { status, start_date: "2026-10-15" }, "en")).toBe('jr.dayOf:{"day":3,"n":30}');
    expect(dayLabel(t, { status: { ...status, finished: true }, start_date: "2026-10-15" }, "en")).toContain("jr.finished");
    expect(dayLabel(t, { status: { ...status, started: false, day: -1 }, start_date: "2026-10-20" }, "en")).toContain("jr.startsOn");
    const d = draftToInput({ key: 1, day: 2, kind: "shadow", title: "Sit in", notes: "", curriculum_id: null, scenario_id: null, document_id: null, colleague_role: "a lead", ref_title: "x" });
    expect(d).not.toHaveProperty("key");
    expect(d).not.toHaveProperty("ref_title");
    expect(d.colleague_role).toBe("a lead");
  });

  it("computes plan progress", () => {
    expect(planPct({ done: 0, total: 0 })).toBe(0);
    expect(planPct({ done: 3, total: 12 })).toBe(25);
  });
});
