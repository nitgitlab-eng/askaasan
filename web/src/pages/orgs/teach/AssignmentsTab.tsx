import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { RecordsExport } from "@/components/orgs/RecordsExport";
import { Button, Card, Segmented, Toggle } from "@/components/ui";
import { localeOf } from "@/i18n/languages";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { downloadFile } from "@/lib/download";
import { lab } from "@/lib/lab";
import { orgs, type Assignment } from "@/lib/orgs";
import { studio } from "@/lib/studio";
import { teach } from "@/lib/teach";

import { LessonDrilldown } from "./LessonDrilldown";
import { RoleplayAnalytics } from "./RoleplayAnalytics";
import { pct } from "./teachUtils";

type Kind = "course" | "scenario";

function AssignForm({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [kind, setKind] = useState<Kind>("course");
  const { data: courses } = useQuery({ queryKey: ["lab-courses"], queryFn: lab.courses });
  const { data: scenarios } = useQuery({ queryKey: ["teach-scenarios", slug], queryFn: () => teach.scenarios(slug), enabled: kind === "scenario" });
  const { data: groups } = useQuery({ queryKey: ["org-groups", slug], queryFn: () => orgs.groups(slug) });
  const { data: surveys } = useQuery({ queryKey: ["org-surveys", slug], queryFn: () => orgs.surveys(slug) });
  const [target, setTarget] = useState<number | "">("");
  const [group, setGroup] = useState<number | "">("");
  const [due, setDue] = useState("");
  const [note, setNote] = useState("");
  const [mandatory, setMandatory] = useState(false);
  const [survey, setSurvey] = useState<number | "">("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      await orgs.assign(slug, {
        ...(kind === "course" ? { curriculum_id: Number(target) } : { scenario_id: Number(target) }),
        group_id: group ? Number(group) : null, due_at: due ? new Date(`${due}T23:59:00`).toISOString() : null, note, mandatory,
        survey_id: survey ? Number(survey) : null,
      });
      setTarget(""); setNote(""); setDue(""); setSurvey(""); setMandatory(false);
      void qc.invalidateQueries({ queryKey: ["org-assignments", slug] });
    } catch (x) {
      const code = x instanceof ApiError ? x.data?.code : "";
      setErr(code === "lessons_not_ready" ? t("org.notReady") : code === "feature_off" ? t("teach.err.featureOff") : code === "survey_audience" ? t("teach.err.surveyAudience") : t("mentor.errors.generic"));
    } finally {
      setBusy(false);
    }
  }
  const field = "rounded-xl border-2 border-line bg-surface px-3 py-2";
  return (
    <Card>
      <form onSubmit={submit} className="grid gap-2 sm:grid-cols-2">
        <h2 className="font-display text-lg font-bold sm:col-span-2">{t("org.assignTitle")}</h2>
        <div className="sm:col-span-2">
          <Segmented label={t("org.assign")} value={kind} onChange={(v) => { setKind(v); setTarget(""); }}
            options={(["course", "scenario"] as const).map((k) => ({ value: k, label: t(`teach.kind.${k}`) }))} />
        </div>
        {kind === "course" ? (
          <select required value={target} onChange={(e) => setTarget(e.target.value ? Number(e.target.value) : "")} className={field} aria-label={t("org.course")}>
            <option value="">{t("org.pickCourse")}</option>
            {courses?.filter((c) => c.status === "ready").map((c) => <option key={c.id} value={c.id}>{c.cover_emoji} {c.title}</option>)}
          </select>
        ) : (
          <select required value={target} onChange={(e) => setTarget(e.target.value ? Number(e.target.value) : "")} className={field} aria-label={t("teach.pickScenario")}>
            <option value="">{t("teach.pickScenario")}</option>
            {scenarios?.map((s) => <option key={s.id} value={s.id}>{s.emoji} {s.title}</option>)}
          </select>
        )}
        <select value={group} onChange={(e) => setGroup(e.target.value ? Number(e.target.value) : "")} className={field} aria-label={t("org.className")}>
          <option value="">{t("org.wholeOrg")}</option>
          {groups?.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
        </select>
        <label className="flex items-center gap-2 text-sm">{t("org.due")}<input type="date" value={due} onChange={(e) => setDue(e.target.value)} className={cn(field, "flex-1")} /></label>
        <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} placeholder={t("org.notePlaceholder")} className={field} aria-label={t("org.note")} />
        <select value={survey} onChange={(e) => setSurvey(e.target.value ? Number(e.target.value) : "")} className={field} aria-label={t("teach.survey")}>
          <option value="">{t("teach.survey")}: {t("teach.noSurvey")}</option>
          {surveys?.filter((s) => s.status !== "closed").map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
        </select>
        <div className="rounded-xl border-2 border-line px-3">
          <Toggle checked={mandatory} onChange={setMandatory} label={t("teach.mandatory")} />
        </div>
        <p className="text-xs text-muted sm:col-span-2">{t("teach.mandatoryHint")}</p>
        <div className="sm:col-span-2"><Button type="submit" loading={busy} disabled={!target}>{t("org.assign")}</Button>{err && <span role="alert" className="ml-3 text-sm text-bad">{err}</span>}</div>
        {kind === "course" && courses && !courses.length && <p className="text-sm text-muted sm:col-span-2">{t("org.noCourses")}</p>}
        {kind === "scenario" && scenarios && !scenarios.length && <p className="text-sm text-muted sm:col-span-2">{t("teach.noScenarios")}</p>}
      </form>
    </Card>
  );
}

function CourseProgress({ slug, x }: { slug: string; x: Assignment }) {
  const { t } = useTranslation();
  const detail = useQuery({ queryKey: ["org-assignment", slug, x.id], queryFn: () => orgs.assignment(slug, x.id) });
  return (
    <div className="space-y-4">
      {detail.data?.rows && (
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted"><tr><th className="py-1">{t("org.learner")}</th><th>{t("org.progress")}</th><th>{t("org.kpi.avgScore")}</th><th /></tr></thead>
          <tbody>{detail.data.rows.map((r) => (
            <tr key={r.user_id} className="border-t border-line">
              <td className="py-1.5">{r.name}</td><td className="tabular-nums">{r.done}/{r.total}</td><td className="tabular-nums">{pct(r.avg_score)}</td>
              <td>{r.overdue && <span className="text-xs font-semibold text-bad">{t("org.reason.overdue")}</span>}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      <LessonDrilldown slug={slug} id={x.id} />
    </div>
  );
}

/** Cockpit "Assignments" tab (v2): courses and role-plays, mandatory flag, end-of-training survey, per-assignment drill-downs. */
export default function AssignmentsTab({ slug }: { slug: string }) {
  const { t, i18n } = useTranslation();
  const { data } = useQuery({ queryKey: ["org-assignments", slug], queryFn: () => orgs.assignments(slug) });
  const [open, setOpen] = useState<number | null>(null);
  const day = (d: string) => new Date(d).toLocaleDateString(localeOf(i18n.language));
  return (
    <div className="space-y-4">
      <AssignForm slug={slug} />
      <RecordsExport slug={slug} />
      {data?.map((x) => {
        const target = x.course ?? x.scenario;
        return (
          <Card key={x.id} className={cn("space-y-2", x.mandatory && "border-l-4 border-accent")}>
            <button className="flex w-full flex-wrap items-center gap-3 text-left" aria-expanded={open === x.id} onClick={() => setOpen(open === x.id ? null : x.id)}>
              <span className="text-2xl">{target?.emoji}</span>
              <div className="min-w-0 flex-1">
                <p className="font-semibold">{target?.title}</p>
                <p className="text-xs text-muted">
                  {t(`teach.kind.${x.kind ?? "course"}`)} · {x.group?.name ?? t("org.wholeOrg")} · {x.due_at ? t("org.dueOn", { d: day(x.due_at) }) : t("org.noDue")}
                  {x.survey && <> · {t("teach.surveyLinked", { title: x.survey.title })}</>}
                </p>
              </div>
              <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", x.mandatory ? "bg-accent text-accent-ink" : "bg-surface-2 text-muted")}>
                {x.mandatory ? t("teach.mandatory") : t("teach.optional")}
              </span>
              <span className="text-sm">{t("org.doneOf", { done: x.completed, n: x.learners })}</span>
              {x.rating != null && <span className="text-sm" title={t("org.learnerRating")}>⭐ {x.rating}</span>}
              {x.overdue > 0 && <span className="rounded-full bg-bad/15 px-2 py-0.5 text-xs font-semibold text-bad">{t("org.overdueN", { n: x.overdue })}</span>}
            </button>
            <div className="h-2 overflow-hidden rounded-full bg-surface-2"><div className="h-full rounded-full bg-accent" style={{ width: `${x.avg_pct * 100}%` }} /></div>
            {x.course && (
              <button onClick={() => void downloadFile(studio.urls.pptx(x.course!.id), "course.pptx")} className="flex items-center gap-1 text-xs font-semibold text-accent"><Download className="h-3.5 w-3.5" /> {t("studio.classSlides")}</button>
            )}
            {open === x.id && (x.kind === "scenario" ? <RoleplayAnalytics slug={slug} id={x.id} /> : <CourseProgress slug={slug} x={x} />)}
          </Card>
        );
      })}
    </div>
  );
}
