import type { CoachCheck, CoachState } from "@/lib/roleplay";

export const MAX_SCORE = 3;

/** Clamp a tracker score to the 0–3 scale used by the chips. */
export function level(score: number | undefined): 0 | 1 | 2 | 3 {
  const n = Math.round(Number(score) || 0);
  return Math.max(0, Math.min(MAX_SCORE, n)) as 0 | 1 | 2 | 3;
}

/** The latest learner turn needs scoring once the character has finished replying. */
export function needsTrack(learnerTurns: number, tracked: number, busy: boolean): boolean {
  return !busy && learnerTurns > 0 && learnerTurns > tracked;
}

/** Objectives fully met / total, for the compact headline. */
export function doneCount(state: Pick<CoachState, "objectives"> | null | undefined): [number, number] {
  const items = state?.objectives ?? [];
  return [items.filter((o) => level(o.score) === MAX_SCORE).length, items.length];
}

/** Fact checks raised on the newest scored turn (older ones live in the final report). */
export function latestChecks(state: Pick<CoachState, "checks" | "progression"> | null | undefined): CoachCheck[] {
  const last = state?.progression[state.progression.length - 1];
  return last ? state!.checks.filter((c) => c.turn_id === last.turn_id) : [];
}
