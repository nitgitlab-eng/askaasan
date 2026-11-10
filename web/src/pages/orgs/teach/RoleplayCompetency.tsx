import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { HBars } from "@/components/charts";
import { Button } from "@/components/ui";
import { localeOf } from "@/i18n/languages";
import { cn } from "@/lib/cn";
import { teach, type RpCompetency, type RpConcept, type RpConceptDrill } from "@/lib/teach";

import { aiError, cellText, cellTone, pct, type CellTone } from "./teachUtils";

const TONE: Record<CellTone, string> = {
  none: "bg-surface-2 text-muted",
  low: "bg-bad/10 text-bad",
  mid: "bg-amber-100 text-amber-900",
  pass: "bg-good/15 text-good font-semibold",
};
const STUCK_DAY_CHOICES = [3, 7, 14, 30];

function conceptLabel(t: (k: string) => string, c: RpConcept) {
  return `${c.kind === "objective" ? t("rca.objective") : t("rca.competency")}: ${c.name}`;
}

function Reasons({ title, list }: { title: string; list: { text: string; learners: number }[] }) {
  const { t } = useTranslation();
  return (
    <div>
      <p className="font-semibold">{title}</p>
      {list.length === 0 ? <p className="text-muted">{t("rca.noNotes")}</p> : (
        <ul className="list-disc space-y-0.5 pl-5">
          {list.map((x) => <li key={x.text}>{x.text} <span className="text-xs text-muted">({t("rca.learners", { count: x.learners })})</span></li>)}
        </ul>
      )}
    </div>
  );
}

/** One objective / skill: what learners got right and wrong (coach notes), each learner's level, cached AI summary. */
function ConceptDrill({ slug, id, conceptKey, onClose }: { slug: string; id: number; conceptKey: string; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const qk = ["teach-rp-concept", slug, id, conceptKey];
  const { data, error } = useQuery({ queryKey: qk, queryFn: () => teach.roleplayConcept(slug, id, conceptKey) });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  if (error) return <p className="text-sm text-bad">{aiError(t, error)}</p>;
  if (!data) return <p className="text-sm text-muted">{t("common.loading")}</p>;
  const c = data.concept;
  async function gen() {
    setBusy(true);
    setErr("");
    try {
      const r = await teach.roleplayConceptInsight(slug, id, conceptKey);
      qc.setQueryData<RpConceptDrill>(qk, (old) => (old ? { ...old, insight: r.insight } : old));
    } catch (e) {
      setErr(aiError(t, e));
    } finally {
      setBusy(false);
    }
  }
  const ins = data.insight;
  return (
    <section className="space-y-3 rounded-xl border border-line p-3 text-sm" aria-label={conceptLabel(t, c)}>
      <div className="flex items-start gap-2">
        <p className="flex-1 font-display text-base font-bold">{conceptLabel(t, c)}</p>
        <button className="rounded-full p-1 hover:bg-surface-2" onClick={onClose} aria-label={t("rca.close")}><X className="h-4 w-4" /></button>
      </div>
      <p className="text-muted">{t("rca.passRate")}: {c.rate == null ? "—" : t("rca.rateOf", { pct: pct(c.rate), passed: c.passed, tried: c.attempted })}</p>
      {data.final && <p>{t("rca.finalReports", { met: t("rca.metTimes", { count: data.final.met }), notMet: t("rca.notMetTimes", { count: data.final.not_met }) })}</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        <Reasons title={`💪 ${t("rca.gotRight")}`} list={data.right} />
        <Reasons title={`🎯 ${t("rca.gotWrong")}`} list={data.wrong} />
      </div>
      <details>
        <summary className="cursor-pointer font-semibold">{t("rca.eachLearner")}</summary>
        <ul className="mt-1 flex flex-wrap gap-1.5">
          {data.learners.map((l) => (
            <li key={l.user_id} className={cn("rounded-full px-2 py-0.5 text-xs", TONE[cellTone(l.level, c.max, c.pass)])}>
              {l.name}: {l.level == null ? t("rca.notTried") : cellText(l.level, c.max, l.passed)}
            </li>
          ))}
        </ul>
      </details>
      <div className="space-y-2 rounded-xl bg-surface-2 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <p className="flex flex-1 items-center gap-2 font-semibold"><Sparkles className="h-4 w-4 text-accent" /> {t("rca.aiTitle")}</p>
          {ins && <span className="text-xs text-muted">{t("teach.updated", { d: new Date(ins.updated_at).toLocaleDateString(localeOf(i18n.language), { day: "numeric", month: "short" }) })}</span>}
          <Button variant="outline" className="py-1 text-sm" loading={busy} onClick={() => void gen()}>{ins ? t("teach.regenerate") : t("teach.generate")}</Button>
        </div>
        <p className="text-xs text-muted">{t("teach.aiCost")}</p>
        {err && <p role="alert" className="text-bad">{err}</p>}
        {ins && (
          <div className="space-y-2">
            <p className="font-semibold">{ins.summary}</p>
            <div className="grid gap-3 sm:grid-cols-3">
              {([["rca.gotRight", ins.got_right], ["rca.gotWrong", ins.got_wrong], ["rca.tips", ins.reteach_tips]] as const).map(([k, list]) => (
                <div key={k}><p className="font-semibold">{t(k)}</p><ul className="list-disc pl-5">{list.map((x) => <li key={x}>{x}</li>)}</ul></div>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

/** Competency analytics for an assigned role-play: funnel, learners × concepts heat-map, stuck learners, drill-down. */
export function RoleplayCompetency({ slug, id, data, stuckDays, onStuckDays }: {
  slug: string; id: number; data: RpCompetency; stuckDays: number; onStuckDays: (n: number) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState<string | null>(null);
  const cs = data.concepts;
  return (
    <div className="space-y-4">
      <HBars title={t("rca.funnelTitle")} valueLabel={t("rca.funnelValue")} max={Math.max(1, data.funnel[0]?.count ?? 1)}
        data={data.funnel.map((f) => ({ label: t(`rca.stage.${f.stage}`), value: f.count, note: pct(f.pct) }))}
        format={(v) => String(v)} />
      <p className="text-xs text-muted">{t("rca.passNote", { n: data.pass_score })}</p>

      {cs.length > 0 && (
        <div className="space-y-2">
          <p className="font-display text-base font-bold">{t("rca.title")}</p>
          <p className="text-xs text-muted">{t("rca.matrixHelp")}</p>
          <div className="overflow-x-auto">
            <table className="w-full border-separate border-spacing-0.5 text-sm">
              <thead className="text-left text-xs text-muted">
                <tr>
                  <th scope="col" className="px-1 py-1">{t("rca.learner")}</th>
                  {cs.map((c) => (
                    <th key={c.key} scope="col" className="min-w-24 max-w-40 px-1 py-1 align-bottom">
                      <button className={cn("text-left hover:text-accent", open === c.key && "text-accent")} aria-expanded={open === c.key}
                        aria-label={t("rca.openConcept", { name: conceptLabel(t, c) })} onClick={() => setOpen(open === c.key ? null : c.key)}>
                        <span className="block text-[10px] uppercase tracking-wide">{c.kind === "objective" ? t("rca.objective") : t("rca.competency")}</span>
                        <span className="line-clamp-2 font-semibold text-ink">{c.name}</span>
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.matrix.map((r) => (
                  <tr key={r.user_id}>
                    <th scope="row" className="px-1 py-1 text-left font-medium">{r.name}</th>
                    {cs.map((c) => {
                      const cell = r.cells[c.key] ?? { level: null, passed: false };
                      const text = cellText(cell.level, c.max, cell.passed);
                      const spoken = cell.level == null ? t("rca.notTried") : t("rca.levelOf", { level: cell.level, max: c.max }) + (cell.passed ? t("rca.reachedSuffix") : "");
                      return (
                        <td key={c.key} className={cn("rounded px-1 py-1 text-center tabular-nums", TONE[cellTone(cell.level, c.max, c.pass)])}>
                          <span aria-hidden>{text}</span><span className="sr-only">{t("rca.cellLabel", { concept: c.name, text: spoken })}</span>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="text-xs">
                  <th scope="row" className="px-1 py-1 text-left">{t("rca.passRate")}</th>
                  {cs.map((c) => (
                    <td key={c.key} className="px-1 py-1 text-center font-semibold tabular-nums">
                      {c.rate == null ? "—" : t("rca.rateOf", { pct: pct(c.rate), passed: c.passed, tried: c.attempted })}
                    </td>
                  ))}
                </tr>
              </tfoot>
            </table>
          </div>
          {open && <ConceptDrill key={open} slug={slug} id={id} conceptKey={open} onClose={() => setOpen(null)} />}
        </div>
      )}

      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <p className="flex-1 font-display text-base font-bold">{t("rca.stuckTitle")}</p>
          <label className="flex items-center gap-2 text-xs text-muted">
            {t("rca.stuckAfter")}
            <select className="rounded-lg border border-line bg-surface px-2 py-1 text-sm text-ink" value={stuckDays} onChange={(e) => onStuckDays(Number(e.target.value))}>
              {STUCK_DAY_CHOICES.map((n) => <option key={n} value={n}>{t("rca.days", { count: n })}</option>)}
            </select>
          </label>
        </div>
        {data.stuck.length === 0 ? <p className="text-sm text-muted">{t("rca.stuckNone")}</p> : (
          <ul className="space-y-1.5">
            {data.stuck.map((s) => (
              <li key={s.user_id} className="flex flex-wrap items-center gap-2 rounded-xl border border-line px-3 py-2 text-sm">
                <span className="font-medium">{s.name}</span>
                {s.reasons.map((r) => (
                  <span key={r} className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-900">{t(`rca.reason.${r}`, { n: data.stuck_days, count: data.stuck_days })}</span>
                ))}
                <span className="ml-auto text-xs text-muted">{t("rca.stuckMeta", { attempts: s.attempts, best: s.best ?? "—", count: s.days_since })}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
