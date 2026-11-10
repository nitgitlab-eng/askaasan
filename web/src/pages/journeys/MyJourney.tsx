import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Compass } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import { JourneyItemRow } from "@/components/journeys/JourneyItemRow";
import { Card } from "@/components/ui";
import { cn } from "@/lib/cn";
import { byDay, dayLabel, journeys, shortDate, splitItems, type PhaseStatus } from "@/lib/journeys";

/** /journey — the new joiner's onboarding plan: today, what's next, and what's behind. */
export default function MyJourneyPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const { data: list } = useQuery({ queryKey: ["my-journeys"], queryFn: journeys.mine });
  const picked = Number(params.get("a")) || list?.[0]?.id;
  if (!list) return <p className="p-8 text-muted">{t("common.loading")}</p>;
  return (
    <div className="mx-auto max-w-3xl space-y-5 px-4 py-8">
      <h1 className="flex items-center gap-2 font-display text-3xl font-extrabold"><Compass className="h-7 w-7 text-accent" /> {t("jr.navTitle")}</h1>
      {!list.length && <Card><p className="text-muted">{t("jr.noJourney")}</p></Card>}
      {list.length > 1 && (
        <div role="tablist" className="flex flex-wrap gap-1 rounded-2xl bg-surface-2 p-1">
          {list.map((a) => (
            <button key={a.id} role="tab" aria-selected={a.id === picked} onClick={() => setParams({ a: String(a.id) })}
              className={cn("rounded-xl px-3 py-1.5 text-sm font-semibold", a.id === picked ? "bg-surface shadow" : "text-muted hover:text-ink")}>
              {a.journey.name}
            </button>
          ))}
        </div>
      )}
      {picked && list.some((a) => a.id === picked) && <JourneyView id={picked} />}
    </div>
  );
}

function PhaseStrip({ phases }: { phases: PhaseStatus[] }) {
  const { t } = useTranslation();
  if (!phases.length) return null;
  return (
    <ol className="grid gap-2 sm:grid-flow-col sm:auto-cols-fr">
      {phases.map((p) => (
        <li key={p.start_day} className={cn("rounded-xl border-2 p-2 text-sm", p.status === "active" ? "border-accent" : p.status === "behind" ? "border-bad/60" : "border-line")}>
          <p className="font-semibold">{p.title}</p>
          <p className="text-xs text-muted">{t("jr.dayRange", { a: p.start_day, b: p.end_day })} · {t(`jr.phaseStatus.${p.status}`)} · {p.done}/{p.total}</p>
        </li>
      ))}
    </ol>
  );
}

function JourneyView({ id }: { id: number }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const { data: a } = useQuery({ queryKey: ["my-journey", id], queryFn: () => journeys.myOne(id) });
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState("");
  if (!a?.items) return <p className="text-muted">{t("common.loading")}</p>;
  const s = a.status;
  const { today, upcoming, past } = splitItems(a.items, s.day);

  async function tick(item: number, done: boolean) {
    setBusy(item);
    setError("");
    try {
      qc.setQueryData(["my-journey", id], await journeys.tick(id, item, done));
      void qc.invalidateQueries({ queryKey: ["my-journeys"] });
    } catch {
      setError(t("jr.tickFailed"));
    } finally {
      setBusy(null);
    }
  }
  const row = (i: (typeof a.items)[number]) => <JourneyItemRow key={i.id} item={i} busy={busy === i.id} onTick={(d) => void tick(i.id, d)} />;
  const pct = s.total ? Math.round((s.done / s.total) * 100) : 0;

  return (
    <div className="space-y-5">
      <Card className="space-y-3 bg-gradient-to-br from-accent/15 to-surface">
        <p className="text-sm text-muted">{a.org}</p>
        <h2 className="font-display text-2xl font-extrabold">{a.journey.name}</h2>
        {a.journey.description && <p className="text-muted">{a.journey.description}</p>}
        <p className="font-display text-xl font-bold text-accent">{dayLabel(t, a, i18n.language)}</p>
        <div className="h-2 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={t("jr.progress", { done: s.done, total: s.total })}>
          <div className="h-full bg-accent" style={{ width: `${pct}%` }} />
        </div>
        <p className="text-sm">{t("jr.progress", { done: s.done, total: s.total })}{s.overdue > 0 && <span className="ml-2 font-semibold text-bad">{t("jr.overdueN", { n: s.overdue })}</span>}</p>
        <PhaseStrip phases={s.phases} />
      </Card>
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}

      {s.started && !s.ended && (
        <section>
          <h3 className="mb-2 font-display text-xl font-bold">{t("jr.today")}</h3>
          {today.length ? <ul className="space-y-2">{today.map(row)}</ul> : <p className="text-sm text-muted">{t("jr.nothingToday")}</p>}
        </section>
      )}
      {!!past.length && (
        <section>
          <h3 className="mb-2 font-display text-xl font-bold">{t("jr.past")}</h3>
          <ul className="space-y-2">{past.map(row)}</ul>
        </section>
      )}
      {!!upcoming.length && (
        <section>
          <h3 className="mb-2 font-display text-xl font-bold">{t("jr.upcoming")}</h3>
          <div className="space-y-3">
            {byDay(upcoming).slice(0, 14).map(([day, rows]) => (
              <div key={day}>
                <p className="mb-1 text-sm font-semibold text-muted">{t("jr.dayN", { n: day })} · {shortDate(rows[0].due_date, i18n.language)}</p>
                <ul className="space-y-2">{rows.map(row)}</ul>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
