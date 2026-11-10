import { describe, expect, it } from "vitest";

import { doneCount, latestChecks, level, needsTrack } from "./coachLogic";

describe("coachLogic", () => {
  it("clamps scores to 0–3", () => {
    expect([level(-1), level(0), level(2.4), level(7), level(undefined)]).toEqual([0, 0, 2, 3, 0]);
  });

  it("tracks only new learner turns after the reply finishes", () => {
    expect(needsTrack(1, 0, false)).toBe(true);
    expect(needsTrack(1, 0, true)).toBe(false);
    expect(needsTrack(1, 1, false)).toBe(false);
    expect(needsTrack(0, 0, false)).toBe(false);
  });

  it("counts fully met objectives", () => {
    const o = (score: number) => ({ text: "x", score, reason: "" });
    expect(doneCount({ objectives: [o(3), o(2), o(3)] })).toEqual([2, 3]);
    expect(doneCount(null)).toEqual([0, 0]);
  });

  it("shows only checks from the newest scored turn", () => {
    const check = (turn_id: number) => ({ fact: "f", said: "s", note: `n${turn_id}`, turn_id });
    const p = (turn_id: number) => ({ turn_id, objectives: [], competencies: [] });
    expect(latestChecks({ checks: [check(1), check(3)], progression: [p(1), p(3)] }).map((c) => c.note)).toEqual(["n3"]);
    expect(latestChecks({ checks: [check(1)], progression: [p(1), p(3)] })).toEqual([]);
    expect(latestChecks({ checks: [], progression: [] })).toEqual([]);
  });
});
