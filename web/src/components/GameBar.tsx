import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { Bell, Presentation } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { gameKey, onToast, useGame } from "@/lib/game";

interface Note {
  id: number;
  kind?: string;
  title: string;
  body: string;
  link: string;
  read: boolean;
}

/** Workshop announcements, reminders and changes: each links to /workshops/<id>. */
const WORKSHOP_KINDS = new Set(["workshop_announce", "workshop"]);

/** Streak, coins, level ring and notifications — always visible. */
export function GameBar() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data: g } = useGame();
  const [open, setOpen] = useState(false);
  const notes = useQuery({ queryKey: ["notifications"], queryFn: () => api<Note[]>("/api/game/notifications/"), enabled: open });
  const pct = g ? Math.min(1, (g.xp - g.level_floor) / Math.max(1, g.level_next - g.level_floor)) : 0;
  const goalPct = g ? Math.min(1, g.today_xp / Math.max(1, g.daily_goal_xp)) : 0;

  return (
    <div className="flex items-center gap-2 text-sm font-bold">
      <Link to="/achievements" className={cn("flex items-center gap-1 rounded-full px-2.5 py-1", g?.active_today ? "bg-orange-100 text-orange-600" : "bg-surface-2 text-muted")} title={t("game.streak")}>
        🔥 {g?.streak ?? 0}
      </Link>
      <Link to="/shop" className="flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-1 text-amber-700" title={t("game.coins")}>
        🪙 {g?.coins ?? 0}
      </Link>
      <Link to="/achievements" className="relative flex h-9 w-9 items-center justify-center" title={t("game.levelTitle", { n: g?.level ?? 1, xp: g?.xp ?? 0 })}>
        <svg viewBox="0 0 36 36" className="absolute inset-0 -rotate-90">
          <circle cx="18" cy="18" r="15" fill="none" stroke="var(--surface-2)" strokeWidth="4" />
          <circle cx="18" cy="18" r="15" fill="none" stroke="var(--accent)" strokeWidth="4" strokeDasharray={`${94.2 * pct} 94.2`} strokeLinecap="round" />
        </svg>
        <span className="text-xs">{g?.level ?? 1}</span>
      </Link>
      <span className="hidden h-2 w-16 overflow-hidden rounded-full bg-surface-2 lg:block" title={t("game.dailyGoal", { xp: g?.today_xp ?? 0, goal: g?.daily_goal_xp ?? 0 })}>
        <span className="block h-full rounded-full bg-good" style={{ width: `${goalPct * 100}%` }} />
      </span>
      <div className="relative">
        <button
          onClick={async () => {
            setOpen(!open);
            if (!open && g?.unread) {
              await api("/api/game/notifications/read/", { method: "POST" });
              void qc.invalidateQueries({ queryKey: gameKey });
            }
          }}
          className="relative rounded-full p-2 hover:bg-surface-2"
          aria-label={t("game.notifications")}
          aria-expanded={open}
        >
          <Bell className="h-5 w-5" />
          {!!g?.unread && <span className="absolute right-1 top-1 h-2.5 w-2.5 rounded-full bg-bad" />}
        </button>
        {open && (
          <div className="absolute right-0 top-11 z-50 w-72 rounded-2xl border border-line bg-surface p-2 shadow-xl">
            {notes.data?.length ? notes.data.map((n) => (
              <button key={n.id} onClick={() => { setOpen(false); if (n.link) navigate(n.link); }} className="flex w-full items-start gap-2 rounded-xl px-3 py-2 text-left hover:bg-surface-2">
                {WORKSHOP_KINDS.has(n.kind ?? "") && <Presentation className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden />}
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold">{n.title}</span>
                  {n.body && <span className="block text-xs font-normal text-muted">{n.body}</span>}
                </span>
              </button>
            )) : <p className="p-3 text-sm font-normal text-muted">{t("game.noNotifications")}</p>}
          </div>
        )}
      </div>
    </div>
  );
}

/** Floating reward toasts (+XP, badges, level ups). */
export function RewardToasts() {
  const [items, setItems] = useState<{ id: number; text: string; tone: string }[]>([]);
  useEffect(() => onToast((t) => {
    setItems((x) => [...x, t]);
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== t.id)), 2600);
  }), []);
  return (
    <div className="pointer-events-none fixed left-1/2 top-16 z-[60] flex -translate-x-1/2 flex-col items-center gap-2" aria-live="polite">
      <AnimatePresence>
        {items.map((i) => (
          <motion.div key={i.id} initial={{ opacity: 0, y: -10, scale: 0.9 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -20 }}
            className={cn("rounded-full px-4 py-1.5 text-sm font-bold shadow-lg", i.tone === "xp" ? "bg-accent text-accent-ink" : i.tone === "level" ? "bg-violet-600 text-white" : "bg-amber-400 text-amber-950")}>
            {i.text}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
