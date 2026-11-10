import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Lightbulb } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/lib/api";
import { gameKey } from "@/lib/game";
import { study } from "@/lib/study";
import { mascot } from "@/mascot/store";

const COST: Record<number, number> = { 1: 0, 2: 2, 3: 5 };

/** Kili's help ladder: nudge (free) → hint → worked example (cost coins); never the answer itself. */
export function HintLadder({ activityId, lang }: { activityId: number; lang?: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: used } = useQuery({ queryKey: ["hints", activityId], queryFn: () => study.hintsUsed(activityId), staleTime: Infinity });
  const [hints, setHints] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const opened = Object.keys(hints).map(Number);
  const reached = Math.max(0, ...(used?.used ?? []), ...opened);
  const next = reached + 1;

  async function ask(level: number) {
    setBusy(true);
    setError("");
    mascot.react("thinking", 0);
    try {
      const r = await study.hint(activityId, level, lang);
      setHints((h) => ({ ...h, [level]: r.text }));
      void qc.invalidateQueries({ queryKey: ["hints", activityId] });
      if (r.cost) void qc.invalidateQueries({ queryKey: gameKey });
      mascot.react("talking", 1500);
    } catch (e) {
      const code = e instanceof ApiError ? e.data?.code : null;
      setError(code === "not_enough_coins" ? t("hint.noCoins", { n: COST[level] }) : code === "ai_budget_exceeded" ? t("paths.budget") : t("mentor.errors.generic"));
      mascot.react("hmm");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      {[1, 2, 3].filter((lv) => hints[lv]).map((lv) => (
        <div key={lv} className="rounded-xl border border-accent/30 bg-accent/5 px-3 py-2 text-sm">
          <p className="mb-0.5 text-xs font-semibold uppercase tracking-wide text-accent">{t(`hint.level.${lv}`)}</p>
          <p className="whitespace-pre-line">{hints[lv]}</p>
        </div>
      ))}
      {[1, 2, 3].filter((lv) => !hints[lv] && lv <= reached).map((lv) => (
        <button key={lv} onClick={() => void ask(lv)} disabled={busy} className="mr-2 text-xs font-semibold text-accent underline-offset-2 hover:underline">
          {t("hint.showAgain", { level: t(`hint.level.${lv}`) })}
        </button>
      ))}
      {next <= 3 && (
        <button onClick={() => void ask(next)} disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-xl border-2 border-line px-3 py-1.5 text-sm font-semibold hover:border-accent disabled:opacity-50">
          <Lightbulb className="h-4 w-4 text-accent" />
          {t(`hint.ask.${next}`)}{COST[next] ? ` · 🪙 ${COST[next]}` : ` · ${t("hint.free")}`}
        </button>
      )}
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
    </div>
  );
}
