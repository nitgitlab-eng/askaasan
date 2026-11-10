import { useQuery } from "@tanstack/react-query";
import { Download, Info } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { HBars, TimeBars } from "@/components/charts";
import { Button, Card } from "@/components/ui";
import { localeOf } from "@/i18n/languages";
import { downloadFile } from "@/lib/download";
import { teach, type Pilot } from "@/lib/teach";

import { defaultRange, pct, points, validRange } from "./teachUtils";

function Tile({ label, value, sub, hint }: { label: string; value: ReactNode; sub: string; hint: string }) {
  return (
    <Card className="space-y-1 p-4">
      <p className="flex items-center gap-1 text-xs text-muted">{label} <span title={hint} aria-label={hint}><Info className="h-3 w-3" /></span></p>
      <p className="font-display text-3xl font-extrabold tabular-nums text-accent">{value}</p>
      <p className="text-xs text-muted">{sub}</p>
    </Card>
  );
}

function highlights(p: Pilot, t: (k: string, o?: Record<string, unknown>) => string): string[] {
  const k = p.kpis;
  const out = [t("teach.pilot.h.activation", { n: k.activation.n, count: k.activation.of }), t("teach.pilot.h.sustained", { count: k.sustained.n }),
    t("teach.pilot.h.completion", { n: k.completion.n, of: k.completion.of })];
  if (k.gain.pairs) out.push(t("teach.pilot.h.gain", { pre: pct(k.gain.avg_pre), post: pct(k.gain.avg_post), count: k.gain.pairs }));
  if (k.recommend.source === "nps") out.push(t("teach.pilot.h.nps", { nps: k.recommend.nps, p: pct(k.recommend.promoters) }));
  else if (k.recommend.source === "ratings") out.push(t("teach.pilot.h.ratings", { p: pct(k.recommend.rating_4plus) }));
  return out;
}

/** Cockpit "Pilot report" tab: leadership KPIs with a date range, charts, and PDF / PPTX exports. */
export default function PilotReport({ slug }: { slug: string }) {
  const { t, i18n } = useTranslation();
  const [range, setRange] = useState(() => defaultRange(new Date()));
  const ok = validRange(range.from, range.to);
  const { data } = useQuery({ queryKey: ["teach-pilot", slug, range.from, range.to], queryFn: () => teach.pilot(slug, range.from, range.to), enabled: ok });
  const [busy, setBusy] = useState<"" | "pdf" | "pptx">("");
  const fmtDay = (d: string) => new Date(d).toLocaleDateString(localeOf(i18n.language), { day: "numeric", month: "short" });
  async function dl(kind: "pdf" | "pptx") {
    setBusy(kind);
    try {
      await downloadFile(kind === "pdf" ? teach.urls.pilotPdf(slug, range.from, range.to) : teach.urls.pilotPptx(slug, range.from, range.to), `pilot-report.${kind}`);
    } finally {
      setBusy("");
    }
  }
  const k = data?.kpis;
  return (
    <div className="space-y-5">
      <Card className="flex flex-wrap items-end gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="font-display text-xl font-bold">{t("teach.tabPilot")}</h2>
          <p className="text-sm text-muted">{t("teach.pilot.sub")}</p>
        </div>
        <label className="text-sm">{t("teach.pilot.from")}<input type="date" value={range.from} max={range.to} onChange={(e) => setRange({ ...range, from: e.target.value })} className="ml-2 rounded-xl border-2 border-line bg-surface px-3 py-1.5" /></label>
        <label className="text-sm">{t("teach.pilot.to")}<input type="date" value={range.to} min={range.from} onChange={(e) => setRange({ ...range, to: e.target.value })} className="ml-2 rounded-xl border-2 border-line bg-surface px-3 py-1.5" /></label>
        <Button variant="outline" className="py-1.5 text-sm" disabled={!ok || !data} loading={busy === "pdf"} onClick={() => void dl("pdf")}><Download className="h-4 w-4" /> {t("teach.pilot.pdf")}</Button>
        <Button variant="outline" className="py-1.5 text-sm" disabled={!ok || !data} loading={busy === "pptx"} onClick={() => void dl("pptx")}><Download className="h-4 w-4" /> {t("teach.pilot.pptx")}</Button>
      </Card>
      {!ok && <p role="alert" className="text-sm text-bad">{t("teach.pilot.badRange")}</p>}
      {ok && !data && <p className="text-muted">{t("common.loading")}</p>}
      {data?.no_class && <p className="rounded-xl bg-surface-2 p-3 text-sm text-muted">{t("teachScope.noClass")}</p>}
      {data && k && !data.no_class && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
            <Tile label={t("teach.pilot.activation")} value={pct(k.activation.value)} sub={t("teach.pilot.nOf", { n: k.activation.n, of: k.activation.of })} hint={t("teach.pilot.def.activation")} />
            <Tile label={t("teach.pilot.sustained")} value={pct(k.sustained.value)} sub={t("teach.pilot.nOf", { n: k.sustained.n, of: k.sustained.of })} hint={t("teach.pilot.def.sustained")} />
            <Tile label={t("teach.pilot.completion")} value={pct(k.completion.value)} sub={t("teach.pilot.nOf", { n: k.completion.n, of: k.completion.of })} hint={t("teach.pilot.def.completion")} />
            <Tile label={t("teach.pilot.gain")} value={k.gain.avg_gain == null ? "—" : t("teach.pilot.gainPts", { v: points(k.gain.avg_gain) })}
              sub={k.gain.pairs ? t("teach.pilot.gainSub", { count: k.gain.pairs }) : t("teach.pilot.noData")} hint={t("teach.pilot.def.gain")} />
            <Tile label={t("teach.pilot.recommend")} value={pct(k.recommend.value)} hint={t("teach.pilot.def.recommend")}
              sub={k.recommend.source === "nps" ? t("teach.pilot.npsSub", { nps: k.recommend.nps, count: k.recommend.nps_responses })
                : k.recommend.source === "ratings" ? t("teach.pilot.ratingsSub", { n: k.recommend.ratings }) : t("teach.pilot.noData")} />
          </div>
          <div className="grid gap-5 lg:grid-cols-2">
            <Card><TimeBars title={t("teach.pilot.weeklyActive")} valueLabel={t("teach.pilot.learners")} data={data.weekly.map((w) => ({ label: fmtDay(w.week), value: w.active }))} /></Card>
            <Card><TimeBars title={t("teach.pilot.weeklyLessons")} valueLabel={t("teach.pilot.lessons")} data={data.weekly.map((w) => ({ label: fmtDay(w.week), value: w.lessons }))} /></Card>
            <Card className="lg:col-span-2"><HBars title={t("teach.pilot.courseCompletion")} valueLabel={t("teach.pilot.completion")} max={1} format={pct} empty={t("org.noAssignments")}
              data={data.courses.map((c) => ({ label: c.title, value: c.rate ?? 0, note: t("teach.pilot.nOf", { n: c.completed, of: c.learners }) }))} /></Card>
          </div>
          <Card className="space-y-2">
            <h3 className="font-display text-lg font-bold">{t("teach.pilot.highlights")}</h3>
            <ul className="list-disc space-y-1 pl-5 text-sm">{highlights(data, t).map((h) => <li key={h}>{h}</li>)}</ul>
            <details className="text-sm">
              <summary className="cursor-pointer font-semibold text-muted">{t("teach.pilot.howMeasured")}</summary>
              <ul className="mt-1 space-y-1 pl-1 text-xs text-muted">
                {(["activation", "sustained", "completion", "gain", "recommend"] as const).map((x) => <li key={x}><b>{t(`teach.pilot.${x}`)}:</b> {t(`teach.pilot.def.${x}`)}</li>)}
              </ul>
            </details>
          </Card>
        </>
      )}
    </div>
  );
}
