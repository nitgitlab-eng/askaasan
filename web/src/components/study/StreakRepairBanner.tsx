import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Flame } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";

import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { celebrate, gameKey, repairStreak, useGame } from "@/lib/game";
import { useMe } from "@/lib/useMe";

/** "Your streak broke — bring it back": repair for coins, or finish a few lessons inside the revival window for free.
 *  Shown on Home, Today and Achievements; `?repair=1` (the win-back email link) scrolls to it and highlights it. */
export function StreakRepairBanner() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const { data: g } = useGame();
  const { data: me } = useMe();
  const [params] = useSearchParams();
  const deep = params.get("repair") === "1";
  const ref = useRef<HTMLDivElement>(null);
  const [err, setErr] = useState("");
  const offer = g?.repair;

  useEffect(() => {
    if (deep && offer) ref.current?.scrollIntoView?.({ behavior: "smooth", block: "center" });
  }, [deep, offer]);

  const fix = useMutation({
    mutationFn: () => repairStreak("coins"),
    onSuccess: (r) => {
      qc.setQueryData(gameKey, r.status);
      celebrate({ xp: 0, coins: 0, streak_repaired: { streak: r.repaired.streak, how: "coins", badges: r.repaired.badges } }, { reducedMotion: me?.preferences.appearance.reduced_motion });
    },
    onError: (e) => {
      const code = e instanceof ApiError ? (e.data as { code?: string } | null)?.code : undefined;
      setErr(code === "not_enough_coins" ? t("game.repair.noCoins") : t("game.repair.failed"));
      void qc.invalidateQueries({ queryKey: gameKey });
    },
  });

  if (!offer || !g) return null;
  const date = (iso: string, withTime = false) =>
    new Date(withTime ? iso : `${iso}T12:00:00`).toLocaleString(i18n.language, withTime ? { weekday: "short", hour: "numeric", minute: "2-digit" } : { day: "numeric", month: "short" });
  const canPay = offer.coins_ok !== false;
  const enough = g.coins >= offer.price;
  return (
    <div ref={ref}>
      <Card className={cn("space-y-3 border-2 border-accent/50 bg-gradient-to-br from-accent/10 to-surface", deep && "ring-4 ring-accent/40")} aria-live="polite">
        <div className="flex items-start gap-3">
          <Flame className="mt-1 h-7 w-7 shrink-0 text-accent" />
          <div className="min-w-0 flex-1">
            <h2 className="font-display text-xl font-bold">{t("game.repair.title", { n: offer.last_streak })}</h2>
            <p className="text-sm text-muted">{t("game.repair.until", { date: date(offer.expires_on) })}</p>
          </div>
        </div>
        {offer.revive_open && offer.revive_ends_at && (
          <div className="space-y-1">
            <p className="text-sm">{t("game.repair.revive", { goal: offer.revive_goal, time: date(offer.revive_ends_at, true) })}</p>
            <div className="h-2 rounded-full bg-surface-2" role="progressbar" aria-label={t("game.repair.progress", { n: offer.revive_progress, goal: offer.revive_goal })} aria-valuemin={0} aria-valuemax={offer.revive_goal} aria-valuenow={offer.revive_progress}>
              <div className="h-2 rounded-full bg-accent transition-all" style={{ width: `${(100 * offer.revive_progress) / offer.revive_goal}%` }} />
            </div>
            <p className="text-xs text-muted">{t("game.repair.progress", { n: offer.revive_progress, goal: offer.revive_goal })}</p>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {offer.revive_open && <Link to="/learn" className="rounded-xl border-2 border-line bg-surface px-4 py-2 text-sm font-semibold hover:border-accent">{t("game.repair.startLesson")}</Link>}
          {canPay && (
            <Button loading={fix.isPending} disabled={!enough} onClick={() => { setErr(""); fix.mutate(); }}>
              {t("game.repair.pay", { price: offer.price })}
            </Button>
          )}
          {canPay && !enough && <span className="text-xs text-muted">{t("game.repair.have", { coins: g.coins })}</span>}
        </div>
        {err && <p role="alert" className="text-sm text-bad">{err}</p>}
      </Card>
    </div>
  );
}
