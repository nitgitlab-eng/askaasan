import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarPlus, Download, MonitorPlay, ShieldCheck, XCircle } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { PageError } from "@/components/PageState";
import { Button, Card, Field, Toggle } from "@/components/ui";
import { localeOf } from "@/i18n/languages";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { confirmDialog } from "@/lib/dialog";
import { downloadFile } from "@/lib/download";
import { orgs, RANK, type Role } from "@/lib/orgs";
import {
  blankOrgRunForm, ORG_RUN_CODE_FIELD, orgWorkshops, REPORT_KINDS, runsKey, splitRuns, validateOrgRunForm,
  type NamedRef, type OrgRun, type OrgRunForm, type SeatQuota,
} from "@/lib/orgWorkshops";
import { school } from "@/lib/school";

const selectCls = "w-full rounded-xl border-2 border-line bg-surface px-3 py-2.5 outline-none transition focus:border-accent";

/** PDF / PPTX / CSV for one run (permission-checked downloads; teachers get their classes only). */
export function ReportLinks({ slug, runId }: { slug: string; runId: number }) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState(false);
  async function get(kind: (typeof REPORT_KINDS)[number]) {
    setBusy(kind);
    setErr(false);
    try {
      await downloadFile(orgWorkshops.reportUrl(slug, runId, kind), `workshop-report-${runId}.${kind}`);
    } catch {
      setErr(true);
    } finally {
      setBusy("");
    }
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-sm font-semibold text-muted">{t("orgWs.report")}</span>
      {REPORT_KINDS.map((k) => (
        <Button key={k} variant="ghost" className="py-1.5 text-sm" loading={busy === k} onClick={() => void get(k)} aria-label={t("orgWs.reportAs", { kind: k.toUpperCase() })}>
          <Download className="h-4 w-4" aria-hidden /> {k.toUpperCase()}
        </Button>
      ))}
      {err && <span role="alert" className="text-sm text-bad">{t("orgWs.reportFailed")}</span>}
    </div>
  );
}

function PickList({ legend, items, picked, onChange, empty }: { legend: string; items: NamedRef[]; picked: number[]; onChange: (ids: number[]) => void; empty: string }) {
  return (
    <fieldset className="space-y-1.5">
      <legend className="text-sm font-medium">{legend}</legend>
      {items.length === 0 ? <p className="text-sm text-muted">{empty}</p> : (
        <div className="flex max-h-48 flex-wrap gap-2 overflow-y-auto">
          {items.map((g) => {
            const on = picked.includes(g.id);
            return (
              <label key={g.id} className={cn("flex max-w-full cursor-pointer items-center gap-2 rounded-full border-2 px-3 py-1.5 text-sm font-semibold transition", on ? "border-accent bg-accent/10" : "border-line bg-surface hover:border-accent")}>
                <input type="checkbox" className="shrink-0 accent-[var(--accent)]" checked={on} onChange={(e) => onChange(e.target.checked ? [...picked, g.id] : picked.filter((x) => x !== g.id))} />
                <span className="min-w-0 break-words">{g.name}</span>
              </label>
            );
          })}
        </div>
      )}
    </fieldset>
  );
}

/** Schedule a batch run: template, IST date and time, classes and/or cohorts, optional proctoring, join windows. */
export function ScheduleForm({ slug, onDone }: { slug: string; onDone: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: templates } = useQuery({ queryKey: ["org-workshop-templates", slug], queryFn: () => orgWorkshops.templates(slug) });
  const { data: groups } = useQuery({ queryKey: ["org-groups", slug], queryFn: () => orgs.groups(slug) });
  const { data: cohorts } = useQuery({ queryKey: ["school-cohorts", slug], queryFn: () => school.cohorts(slug) });
  const [f, setF] = useState<OrgRunForm>(blankOrgRunForm);
  const [errors, setErrors] = useState<Partial<Record<keyof OrgRunForm, string>>>({});
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const set = <K extends keyof OrgRunForm>(k: K, v: OrgRunForm[K]) => setF((x) => ({ ...x, [k]: v }));
  const errText = (k: keyof OrgRunForm) => (errors[k] ? t(`orgWs.err.${errors[k]}`, { defaultValue: t("orgWs.err.save") }) : undefined);
  const tpl = templates?.find((w) => w.slug === f.workshop_slug);
  const proctorOn = f.proctoring ? f.proctoring !== "off" : !!tpl?.proctoring && tpl.proctoring !== "off";

  function pickTemplate(slugValue: string) {
    const w = templates?.find((x) => x.slug === slugValue);
    setF((x) => ({ ...x, workshop_slug: slugValue, proctoring: w?.proctoring && w.proctoring !== "off" ? w.proctoring : "off" }));
  }

  async function save() {
    const { errors: errs, body } = validateOrgRunForm(f, Date.now());
    setErrors(errs);
    setProblem("");
    if (!body) return;
    setBusy(true);
    try {
      await orgWorkshops.create(slug, body);
      await qc.invalidateQueries({ queryKey: runsKey(slug) });
      onDone();
    } catch (e) {
      const code = e instanceof ApiError ? String(e.data?.code ?? "") : "";
      const field = ORG_RUN_CODE_FIELD[code];
      if (field) setErrors({ [field]: code });
      else setProblem(t(`orgWs.err.${code || "save"}`, { defaultValue: t("orgWs.err.save") }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-4 border-2 border-accent/40">
      <h2 className="font-display text-xl font-bold">{t("orgWs.schedule")}</h2>
      <div className="space-y-1">
        <label htmlFor="ows-template" className="block text-sm font-medium">{t("orgWs.template")}</label>
        <select id="ows-template" className={cn(selectCls, errors.workshop_slug && "border-bad")} value={f.workshop_slug} onChange={(e) => pickTemplate(e.target.value)} aria-invalid={!!errors.workshop_slug}>
          <option value="">{t("orgWs.pickTemplate")}</option>
          {templates?.map((w) => <option key={w.slug} value={w.slug}>{w.title} · {t("workshop.list.minutes", { count: w.duration_minutes })}</option>)}
        </select>
        {errors.workshop_slug && <span role="alert" className="text-sm text-bad">{errText("workshop_slug")}</span>}
        {tpl?.summary && <p className="text-xs text-muted">{tpl.summary}</p>}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("orgWs.date")} name="ows-date" type="date" value={f.date} onChange={(e) => set("date", e.target.value)} error={errText("date")} />
        <Field label={t("orgWs.time")} name="ows-time" type="time" value={f.time} onChange={(e) => set("time", e.target.value)} />
      </div>
      <p className="-mt-2 text-xs text-muted">{t("adminWs.runs.istNote")}</p>
      <PickList legend={t("orgWs.classes")} items={groups ?? []} picked={f.groups} onChange={(v) => set("groups", v)} empty={t("orgWs.noClasses")} />
      <PickList legend={t("orgWs.cohorts")} items={(cohorts ?? []).map((c) => ({ id: c.id, name: c.name }))} picked={f.cohorts} onChange={(v) => set("cohorts", v)} empty={t("orgWs.noCohorts")} />
      {errors.groups && <p role="alert" className="-mt-2 text-sm text-bad">{errText("groups")}</p>}
      <p className="-mt-2 text-xs text-muted">{t("orgWs.audienceHint")}</p>
      <div className="space-y-1 rounded-2xl bg-surface-2 p-3">
        <Toggle label={t("orgWs.proctoring")} checked={proctorOn} onChange={(v) => set("proctoring", v ? "activity" : "off")} />
        <p className="text-xs text-muted">{t("orgWs.proctoringHint")}</p>
        {proctorOn && (
          <label className="flex items-center gap-2 pt-1 text-sm">
            <input type="checkbox" className="accent-[var(--accent)]" checked={f.proctoring === "strict"} onChange={(e) => set("proctoring", e.target.checked ? "strict" : "activity")} />
            {t("orgWs.strict")}
          </label>
        )}
        {errors.proctoring && <span role="alert" className="text-sm text-bad">{errText("proctoring")}</span>}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("adminWs.runs.lateJoin")} name="ows-late" type="number" min={0} max={60} inputMode="numeric" value={f.late_join_minutes} onChange={(e) => set("late_join_minutes", e.target.value)} error={errText("late_join_minutes")} />
        <Field label={t("adminWs.runs.lobby")} name="ows-lobby" type="number" min={5} max={60} inputMode="numeric" value={f.lobby_opens_minutes} onChange={(e) => set("lobby_opens_minutes", e.target.value)} error={errText("lobby_opens_minutes")} />
      </div>
      <p className="text-xs text-muted">{t("orgWs.enrolNote")}</p>
      {problem && <p role="alert" className="text-sm text-bad">{problem}</p>}
      <div className="flex flex-wrap gap-2">
        <Button loading={busy} onClick={() => void save()}>{t("orgWs.create")}</Button>
        <Button variant="ghost" onClick={onDone}>{t("adminWs.runs.cancelEdit")}</Button>
      </div>
    </Card>
  );
}

function RunCard({ slug, run, canManage }: { slug: string; run: OrgRun; canManage: boolean }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const fmt = (iso: string) => new Date(iso).toLocaleString(localeOf(i18n.language), { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata" });
  const audience = [...(run.groups ?? []), ...(run.cohorts ?? [])].map((g) => g.name).join(", ");
  const cancellable = canManage && (run.status === "scheduled" || run.status === "draft");
  const hasData = run.status === "live" || run.status === "ended";

  async function cancel() {
    if (!(await confirmDialog(t("orgWs.cancelConfirm"), { danger: true, ok: t("orgWs.cancel") }))) return;
    setBusy(true);
    setErr("");
    try {
      await orgWorkshops.cancel(slug, run.id);
      await qc.invalidateQueries({ queryKey: runsKey(slug) });
    } catch (e) {
      const code = e instanceof ApiError ? String(e.data?.code ?? "") : "";
      setErr(t(`orgWs.err.${code || "action"}`, { defaultValue: t("orgWs.err.action") }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-3" data-testid={`org-run-${run.id}`}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="break-words font-display text-lg font-bold">{run.workshop.title}</h3>
          <p className="text-sm text-muted">{fmt(run.starts_at)} IST</p>
          {audience && <p className="break-words text-sm">{t("orgWs.for", { names: audience })}</p>}
        </div>
        <span className={cn("rounded-full px-2.5 py-0.5 text-xs font-bold uppercase",
          run.status === "live" ? "bg-good/15 text-good" : run.status === "cancelled" ? "bg-bad/15 text-bad" : run.status === "scheduled" ? "bg-accent/15 text-accent" : "bg-surface-2 text-muted")}>
          {t(`adminWs.runs.status.${run.status}`, { defaultValue: run.status })}
        </span>
        {run.proctoring && run.proctoring !== "off" && <span className="flex items-center gap-1 rounded-full bg-surface-2 px-2.5 py-0.5 text-xs font-bold"><ShieldCheck className="h-3.5 w-3.5" aria-hidden /> {t(`adminWs.mode.${run.proctoring}`)}</span>}
      </div>
      {run.enrolled !== undefined && (
        <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
          <span>{t("adminWs.runs.stat.enrolled")}: <b>{run.enrolled}</b></span>
          {run.started !== undefined && <span>{t("adminWs.runs.stat.started")}: <b>{run.started}</b></span>}
          {run.finished !== undefined && <span>{t("adminWs.runs.stat.finished")}: <b>{run.finished}</b></span>}
          {run.passed !== undefined && <span>{t("adminWs.runs.stat.passed")}: <b>{run.passed}</b></span>}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {run.status !== "cancelled" && (
          <Link to={`/org/${slug}/workshops/${run.id}/live`} className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 font-semibold text-accent-ink shadow-sm hover:brightness-105">
            <MonitorPlay className="h-4 w-4" aria-hidden /> {t("orgWs.openDashboard")}
          </Link>
        )}
        {cancellable && <Button variant="ghost" className="py-2 text-bad" loading={busy} onClick={() => void cancel()}><XCircle className="h-4 w-4" aria-hidden /> {t("orgWs.cancel")}</Button>}
      </div>
      {hasData && <ReportLinks slug={slug} runId={run.id} />}
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
    </Card>
  );
}

function Quota({ q }: { q: SeatQuota }) {
  const { t } = useTranslation();
  return <p className={cn("text-sm", q.limit === 0 || q.used >= q.limit ? "font-semibold text-bad" : "text-muted")} data-testid="seat-quota">{q.limit === 0 ? t("orgWs.quotaNone") : t("orgWs.quota", { used: q.used, limit: q.limit })}</p>;
}

/** Cockpit "Workshops": owners and admins schedule batch runs; teachers open the dashboards (their classes only). */
export default function WorkshopsTab({ slug, role }: { slug: string; role: Role }) {
  const { t } = useTranslation();
  const canManage = RANK[role] >= RANK.admin;
  const { data, error, refetch } = useQuery({ queryKey: runsKey(slug), queryFn: () => orgWorkshops.runs(slug) });
  const [editing, setEditing] = useState(false);
  if (error) {
    if (error instanceof ApiError && error.data?.code === "feature_off") return <Card className="text-muted">{t("orgWs.off")}</Card>;
    return <PageError error={error} onRetry={() => void refetch()} />;
  }
  if (!data) return <p className="text-muted">{t("common.loading")}</p>;
  const { upcoming, past } = splitRuns(data.runs);
  return (
    <div className="space-y-4">
      <Card className="space-y-1">
        <h2 className="font-display text-lg font-bold">{t("orgWs.title")}</h2>
        <p className="text-sm text-muted">{canManage ? t("orgWs.sub") : t("orgWs.subTeacher")}</p>
        {data.quota && <Quota q={data.quota} />}
      </Card>
      {canManage && (editing ? <ScheduleForm slug={slug} onDone={() => setEditing(false)} /> : (
        <Button onClick={() => setEditing(true)}><CalendarPlus className="h-4 w-4" aria-hidden /> {t("orgWs.schedule")}</Button>
      ))}
      <section className="space-y-3">
        <h2 className="font-display text-lg font-bold">{t("orgWs.upcoming")}</h2>
        {upcoming.length === 0 ? <Card className="text-muted">{t("orgWs.noUpcoming")}</Card> : upcoming.map((r) => <RunCard key={r.id} slug={slug} run={r} canManage={canManage} />)}
      </section>
      {past.length > 0 && (
        <section className="space-y-3">
          <h2 className="font-display text-lg font-bold">{t("orgWs.past")}</h2>
          {past.map((r) => <RunCard key={r.id} slug={slug} run={r} canManage={canManage} />)}
        </section>
      )}
    </div>
  );
}
