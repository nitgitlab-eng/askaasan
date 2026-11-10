import { Check, ChevronDown, Lock } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { cn } from "@/lib/cn";
import { stageProgress, type Session } from "@/lib/workshops";

type StageState = "done" | "current" | "upcoming";
const stateOf = (i: number, at: number): StageState => (i < at ? "done" : i === at ? "current" : "upcoming");

export function ProgressBar({ pct, label }: { pct: number; label: string }) {
  return (
    <div role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} className="h-2 overflow-hidden rounded-full bg-surface-2">
      <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${pct}%` }} />
    </div>
  );
}

/**
 * The stage list. It follows the server's stage_index: finished stages are ticked, the current one is filled with a
 * "Now" tag, and upcoming ones are locked. Nothing here moves the learner; only Next (on the server) does.
 */
export function StageList({ session, onCurrent }: { session: Session; onCurrent?: () => void }) {
  const { t } = useTranslation();
  return (
    <ol className="space-y-1.5">
      {session.stages.map((s, i) => {
        const state = stateOf(i, session.stage_index);
        return (
          <li key={s.key} data-state={state} aria-current={state === "current" ? "step" : undefined} aria-disabled={state === "upcoming" ? true : undefined}
            className={cn(
              "flex items-center gap-2.5 rounded-xl border-2 px-3 py-2 text-sm",
              state === "done" && "border-good/30 bg-good/10 text-ink",
              state === "current" && "border-accent bg-accent font-bold text-accent-ink shadow-sm",
              state === "upcoming" && "cursor-not-allowed border-line bg-surface text-muted",
            )}>
            <span className={cn("grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-bold",
              state === "done" && "bg-good text-white", state === "current" && "bg-accent-ink text-accent", state === "upcoming" && "bg-surface-2 text-muted")}>
              {state === "done" ? <Check className="h-3.5 w-3.5" strokeWidth={3} aria-label={t("workshop.rail.doneLabel")} /> : i + 1}
            </span>
            {state === "current" && onCurrent ? (
              <button type="button" onClick={onCurrent} className="line-clamp-2 min-w-0 flex-1 text-left leading-snug" title={s.title}>{s.title}</button>
            ) : (
              <span className="line-clamp-2 min-w-0 flex-1 leading-snug" title={s.title}>{s.title}</span>
            )}
            {state === "current" && <span className="shrink-0 rounded-full bg-accent-ink px-2 py-0.5 text-[11px] font-bold uppercase text-accent">{t("workshop.nowTag")}</span>}
            {state === "upcoming" && <Lock className="h-3.5 w-3.5 shrink-0" aria-label={t("workshop.rail.locked")} />}
            {state !== "current" && <span className="shrink-0 text-xs tabular-nums">{t("workshop.list.minutes", { count: s.minutes })}</span>}
          </li>
        );
      })}
    </ol>
  );
}

const summary = (t: TFunction, session: Session, pct: number) =>
  `${t("workshop.stageN", { n: Math.min(session.stage_index + 1, session.stages.length), total: session.stages.length })} · ${pct}%`;

/** Desktop: a solid, sticky card with its own scroll when the plan is long. */
export function StageRail({ session, onCurrent }: { session: Session; onCurrent?: () => void }) {
  const { t } = useTranslation();
  const pct = stageProgress(session);
  return (
    <nav aria-label={t("workshop.stages")} data-testid="stage-rail"
      className="sticky top-16 max-h-[calc(100dvh-5rem)] overflow-y-auto rounded-2xl border-2 border-line bg-surface p-4 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">{t("workshop.stages")}</p>
      <p className="mb-2 mt-1 text-sm font-bold">{summary(t, session, pct)}</p>
      <ProgressBar pct={pct} label={t("workshop.rail.progress")} />
      <div className="mt-4"><StageList session={session} onCurrent={onCurrent} /></div>
    </nav>
  );
}

/** Phones: a strip pinned under the app header (stage title, step N of M, progress) that opens the full plan on tap. */
export function StageStrip({ session }: { session: Session }) {
  const { t } = useTranslation();
  // Remembers which stage the plan was opened on, so moving to a new stage folds it away again.
  const [openAt, setOpenAt] = useState<number | null>(null);
  const open = openAt === session.stage_index;
  const listId = useId();
  const pct = stageProgress(session);
  const stage = session.stages[session.stage_index];
  return (
    <div data-testid="stage-strip" className="sticky top-14 z-20 -mx-3 border-b-2 border-line bg-surface/95 px-3 py-2 shadow-sm backdrop-blur md:-mx-6 md:px-6 lg:hidden">
      <button type="button" aria-expanded={open} aria-controls={listId} onClick={() => setOpenAt(open ? null : session.stage_index)} className="flex w-full items-center gap-3 text-left">
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-bold">{stage?.title ?? t("workshop.stages")}</span>
          <span className="block text-xs text-muted">{summary(t, session, pct)}</span>
        </span>
        <span className="sr-only">{open ? t("workshop.rail.hide") : t("workshop.rail.show")}</span>
        <ChevronDown className={cn("h-5 w-5 shrink-0 transition", open && "rotate-180")} aria-hidden />
      </button>
      <div className="mt-1.5"><ProgressBar pct={pct} label={t("workshop.rail.progress")} /></div>
      {open && (
        <nav id={listId} aria-label={t("workshop.stages")} className="mt-3 max-h-[60dvh] overflow-y-auto pb-1">
          <StageList session={session} />
        </nav>
      )}
    </div>
  );
}
