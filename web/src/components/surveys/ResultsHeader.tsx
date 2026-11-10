import { useTranslation } from "react-i18next";

import { HBars } from "@/components/charts";
import { Segmented } from "@/components/ui";
import type { Survey, TestStats } from "@/lib/orgs";

interface ScoredRow { id: string; text: string; scored?: boolean; correct_rate?: number | null }

/** Results header: latest-attempt / all-attempts toggle (retakes), and for knowledge tests the score distribution,
 *  average, pass rate and per-question difficulty (hardest first). */
export function ResultsHeader({ data, all, onAll }: { data: Survey & { results: ScoredRow[]; test: TestStats | null }; all: boolean; onAll: (v: boolean) => void }) {
  const { t } = useTranslation();
  const t2 = data.test;
  const hard = data.results.filter((q) => q.scored && q.correct_rate != null).sort((a, b) => (a.correct_rate ?? 0) - (b.correct_rate ?? 0));
  return (
    <div className="space-y-3">
      {data.max_attempts !== 1 && (
        <Segmented label={t("credSurvey.results.scope")} value={all ? "all" : "latest"} onChange={(v) => onAll(v === "all")}
          options={[{ value: "latest", label: t("credSurvey.results.latest") }, { value: "all", label: t("credSurvey.results.all") }]} />
      )}
      {t2 && (
        <>
          <div className="grid grid-cols-3 gap-2 text-sm">
            {[[t("credSurvey.results.takers"), String(t2.n)], [t("credSurvey.results.avg"), t2.avg_pct == null ? "—" : `${t2.avg_pct}%`],
              [t("credSurvey.results.passRate", { mark: t2.pass_mark }), t2.pass_rate == null ? "—" : `${Math.round(t2.pass_rate * 100)}%`]].map(([label, v]) => (
              <div key={label} className="rounded-xl bg-surface-2 p-2"><p className="text-xs text-muted">{label}</p><p className="font-display text-xl font-bold">{v}</p></div>
            ))}
          </div>
          <HBars title={t("credSurvey.results.dist")} valueLabel={t("org.count")} data={t2.distribution.map((d) => ({ label: `${d.label}%`, value: d.count }))} />
          {!!hard.length && (
            <HBars title={t("credSurvey.results.difficulty")} valueLabel={t("credSurvey.results.pctCorrect")} max={100} format={(v) => `${v}%`}
              data={hard.map((q) => ({ label: q.text, value: Math.round((q.correct_rate ?? 0) * 100) }))} />
          )}
        </>
      )}
    </div>
  );
}
