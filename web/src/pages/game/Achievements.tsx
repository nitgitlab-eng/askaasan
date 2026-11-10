import { useQuery } from "@tanstack/react-query";
import { Copy, Share2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Kolam } from "@/components/Kolam";
import { StreakRepairBanner } from "@/components/study/StreakRepairBanner";
import { Card } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useGame } from "@/lib/game";
import { useMe } from "@/lib/useMe";
import { Kili } from "@/mascot/Kili";

interface Ach {
  badges: { code: string; icon: string; name: string; desc: string; earned_at: string | null }[];
  calendar: { day: string; xp: number }[];
  lessons_completed: number;
}

/** Kolam rings hold 6, 12, 18, 24, 30 petals: show the ring you're currently filling. */
function nextRing(n: number) {
  let total = 0;
  for (const r of [6, 12, 18, 24, 30]) {
    total += r;
    if (n < total) return total;
  }
  return Math.max(total, n + 1);
}

export default function AchievementsPage() {
  const { t } = useTranslation();
  const { data: g } = useGame();
  const { data: me } = useMe();
  const { data } = useQuery({ queryKey: ["achievements"], queryFn: () => api<Ach>("/api/game/achievements/") });
  const [copied, setCopied] = useState(false);
  const link = g ? `${location.origin}/signup?ref=${g.referral_code}` : "";
  const pct = g ? Math.min(1, (g.xp - g.level_floor) / Math.max(1, g.level_next - g.level_floor)) : 0;
  const max = Math.max(1, ...(data?.calendar.map((c) => c.xp) ?? [1]));

  async function share() {
    const text = t("game.inviteText");
    if (navigator.share) await navigator.share({ title: "Aasan", text, url: link }).catch(() => {});
    else {
      await navigator.clipboard.writeText(`${text} ${link}`);
      setCopied(true);
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-8">
      <StreakRepairBanner />
      <Card className="flex flex-col items-center gap-5 sm:flex-row">
        <Kili mood="celebrate" size={120} color={me?.preferences.mascot.color} accessories={me?.preferences.mascot.accessories} outfit={me?.preferences.mascot.outfit} />
        <div className="w-full flex-1 space-y-2">
          <p className="text-sm font-semibold text-muted">{t("game.levelTitle", { n: g?.level ?? 1, xp: g?.xp ?? 0 })}</p>
          <div className="h-4 overflow-hidden rounded-full bg-surface-2"><div className="h-full rounded-full bg-accent" style={{ width: `${pct * 100}%` }} /></div>
          <p className="text-xs text-muted">{t("game.toNext", { n: Math.max(0, (g?.level_next ?? 0) - (g?.xp ?? 0)) })}</p>
          <div className="flex flex-wrap gap-3 pt-1 text-sm font-bold">
            <span>🔥 {t("game.streakDays", { n: g?.streak ?? 0 })}</span>
            <span>🏅 {t("game.best", { n: g?.best_streak ?? 0 })}</span>
            <span>🧊 {t("game.freezes", { count: g?.freezes ?? 0 })}</span>
            <span>{g?.league.icon} {t(`game.leagues.${g?.league.name ?? "bronze"}`)}</span>
          </div>
        </div>
      </Card>

      {data && (
        <Card className="flex flex-col items-center gap-4 sm:flex-row">
          <Kolam filled={data.lessons_completed} slots={nextRing(data.lessons_completed)} size={200} label={t("game.kolamLabel", { count: data.lessons_completed })} />
          <div>
            <h2 className="font-display text-xl font-bold">{t("game.kolamTitle")}</h2>
            <p className="text-muted">{t("game.kolamSub", { count: data.lessons_completed, left: nextRing(data.lessons_completed) - data.lessons_completed })}</p>
          </div>
        </Card>
      )}

      <Card>
        <h2 className="mb-3 font-display text-xl font-bold">{t("game.activity")}</h2>
        <div className="grid grid-cols-7 gap-1.5 sm:gap-2">
          {data?.calendar.map((c) => (
            <div key={c.day} title={`${c.day}: ${c.xp} XP`} className={cn("aspect-square rounded-lg", c.xp === 0 && "bg-surface-2")}
              style={c.xp ? { background: `color-mix(in srgb, var(--accent) ${25 + (75 * c.xp) / max}%, transparent)` } : undefined} />
          ))}
        </div>
      </Card>

      <Card>
        <h2 className="mb-3 font-display text-xl font-bold">{t("game.badges")}</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {data?.badges.map((b) => (
            <div key={b.code} className={cn("rounded-2xl border-2 p-3 text-center", b.earned_at ? "border-accent bg-accent/10" : "border-line opacity-50 grayscale")}>
              <div className="text-4xl">{b.icon}</div>
              <p className="font-bold">{b.name}</p>
              <p className="text-xs text-muted">{b.desc}</p>
            </div>
          ))}
        </div>
      </Card>

      <Card className="space-y-2">
        <h2 className="font-display text-xl font-bold">{t("game.invite")}</h2>
        <p className="text-sm text-muted">{t("game.inviteSub")}</p>
        <div className="flex flex-wrap items-center gap-2">
          <code className="rounded-lg bg-surface-2 px-3 py-2 text-sm">{g?.referral_code}</code>
          <button onClick={() => { void navigator.clipboard.writeText(link); setCopied(true); }} className="flex items-center gap-1 rounded-xl border-2 border-line px-3 py-1.5 text-sm font-semibold hover:border-accent">
            <Copy className="h-4 w-4" /> {copied ? t("game.copied") : t("game.copyLink")}
          </button>
          <button onClick={share} className="flex items-center gap-1 rounded-xl bg-accent px-3 py-1.5 text-sm font-semibold text-accent-ink"><Share2 className="h-4 w-4" /> {t("game.share")}</button>
        </div>
      </Card>
    </div>
  );
}
