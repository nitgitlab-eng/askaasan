import { AlertTriangle, Lightbulb, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/cn";
import type { CoachItem, CoachProgress } from "@/lib/roleplay";
import { Kili } from "@/mascot/Kili";

import { doneCount, latestChecks, level, MAX_SCORE } from "./coachLogic";
import type { useLiveCoach } from "./useLiveCoach";

function Pips({ score, label }: { score: number; label: string }) {
  const n = level(score);
  return (
    <span className="inline-flex shrink-0 gap-0.5" role="img" aria-label={label}>
      {Array.from({ length: MAX_SCORE }, (_, i) => (
        <span key={i} className={cn("h-1.5 w-3 rounded-full", i < n ? (n === MAX_SCORE ? "bg-good" : "bg-accent") : "bg-line")} />
      ))}
    </span>
  );
}

function Row({ item }: { item: CoachItem }) {
  const { t } = useTranslation();
  const lvl = t(`rpx.level.${level(item.score)}`);
  return (
    <li className="flex items-center gap-2 rounded-full bg-surface px-2.5 py-1 text-xs" title={item.reason || undefined}>
      <span className="max-w-[14rem] truncate">{item.text}</span>
      <Pips score={item.score} label={t("rpx.scoreLabel", { name: item.text, level: lvl })} />
    </li>
  );
}

type Coach = ReturnType<typeof useLiveCoach>;

/** Compact live tracker: objective/skill chips that fill per turn, gentle fact checks and Kili's private hint. */
export function LiveCoachBar({ coach, disabled }: { coach: Coach; disabled?: boolean }) {
  const { t } = useTranslation();
  const { state } = coach;
  const [done, total] = doneCount(state);
  const checks = latestChecks(state);
  const latest = state?.progression.length ? state : null;
  const announce = latest
    ? [
        ...latest.objectives.map((o) => t("rpx.scoreLabel", { name: o.text, level: t(`rpx.level.${level(o.score)}`) })),
        ...checks.map((c) => c.note),
      ].join(". ")
    : "";

  return (
    <section aria-label={t("rpx.tracker")} className="mb-2 space-y-2 rounded-xl bg-surface-2 px-3 py-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <details className="min-w-0 flex-1">
          <summary className="cursor-pointer text-xs font-semibold">
            📈 {t("rpx.tracker")} · {done}/{total}
            {coach.updating && <span className="ml-2 font-normal text-muted">{t("rpx.updating")}</span>}
          </summary>
          {state && (
            <div className="mt-2 space-y-2">
              {(["objectives", "competencies"] as const).map((k) => (
                <div key={k}>
                  <p className="text-xs font-semibold text-muted">{t(`rpx.${k === "objectives" ? "objectives" : "skills"}`)}</p>
                  <ul className="mt-1 space-y-1">
                    {state[k].map((it) => (
                      <li key={it.text} className="flex items-start gap-2 text-xs">
                        <Pips score={it.score} label={t("rpx.scoreLabel", { name: it.text, level: t(`rpx.level.${level(it.score)}`) })} />
                        <span><b>{it.text}</b>{it.reason && <span className="text-muted"> — {it.reason}</span>}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </details>
        <button
          type="button"
          onClick={() => void coach.askHint()}
          disabled={disabled || coach.hintBusy || coach.hintsLeft <= 0}
          className="flex items-center gap-1 rounded-full border-2 border-line bg-surface px-3 py-1 text-xs font-semibold hover:border-accent disabled:opacity-50"
          aria-describedby="rpx-hints-left"
        >
          <Lightbulb className="h-3.5 w-3.5" /> {t("rpx.hint")}
          <span id="rpx-hints-left" className="font-normal text-muted">· {coach.hintsLeft > 0 ? t("rpx.hintsLeft", { count: coach.hintsLeft }) : t("rpx.noHints")}</span>
        </button>
      </div>
      {state && (
        <ul className="flex gap-1.5 overflow-x-auto pb-0.5" aria-hidden="true">
          {state.objectives.map((o) => <Row key={o.text} item={o} />)}
        </ul>
      )}
      {checks.map((c) => (
        <p key={c.note} className="flex items-start gap-1.5 rounded-lg bg-amber-500/10 px-2 py-1 text-xs">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />
          <span><b>{t("rpx.check")}:</b> {c.note}</span>
        </p>
      ))}
      {coach.error && <p className="text-xs text-muted">{t(coach.error === "budget" ? "rpx.budget" : "rpx.failed")}</p>}
      {coach.hintError && <p role="alert" className="text-xs text-bad">{t(coach.hintError === "limit" ? "rpx.hintLimit" : coach.hintError === "budget" ? "rpx.budget" : "rpx.failed")}</p>}
      {coach.hint && (
        <aside className="flex items-start gap-2 rounded-2xl border border-accent/40 bg-surface p-2.5" aria-label={t("rpx.hintFrom")}>
          <Kili mood="cheer" size={36} />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-muted">{t("rpx.hintFrom")}</p>
            <p className="text-sm">{coach.hint.text}</p>
          </div>
          <button type="button" onClick={coach.closeHint} aria-label={t("rpx.close")} className="rounded p-1 text-muted hover:text-ink"><X className="h-4 w-4" /></button>
        </aside>
      )}
      <p className="sr-only" aria-live="polite">{coach.hint ? `${t("rpx.hintFrom")}: ${coach.hint.text}. ` : ""}{announce}</p>
    </section>
  );
}

/** Final report: how the objectives filled up turn by turn, fact checks raised, and hints used. */
export function CoachReport({ objectives, coach }: { objectives: string[]; coach: { progression: CoachProgress[]; checks: { note: string }[]; hints_used: number } }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-3">
      <h2 className="font-display text-xl font-bold">📈 {t("rpx.progression")}</h2>
      {!!coach.progression.length && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr>
                <th scope="col" className="sr-only">{t("rpx.objectives")}</th>
                {coach.progression.map((p, i) => <th key={p.turn_id} scope="col" className="px-2 text-xs font-semibold text-muted">{t("rpx.turn", { n: i + 1 })}</th>)}
              </tr>
            </thead>
            <tbody>
              {objectives.map((o, oi) => (
                <tr key={o} className="border-t border-line">
                  <th scope="row" className="max-w-[12rem] py-1.5 pr-2 font-normal">{o}</th>
                  {coach.progression.map((p) => {
                    const s = p.objectives[oi] ?? 0;
                    return <td key={p.turn_id} className="px-2"><Pips score={s} label={t(`rpx.level.${level(s)}`)} /></td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!!coach.checks.length && (
        <div>
          <p className="text-sm font-semibold">{t("rpx.checks")}</p>
          <ul className="list-disc pl-5 text-sm">{coach.checks.map((c, i) => <li key={i}>{c.note}</li>)}</ul>
        </div>
      )}
      <p className="text-sm text-muted">💡 {coach.hints_used ? t("rpx.hintsUsed", { count: coach.hints_used }) : t("rpx.noHintsUsed")}</p>
    </div>
  );
}
