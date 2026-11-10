import { describe, expect, it, vi } from "vitest";

import { celebrate, onToast } from "./game";

vi.mock("canvas-confetti", () => ({ default: vi.fn() }));

describe("celebrate", () => {
  it("toasts XP, daily goal, badges and level-ups; ignores duplicates", () => {
    const seen: string[] = [];
    const off = onToast((t) => seen.push(`${t.tone}:${t.text}`));
    celebrate({ xp: 0, coins: 0, duplicate: true });
    celebrate({ xp: 0, coins: 0 });
    expect(seen).toEqual([]);
    celebrate({ xp: 50, coins: 10, daily_goal: true, badges: ["first_lesson", "streak_3"], level_up: 2 }, { reducedMotion: true });
    expect(seen[0]).toBe("xp:+50 XP · +10 🪙");
    expect(seen.some((s) => s.startsWith("badge:🏅") && s.endsWith("×2"))).toBe(true);
    expect(seen.some((s) => s.startsWith("level:"))).toBe(true);
    off();
  });
});
