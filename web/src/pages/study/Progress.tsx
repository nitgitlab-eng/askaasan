import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Pin, PinOff, Send, Sparkles } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { localeOf } from "@/i18n/languages";
import { typeLabelKey } from "@/activities/typeLabel";
import { HBars, TimeBars } from "@/components/charts";
import { AskAnswer } from "@/components/study/AskAnswer";
import { KnowledgeGraph } from "@/components/study/KnowledgeGraph";
import { Button, Card, Segmented } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { downloadFile } from "@/lib/download";
import { study, type AskResult, type Insights, type Progress } from "@/lib/study";
import { studio } from "@/lib/studio";
import { useMe, useUpdatePreferences } from "@/lib/useMe";

export type ChartId = "minutes" | "xp" | "accuracy" | "skills" | "weekday";

const shortDay = (iso: string, locale: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(locale, { day: "numeric", month: "short" });

/** One chart by id — shared by this page and the Home pins. */
export function ProgressChart({ id, p }: { id: ChartId; p: Progress }) {
  const { t, i18n } = useTranslation();
  const locale = localeOf(i18n.language);
  switch (id) {
    case "minutes": return <TimeBars title={t("progress.charts.minutes")} valueLabel={t("progress.minutes")} data={p.minutes.map((d) => ({ label: shortDay(d.label, locale), value: d.value }))} />;
    case "xp": return <TimeBars title={t("progress.charts.xp")} valueLabel="XP" data={p.xp.map((d) => ({ label: shortDay(d.label, locale), value: d.value }))} />;
    case "weekday": return <HBars title={t("progress.charts.weekday")} valueLabel={t("progress.minutes")} data={p.by_weekday} />;
    case "accuracy": return <HBars title={t("progress.charts.accuracy")} valueLabel="%" max={100} format={(v) => `${v}%`} empty={t("progress.noData")}
      data={p.efficiency.map((e) => ({ label: t(typeLabelKey(e.type)), value: e.accuracy, note: t("progress.attempts", { count: e.attempts }) }))} />;
    case "skills": return <HBars title={t("progress.charts.skills")} valueLabel="%" max={100} format={(v) => `${v}%`} empty={t("progress.noData")}
      data={p.skills.filter((s) => s.mastery !== null).map((s) => ({ label: i18n.language === "ta" && s.name_ta ? s.name_ta : s.name, value: Math.round((s.mastery ?? 0) * 100), note: t("progress.used", { n: s.usage }) }))} />;
  }
}

function PinButton({ id }: { id: ChartId }) {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const update = useUpdatePreferences();
  const pins = me?.preferences.learning.progress_pins ?? [];
  const on = pins.includes(id);
  return (
    <button onClick={() => update.mutate({ learning: { progress_pins: on ? pins.filter((x) => x !== id) : [...pins, id].slice(-4) } })} aria-pressed={on}
      title={on ? t("progress.unpin") : t("progress.pin")} className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-muted hover:bg-surface-2">
      {on ? <PinOff className="h-3.5 w-3.5" /> : <Pin className="h-3.5 w-3.5" />} {on ? t("progress.unpin") : t("progress.pin")}
    </button>
  );
}

function Panel({ id, p, children }: { id?: ChartId; p?: Progress; children?: ReactNode }) {
  return (
    <Card className="space-y-1">
      {id && p ? <ProgressChart id={id} p={p} /> : children}
      {id && <div className="flex justify-end"><PinButton id={id} /></div>}
    </Card>
  );
}

export default function ProgressPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [days, setDays] = useState(30);
  const { data: p } = useQuery({ queryKey: ["progress", days], queryFn: () => study.progress(days) });
  const [ins, setIns] = useState<Insights | null>(null);
  const [insBusy, setInsBusy] = useState(false);
  const [q, setQ] = useState("");
  const [ans, setAns] = useState<AskResult | null>(null);
  const [askBusy, setAskBusy] = useState(false);
  const [err, setErr] = useState("");

  async function loadInsights() {
    setInsBusy(true);
    setErr("");
    try {
      setIns(await study.insights());
    } catch (e) {
      setErr(e instanceof ApiError && e.data?.code === "ai_budget_exceeded" ? t("paths.budget") : t("mentor.errors.generic"));
    } finally {
      setInsBusy(false);
    }
  }
  async function ask(e: FormEvent) {
    e.preventDefault();
    if (q.trim().length < 3) return;
    setAskBusy(true);
    setErr("");
    try {
      setAns(await study.ask(q.trim()));
    } catch (x) {
      setErr(x instanceof ApiError && x.data?.code === "ai_budget_exceeded" ? t("paths.budget") : t("mentor.errors.generic"));
    } finally {
      setAskBusy(false);
    }
  }
  const tot = p?.totals;
  const stat = (label: string, value: ReactNode) => <Card className="p-4"><p className="text-xs text-muted">{label}</p><p className="font-display text-2xl font-extrabold tabular-nums">{value}</p></Card>;

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-extrabold">{t("progress.title")}</h1>
          <p className="text-muted">{t("progress.sub")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link to="/progress/review" className="rounded-xl border-2 border-line px-3 py-1.5 text-sm font-semibold hover:border-accent">📄 {t("review2.link")}</Link>
          <Link to="/checkpoints" className="rounded-xl border-2 border-line px-3 py-1.5 text-sm font-semibold hover:border-accent">📈 {t("checkpoint.mine")}</Link>
          <button onClick={() => void downloadFile(studio.urls.progressXlsx(days), "my-progress.xlsx")} className="rounded-xl border-2 border-line px-3 py-1.5 text-sm font-semibold hover:border-accent">⬇ Excel</button>
        </div>
        <Segmented label={t("progress.range")} value={days} onChange={(v) => { setDays(v); void qc.invalidateQueries({ queryKey: ["progress"] }); }}
          options={[7, 30, 90, 365].map((d) => ({ value: d, label: t("progress.days", { count: d }) }))} />
      </header>

      {!p || !tot ? <p className="text-muted">{t("common.loading")}</p> : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {stat(t("progress.timeSpent"), t("progress.hm", { h: Math.floor(tot.minutes / 60), m: tot.minutes % 60 }))}
            {stat(t("progress.activeDays"), `${tot.active_days}/${p.days}`)}
            {stat(t("progress.firstTry"), tot.first_try_accuracy === null ? "—" : `${tot.first_try_accuracy}%`)}
            {stat(t("progress.lessonsDone"), tot.lessons)}
            {stat(t("progress.sessions"), tot.sessions)}
            {stat("XP", tot.xp)}
            {stat(t("progress.streak"), `🔥 ${tot.streak}`)}
            {stat(t("progress.best"), tot.best_streak)}
          </div>
          <p className="text-xs text-muted">{t("progress.estimate")}</p>

          <Card className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="flex items-center gap-2 font-display text-xl font-bold"><Sparkles className="h-5 w-5 text-accent" /> {t("progress.insights")}</h2>
              {!ins && <Button variant="outline" loading={insBusy} onClick={() => void loadInsights()}>{t("progress.getInsights")}</Button>}
            </div>
            {ins ? (
              <div className="space-y-2">
                <p className="font-display text-lg font-bold">{ins.headline}</p>
                <p>{ins.summary}</p>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div><p className="text-sm font-semibold">{t("progress.strengths")}</p><ul className="list-disc pl-5 text-sm">{ins.strengths.map((s) => <li key={s}>{s}</li>)}</ul></div>
                  <div><p className="text-sm font-semibold">{t("progress.focusNext")}</p><ul className="list-disc pl-5 text-sm">{ins.focus.map((s) => <li key={s}>{s}</li>)}</ul></div>
                </div>
                <p className="text-xs text-muted">{t("progress.insightNote", { week: ins.week })} <Link to="/today" className="font-semibold text-accent">{t("today.title")} →</Link></p>
              </div>
            ) : <p className="text-sm text-muted">{t("progress.insightsSub")}</p>}
          </Card>

          <Card className="space-y-3">
            <h2 className="font-display text-xl font-bold">{t("progress.ask")}</h2>
            <form onSubmit={(e) => void ask(e)} className="flex gap-2">
              <input value={q} onChange={(e) => setQ(e.target.value)} maxLength={300} placeholder={t("progress.askPh")} aria-label={t("progress.ask")}
                className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2 outline-none focus:border-accent" />
              <Button type="submit" loading={askBusy} disabled={q.trim().length < 3} aria-label={t("mentor.send")}><Send className="h-4 w-4" /></Button>
            </form>
            <div className="flex flex-wrap gap-2">
              {(t("progress.askExamples", { returnObjects: true }) as string[]).map((ex) => (
                <button key={ex} onClick={() => setQ(ex)} className="rounded-full border border-line px-3 py-1 text-xs hover:border-accent">{ex}</button>
              ))}
            </div>
            {ans && <AskAnswer ans={ans} unsupported={t("progress.askUnsupported")} empty={t("progress.noData")} />}
            {ans?.supported && <p className="text-xs text-muted">{t("progress.askHow")}</p>}
            {err && <p role="alert" className="text-sm text-bad">{err}</p>}
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel id="minutes" p={p} />
            <Panel id="xp" p={p} />
            <Panel id="skills" p={p} />
            <Panel id="accuracy" p={p} />
            <Panel id="weekday" p={p} />
            <Panel>
              <h2 className="font-display text-base font-bold">{t("progress.graph")}</h2>
              <KnowledgeGraph graph={p.graph} labels={{ skill: t("paths.skill"), lesson: t("progress.lesson"), mastery: t("progress.masteryWord"), empty: t("progress.noData") }} />
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
