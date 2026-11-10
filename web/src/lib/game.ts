import { useQuery } from "@tanstack/react-query";
import confetti from "canvas-confetti";

import i18n from "@/i18n";
import { sfx } from "@/mascot/sfx";
import { mascot } from "@/mascot/store";

import { api } from "./api";

export interface GameStatus {
  xp: number;
  coins: number;
  level: number;
  level_floor: number;
  level_next: number;
  streak: number;
  best_streak: number;
  active_today: boolean;
  freezes: number;
  today_xp: number;
  daily_goal_xp: number;
  weekly_xp: number;
  league: { name: string; icon: string };
  owned_items: string[];
  referral_code: string;
  show_on_leaderboard: boolean;
  unread: number;
  /** A broken streak that can still be repaired (coins, or STREAK_REVIVE_GOAL lessons inside the revival window). */
  repair?: StreakRepairOffer | null;
}

export interface StreakRepairOffer {
  last_streak: number;
  broken_at: string;
  expires_on: string;
  price: number;
  revive_goal: number;
  revive_progress: number;
  revive_ends_at: string | null;
  revive_open: boolean;
  coins_ok?: boolean;
}

export interface Reward {
  xp: number;
  coins: number;
  level_up?: number | null;
  badges?: string[];
  streak?: number;
  daily_goal?: boolean;
  duplicate?: boolean;
  streak_repaired?: { streak: number; how: "coins" | "revive"; badges: string[] };
}

export const gameKey = ["game-status"] as const;
export const useGame = () => useQuery({ queryKey: gameKey, queryFn: () => api<GameStatus>("/api/game/status/"), staleTime: 15_000 });

type Toast = { id: number; text: string; tone: "xp" | "badge" | "level" };
let listeners: ((t: Toast) => void)[] = [];
let seq = 0;
export const onToast = (fn: (t: Toast) => void) => {
  listeners.push(fn);
  return () => {
    listeners = listeners.filter((l) => l !== fn);
  };
};
const toast = (text: string, tone: Toast["tone"]) => listeners.forEach((l) => l({ id: ++seq, text, tone }));

/** Show a reward the server just granted: floating XP, badges, level-ups, Kili. */
export function celebrate(r: Reward | undefined, opts: { reducedMotion?: boolean; invalidate?: () => void } = {}) {
  if (!r || r.duplicate || (!r.xp && !r.coins && !r.badges?.length && !r.streak_repaired)) return;
  const t = i18n.t.bind(i18n);
  if (r.streak_repaired) {
    toast(t("game.repair.done", { n: r.streak_repaired.streak }), "level");
    mascot.react("celebrate");
    mascot.say(t("game.repair.done", { n: r.streak_repaired.streak }), { ms: 4000 });
    if (!opts.reducedMotion) void confetti({ particleCount: 120, spread: 90, origin: { y: 0.6 } });
  }
  if (r.xp || r.coins) toast(`+${r.xp} XP${r.coins ? ` · +${r.coins} 🪙` : ""}`, "xp");
  if (r.daily_goal) toast(t("game.dailyGoalDone"), "badge");
  if (r.badges?.length) toast(`🏅 ${t("game.newBadge")}${r.badges.length > 1 ? ` ×${r.badges.length}` : ""}`, "badge");
  if (r.level_up) {
    sfx("levelup");
    mascot.react("celebrate");
    mascot.say(t("game.levelUp", { n: r.level_up }), { ms: 4000 });
    toast(t("game.levelUp", { n: r.level_up }), "level");
    if (!opts.reducedMotion) void confetti({ particleCount: 160, spread: 100, origin: { y: 0.6 } });
  }
  opts.invalidate?.();
}

export const repairStreak = (how: "coins" | "revive") =>
  api<{ repaired: { streak: number; how: string; badges: string[] }; status: GameStatus }>("/api/game/streak/repair/", { method: "POST", json: { how } });
