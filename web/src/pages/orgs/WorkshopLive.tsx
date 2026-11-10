import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Radio, WifiOff } from "lucide-react";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { PageError } from "@/components/PageState";
import { LearnerDrawer } from "@/components/workshop/LearnerDrawer";
import { MonitorGrid } from "@/components/workshop/MonitorGrid";
import { cn } from "@/lib/cn";
import { orgs } from "@/lib/orgs";
import { orgWorkshops, runsKey, useMonitorSocket } from "@/lib/orgWorkshops";
import { useRunTime } from "@/lib/workshops";

import { ReportLinks } from "./WorkshopsTab";

/** /org/:slug/workshops/:runId/live: the faculty dashboard for one institution run (teachers see their classes only). */
export default function WorkshopLivePage() {
  const { t } = useTranslation();
  const when = useRunTime();
  const { slug = "", runId: rid } = useParams();
  const runId = Number(rid);
  const { data: org, error: orgError } = useQuery({ queryKey: ["org", slug], queryFn: () => orgs.get(slug), retry: false });
  const { data: runs } = useQuery({ queryKey: runsKey(slug), queryFn: () => orgWorkshops.runs(slug), enabled: !!org && org.role !== "learner" });
  const run = runs?.runs.find((r) => r.id === runId);
  const mon = useMonitorSocket(runId);
  const [open, setOpen] = useState<number | null>(null);
  const onOpen = useCallback((id: number) => setOpen(id), []);
  const onClose = useCallback(() => setOpen(null), []);

  if (!(runId > 0) || orgError || mon.status === "not_found") return <PageError notFound />;
  if (org?.role === "learner" || mon.status === "forbidden") return <p role="alert" className="p-8 text-muted">{t("orgWs.live.forbidden")}</p>;
  const openTile = open !== null ? mon.tiles[open] : undefined;

  return (
    <div className="mx-auto max-w-7xl space-y-4 px-3 py-5 md:px-6 md:py-8">
      <Link to={`/org/${slug}`} className="inline-flex items-center gap-1.5 text-sm font-semibold text-accent hover:underline"><ArrowLeft className="h-4 w-4" aria-hidden /> {t("orgWs.live.back")}</Link>
      <header className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm text-muted">{org?.name}</p>
          <h1 className="font-display text-2xl font-extrabold md:text-3xl">{run?.workshop.title ?? t("orgWs.live.title")}</h1>
          {run && <p className="text-sm text-muted">{when.date(run.starts_at)} · {when.time(run.starts_at)}</p>}
        </div>
        <span role="status" className={cn("flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-semibold", mon.status === "live" ? "bg-good/15 text-good" : "bg-surface-2 text-muted")}>
          {mon.status === "live" ? <Radio className="h-4 w-4" aria-hidden /> : <WifiOff className="h-4 w-4" aria-hidden />}
          {t(`orgWs.live.conn.${mon.status}`)}
        </span>
      </header>
      {run && <ReportLinks slug={slug} runId={runId} />}
      {mon.error && <p role="alert" className="text-sm text-bad">{t(`orgWs.live.err.${mon.error}`, { defaultValue: t("orgWs.live.err.generic") })}</p>}
      {mon.status === "connecting" && !Object.keys(mon.tiles).length ? <p className="text-muted">{t("common.loading")}</p> : <MonitorGrid tiles={mon.tiles} onOpen={onOpen} />}
      {mon.notJoined.length > 0 && (
        <details className="rounded-2xl border border-line bg-surface p-3" data-testid="not-joined">
          <summary className="cursor-pointer font-semibold">{t("orgWs.live.notJoined", { count: mon.notJoined.length })}</summary>
          <ul className="mt-2 flex flex-wrap gap-2">
            {mon.notJoined.map((l) => (
              <li key={l.id} className="rounded-full bg-surface-2 px-3 py-1 text-sm">{l.name}{l.roll_no && <span className="text-muted"> · {l.roll_no}</span>}</li>
            ))}
          </ul>
        </details>
      )}
      {openTile && <LearnerDrawer slug={slug} runId={runId} tile={openTile} onClose={onClose} nudge={mon.nudge} ackHand={mon.ackHand} />}
    </div>
  );
}
