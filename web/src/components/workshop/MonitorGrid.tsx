import { Hand, LifeBuoy, Users } from "lucide-react";
import { memo, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Segmented } from "@/components/ui";
import { cn } from "@/lib/cn";
import { countByStatus, pctText, filterTiles, normStatus, sortTiles, STATUS_TONE, STATUSES, type Tile, type Tiles, type TileStatus } from "@/lib/orgWorkshops";

const mins = (s: number) => Math.round(s / 60);

export function StatusPill({ status, className }: { status: string; className?: string }) {
  const { t } = useTranslation();
  const s = normStatus(status);
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-2 py-0.5 text-xs font-bold", className)}>
      <span className={cn("h-2 w-2 shrink-0 rounded-full", STATUS_TONE[s])} aria-hidden />
      {t(`orgWs.status.${s}`)}
    </span>
  );
}

/** One learner. Memoised: a tile re-renders only when its own data (a new object from the socket) arrives. */
export const TileCard = memo(function TileCard({ tile, onOpen }: { tile: Tile; onOpen: (sessionId: number) => void }) {
  const { t } = useTranslation();
  const s = normStatus(tile.status);
  const help = tile.help_summaries?.[0] ?? ""; // newest first
  const score = tile.final_score ?? tile.score_so_far;
  return (
    <li className="min-w-0" style={{ contentVisibility: "auto", containIntrinsicSize: "auto 168px" }}>
      <button type="button" onClick={() => onOpen(tile.session_id)} data-testid={`tile-${tile.session_id}`}
        aria-label={`${tile.learner.name} · ${t(`orgWs.status.${s}`)}${tile.raised_hand ? ` · ${t("orgWs.tile.hand")}` : ""}`}
        className="flex h-full w-full flex-col overflow-hidden rounded-2xl border border-line bg-surface text-left shadow-sm transition hover:border-accent focus-visible:border-accent">
        <span className={cn("h-1.5 w-full shrink-0", STATUS_TONE[s])} aria-hidden />
        <span className="flex min-w-0 flex-1 flex-col gap-1.5 p-3">
          <span className="flex min-w-0 items-start gap-2">
            <span className="min-w-0 flex-1">
              <span className="block truncate font-semibold" title={tile.learner.name}>{tile.learner.name}</span>
              {tile.learner.roll_no && <span className="block truncate text-xs text-muted">{tile.learner.roll_no}</span>}
            </span>
            {tile.raised_hand && <Hand className="h-5 w-5 shrink-0 animate-pulse text-bad" aria-label={t("orgWs.tile.hand")} />}
          </span>
          <StatusPill status={tile.status} className="self-start" />
          {tile.stage && <span className="truncate text-xs text-muted" title={tile.stage.title}>{t("orgWs.tile.stage", { n: tile.stage.index + 1, title: tile.stage.title })}</span>}
          {tile.diy && tile.diy.total > 0 ? (
            <span className="flex items-center gap-2 text-xs">
              <span className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-2"><span className="block h-full bg-teal-500" style={{ width: `${Math.round((tile.diy.done / tile.diy.total) * 100)}%` }} /></span>
              <span className="shrink-0 tabular-nums">{t("orgWs.tile.diy", { done: tile.diy.done, total: tile.diy.total })}</span>
            </span>
          ) : tile.concept ? <span className="line-clamp-1 text-xs">{tile.concept}</span> : null}
          <span className="flex flex-wrap gap-x-3 text-xs">
            <span>{t("orgWs.tile.score")}: <b className="tabular-nums">{pctText(score)}</b></span>
            {tile.attention && (
              <span className="text-muted" data-testid="attention">{t("orgWs.tile.attention", { hidden: mins(tile.attention.hidden_s), idle: mins(tile.attention.idle_s), focus: tile.attention.focus_losses })}</span>
            )}
          </span>
          {help && <span className="flex items-start gap-1 text-xs text-muted"><LifeBuoy className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /><span className="line-clamp-2">{help}</span></span>}
        </span>
      </button>
    </li>
  );
});

type Sort = "attention" | "name";

/** The live dashboard grid: per-status counts that double as filters, a sort, and one tile per participant. */
export function MonitorGrid({ tiles, onOpen }: { tiles: Tiles; onOpen: (sessionId: number) => void }) {
  const { t } = useTranslation();
  const [only, setOnly] = useState<ReadonlySet<TileStatus>>(new Set());
  const [sort, setSort] = useState<Sort>("attention");
  const all = useMemo(() => Object.values(tiles), [tiles]);
  const counts = useMemo(() => countByStatus(all), [all]);
  const hands = useMemo(() => all.filter((x) => x.raised_hand).length, [all]);
  const shown = useMemo(() => {
    const list = filterTiles(all, only);
    return sort === "attention" ? sortTiles(list) : [...list].sort((a, b) => a.learner.name.localeCompare(b.learner.name));
  }, [all, only, sort]);
  const toggle = (s: TileStatus) => setOnly((cur) => {
    const next = new Set(cur);
    if (next.has(s)) next.delete(s);
    else next.add(s);
    return next;
  });

  return (
    <div className="space-y-4">
      <div className="space-y-3 rounded-2xl border border-line bg-surface p-3 shadow-sm">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <span className="flex items-center gap-1.5 font-semibold"><Users className="h-4 w-4" aria-hidden /> {t("orgWs.live.learners", { count: all.length })}</span>
          {hands > 0 && <span className="flex items-center gap-1.5 font-semibold text-bad"><Hand className="h-4 w-4" aria-hidden /> {t("orgWs.live.hands", { count: hands })}</span>}
        </div>
        <div role="group" aria-label={t("orgWs.live.filter")} className="flex flex-wrap gap-1.5">
          <button type="button" aria-pressed={only.size === 0} onClick={() => setOnly(new Set())}
            className={cn("rounded-full border-2 px-3 py-1 text-sm font-semibold transition", only.size === 0 ? "border-accent bg-accent text-accent-ink" : "border-line bg-surface hover:border-accent")}>
            {t("orgWs.live.all")} <span className="tabular-nums">{all.length}</span>
          </button>
          {STATUSES.filter((s) => counts[s]).map((s) => (
            <button key={s} type="button" aria-pressed={only.has(s)} onClick={() => toggle(s)} data-testid={`chip-${s}`}
              className={cn("flex items-center gap-1.5 rounded-full border-2 px-3 py-1 text-sm font-semibold transition", only.has(s) ? "border-accent bg-accent/10" : "border-line bg-surface hover:border-accent")}>
              <span className={cn("h-2 w-2 rounded-full", STATUS_TONE[s])} aria-hidden />
              {t(`orgWs.status.${s}`)} <span className="tabular-nums">{counts[s]}</span>
            </button>
          ))}
        </div>
        <Segmented<Sort> label={t("orgWs.live.sort")} value={sort} onChange={setSort}
          options={[{ value: "attention", label: t("orgWs.live.sortAttention") }, { value: "name", label: t("orgWs.live.sortName") }]} />
      </div>
      {all.length === 0 ? (
        <p className="rounded-2xl bg-surface-2 p-6 text-center text-muted">{t("orgWs.live.empty")}</p>
      ) : shown.length === 0 ? (
        <p className="rounded-2xl bg-surface-2 p-6 text-center text-muted">{t("orgWs.live.noMatch")}</p>
      ) : (
        <ul aria-label={t("orgWs.live.grid")} className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2 md:grid-cols-3 xl:grid-cols-4">
          {shown.map((x) => <TileCard key={x.session_id} tile={x} onOpen={onOpen} />)}
        </ul>
      )}
    </div>
  );
}
