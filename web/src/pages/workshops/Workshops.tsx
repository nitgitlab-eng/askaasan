import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Presentation } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { PageError } from "@/components/PageState";
import { Button, Card } from "@/components/ui";
import { Countdown, PriceBadge, RunMeta } from "@/components/workshop/RunBits";
import { cn } from "@/lib/cn";
import { joinPhase, runSection, useNow, workshops, type Run } from "@/lib/workshops";
import { Kili } from "@/mascot/Kili";

import { useOpenSession } from "./useOpenSession";

function RunCard({ run, now, section }: { run: Run; now: number; section: "mine" | "upcoming" | "past" }) {
  const { t } = useTranslation();
  const { open, busy, err } = useOpenSession();
  const phase = joinPhase(run, now);
  const detail = `/workshops/${run.id}`;

  let action: ReactNode = null;
  if (section === "mine") {
    if (run.session_id || phase === "anytime" || phase === "open") {
      action = <Button loading={busy} onClick={() => void open(run)}>{run.session_id ? t("workshop.list.continue") : phase === "open" ? t("workshop.pub.joinNow") : t("workshop.list.open")}</Button>;
    } else if (run.my_status === "paid_pending") {
      action = <span className="text-sm font-semibold text-muted">{t("workshop.pub.pendingShort")}</span>;
    } else if (phase === "lobby") {
      action = <Link to={`${detail}/lobby`} className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2.5 font-semibold text-accent-ink shadow-sm hover:brightness-105">{t("workshop.pub.toLobby")} <ArrowRight className="h-4 w-4" aria-hidden /></Link>;
    }
  }

  return (
    <Card className={cn("space-y-3", section === "past" && "bg-surface-2/60")} data-section={section}>
      <div className="flex items-start gap-3">
        <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-accent/10 text-accent"><Presentation className="h-6 w-6" aria-hidden /></span>
        <div className="min-w-0 flex-1">
          <h3 className="break-words font-display text-xl font-bold">
            <Link to={detail} className="hover:underline">{run.workshop.title}</Link>
          </h3>
          <p className="break-words text-muted">{run.workshop.summary}</p>
        </div>
        <PriceBadge paise={run.price_paise} />
      </div>
      <RunMeta run={run} />
      {section !== "past" && phase !== "anytime" && (
        <p className="text-sm font-semibold text-accent">
          {phase === "before_lobby" || phase === "lobby" ? (
            <>{t("workshop.pub.startsIn")} <Countdown to={run.starts_at} now={now} /></>
          ) : phase === "open" ? t("workshop.pub.liveNow") : null}
        </p>
      )}
      {section === "past" && <p className="text-sm font-semibold text-muted">{run.status === "cancelled" ? t("workshop.pub.cancelled") : t("workshop.pub.ended")}</p>}
      <div className="flex flex-wrap items-center gap-2">
        {section === "mine" && run.my_status !== "paid_pending" && <span className="text-sm font-semibold text-good">{t("workshop.list.enrolled")}</span>}
        {action}
        {(section !== "mine" || !action) && (
          <Link to={detail} className="inline-flex items-center gap-1 rounded-xl border-2 border-line bg-surface px-4 py-2 font-semibold hover:border-accent">
            {t("workshop.pub.details")} <ArrowRight className="h-4 w-4" aria-hidden />
          </Link>
        )}
      </div>
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
    </Card>
  );
}

function Section({ title, runs, now, section, empty }: { title: string; runs: Run[]; now: number; section: "mine" | "upcoming" | "past"; empty?: string }) {
  if (!runs.length && !empty) return null;
  const id = `ws-${section}`;
  return (
    <section aria-labelledby={id} className="space-y-3">
      <h2 id={id} className="font-display text-xl font-bold">{title}</h2>
      {runs.length ? runs.map((r) => <RunCard key={r.id} run={r} now={now} section={section} />) : <Card className="text-center text-muted">{empty}</Card>}
    </section>
  );
}

/** Upcoming public workshops, the learner's own (with Join once the lobby opens), and past ones. */
export default function WorkshopsPage() {
  const { t } = useTranslation();
  const now = useNow(1000);
  const { data, error, refetch } = useQuery({ queryKey: ["workshop-runs"], queryFn: workshops.runs, refetchInterval: 60_000 });
  const by = { mine: [] as Run[], upcoming: [] as Run[], past: [] as Run[] };
  for (const r of data ?? []) by[runSection(r, now)].push(r);
  const soonest = (a: Run, b: Run) => Date.parse(a.starts_at) - Date.parse(b.starts_at);
  by.mine.sort(soonest);
  by.upcoming.sort(soonest);
  by.past.sort((a, b) => -soonest(a, b));

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">
      <header className="flex items-center gap-4">
        <Kili mood="wave" size={84} />
        <div className="min-w-0">
          <h1 className="font-display text-3xl font-extrabold">{t("workshop.list.title")}</h1>
          <p className="text-muted">{t("workshop.list.sub")}</p>
        </div>
      </header>
      {error ? <PageError error={error} onRetry={() => void refetch()} /> : !data ? <p className="text-muted">{t("common.loading")}</p> : data.length === 0 ? (
        <Card className="text-center text-muted">{t("workshop.list.empty")}</Card>
      ) : (
        <>
          <Section title={t("workshop.pub.mine")} runs={by.mine} now={now} section="mine" />
          <Section title={t("workshop.pub.upcoming")} runs={by.upcoming} now={now} section="upcoming" empty={t("workshop.pub.noUpcoming")} />
          <Section title={t("workshop.pub.past")} runs={by.past} now={now} section="past" />
        </>
      )}
    </div>
  );
}
