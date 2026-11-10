import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Sparkles } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { localeOf } from "@/i18n/languages";
import { cn } from "@/lib/cn";
import { downloadFile } from "@/lib/download";
import { teach, type RpAttempt, type RpStatus } from "@/lib/teach";

import { RoleplayCompetency } from "./RoleplayCompetency";
import { aiError, fmtDuration } from "./teachUtils";

const STATUS_COLOR: Record<RpStatus, string> = { done: "bg-good/15 text-good", in_progress: "bg-amber-100 text-amber-800", not_started: "bg-surface-2 text-muted" };

function Feedback({ a }: { a: RpAttempt }) {
  const { t } = useTranslation();
  const r = a.result;
  if (!r) return null;
  return (
    <div className="space-y-2 rounded-xl bg-surface-2 p-3 text-sm">
      <p>{r.summary}</p>
      <div className="flex flex-wrap gap-2">
        {r.competencies.map((c) => <span key={c.name} className="rounded-full bg-surface px-2 py-0.5 text-xs">{c.name}: {c.score}/5</span>)}
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <div><p className="font-semibold">💪 {t("teach.strengths")}</p><ul className="list-disc pl-5">{r.strengths.map((x) => <li key={x}>{x}</li>)}</ul></div>
        <div><p className="font-semibold">🎯 {t("teach.improvements")}</p><ul className="list-disc pl-5">{r.improvements.map((x) => <li key={x}>{x}</li>)}</ul></div>
      </div>
    </div>
  );
}

function Attempts({ slug, id, uid }: { slug: string; id: number; uid: number }) {
  const { t, i18n } = useTranslation();
  const { data } = useQuery({ queryKey: ["teach-rp-learner", slug, id, uid], queryFn: () => teach.roleplayLearner(slug, id, uid) });
  const [open, setOpen] = useState<number | null>(null);
  if (!data) return <p className="text-sm text-muted">{t("common.loading")}</p>;
  return (
    <div className="space-y-2">
      <p className="font-semibold">{t("teach.attemptsOf", { name: data.name })}</p>
      <ol className="space-y-2">
        {data.attempts.map((a, i) => (
          <li key={a.id} className="space-y-1">
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span className="w-24 shrink-0 text-muted">{t("teach.attemptN", { n: i + 1 })}</span>
              <div className="h-2 min-w-24 flex-1 overflow-hidden rounded-full bg-surface-2" aria-hidden><div className="h-full rounded-full bg-accent" style={{ width: `${a.score ?? 0}%` }} /></div>
              <span className="w-12 text-right font-semibold tabular-nums">{a.score ?? "—"}</span>
              <span className="text-xs text-muted">{new Date(a.started_at).toLocaleString(localeOf(i18n.language), { dateStyle: "medium", timeStyle: "short" })} · {fmtDuration(a.duration)}</span>
              {a.result ? (
                <button className="text-xs font-semibold text-accent" onClick={() => setOpen(open === a.id ? null : a.id)}>{open === a.id ? t("teach.hideFeedback") : t("teach.coachFeedback")}</button>
              ) : <span className="text-xs text-muted">{t("teach.notFinished")}</span>}
            </div>
            {open === a.id && <Feedback a={a} />}
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Per-learner results for one assigned role-play: table, attempt history, AI class insights, CSV/Excel. */
export function RoleplayAnalytics({ slug, id }: { slug: string; id: number }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [stuckDays, setStuckDays] = useState(7);
  const { data, error } = useQuery({ queryKey: ["teach-rp", slug, id, stuckDays], queryFn: () => teach.roleplay(slug, id, stuckDays), placeholderData: (prev) => prev });
  const [learner, setLearner] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  if (error) return <p className="text-sm text-bad">{aiError(t, error)}</p>;
  if (!data) return <p className="text-sm text-muted">{t("common.loading")}</p>;
  if (data.no_class) return <p className="text-sm text-muted">{t("teachScope.noClass")}</p>;
  const s = data.summary;
  const fmt = (d: string | null) => (d ? new Date(d).toLocaleDateString(localeOf(i18n.language), { day: "numeric", month: "short" }) : "—");
  async function gen() {
    setBusy(true);
    setErr("");
    try {
      const r = await teach.roleplayInsights(slug, id);
      qc.setQueryData(["teach-rp", slug, id, stuckDays], { ...data!, insights: r.insights });
    } catch (e) {
      setErr(aiError(t, e));
    } finally {
      setBusy(false);
    }
  }
  const ins = data.insights;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span>{t("teach.summary", { done: s.done, progress: s.in_progress, none: s.not_started })}</span>
        {s.avg_best != null && <span className="text-muted">· {t("teach.avgBest", { v: s.avg_best })}</span>}
        <span className="ml-auto flex gap-1">
          <Button variant="ghost" className="py-1 text-sm" onClick={() => void downloadFile(teach.urls.roleplayCsv(slug, id, stuckDays), "roleplay.csv")}><Download className="h-4 w-4" /> CSV</Button>
          <Button variant="ghost" className="py-1 text-sm" onClick={() => void downloadFile(teach.urls.roleplayXlsx(slug, id, stuckDays), "roleplay.xlsx")}><Download className="h-4 w-4" /> Excel</Button>
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted">
            <tr>{(["learner", "status", "latest", "best", "attempts", "duration", "lastAttempt"] as const).map((k) => <th key={k} className="px-1 py-1">{t(`teach.col.${k}`)}</th>)}</tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.user_id} className={cn("cursor-pointer border-t border-line hover:bg-surface-2", learner === r.user_id && "bg-surface-2")}
                onClick={() => setLearner(learner === r.user_id ? null : r.user_id)}>
                <td className="px-1 py-1.5 font-medium"><button className="text-left hover:text-accent" aria-expanded={learner === r.user_id}>{r.name}</button></td>
                <td className="px-1"><span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", STATUS_COLOR[r.status])}>{t(`teach.status.${r.status}`)}</span></td>
                <td className="px-1 tabular-nums">{r.latest ?? "—"}</td>
                <td className="px-1 font-semibold tabular-nums">{r.best ?? "—"}</td>
                <td className="px-1 tabular-nums">{r.attempts}</td>
                <td className="px-1 tabular-nums">{fmtDuration(r.last_duration)}</td>
                <td className="px-1">{fmt(r.last_attempt)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {learner != null && <Attempts slug={slug} id={id} uid={learner} />}
      {data.competency && <RoleplayCompetency slug={slug} id={id} data={data.competency} stuckDays={stuckDays} onStuckDays={setStuckDays} />}
      <div className="space-y-2 rounded-xl border border-line p-3">
        <div className="flex flex-wrap items-center gap-2">
          <p className="flex flex-1 items-center gap-2 font-display text-base font-bold"><Sparkles className="h-4 w-4 text-accent" /> {t("teach.insightsTitle")}</p>
          {ins && <span className="text-xs text-muted">{t("teach.updated", { d: fmt(ins.updated_at) })}</span>}
          <Button variant="outline" className="py-1 text-sm" loading={busy} onClick={() => void gen()}>{ins ? t("teach.regenerate") : t("teach.generate")}</Button>
        </div>
        <p className="text-xs text-muted">{t("teach.aiCost")}</p>
        {err && <p role="alert" className="text-sm text-bad">{err}</p>}
        {ins && (
          <div className="space-y-2 text-sm">
            <p className="font-semibold">{ins.headline}</p>
            <div className="grid gap-3 sm:grid-cols-3">
              {([["wentWell", ins.strengths], ["struggled", ins.struggles], ["tips", ins.teaching_tips]] as const).map(([k, list]) => (
                <div key={k}><p className="font-semibold">{t(`teach.${k}`)}</p><ul className="list-disc pl-5">{list.map((x) => <li key={x}>{x}</li>)}</ul></div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
