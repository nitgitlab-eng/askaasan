import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, CalendarPlus, FlaskConical, Megaphone, Pencil, Presentation, Send, XCircle } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { PageError } from "@/components/PageState";
import { Button, Card, Field, Toggle } from "@/components/ui";
import { localeOf } from "@/i18n/languages";
import { ApiError } from "@/lib/api";
import { rupees } from "@/lib/billing";
import { cn } from "@/lib/cn";
import { confirmDialog } from "@/lib/dialog";
import { adminOrgWorkshops, SEATS_MAX, type AdminOrgWorkshops } from "@/lib/orgWorkshops";
import {
  blankRunForm, CAPACITY_MAX, RUN_CODE_FIELD, runFormOf, validateRunForm, workshops,
  type AdminRun, type AdminTemplate, type RunForm,
} from "@/lib/workshops";

function TemplateRow({ w }: { w: AdminTemplate }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  /** Creates a staff-only test run (enrolled), opens its session, and drops the admin straight into it. */
  async function testRun() {
    setBusy(true);
    setErr("");
    try {
      const { run_id, session_id } = await workshops.adminTestRun(w.slug);
      navigate(`/workshops/session/${session_id ?? (await workshops.openSession(run_id)).id}`);
    } catch {
      setErr(t("adminWs.failed"));
      setBusy(false);
    }
  }
  return (
    <Card className="flex flex-wrap items-center gap-3">
      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-accent/10 text-accent"><Presentation className="h-5 w-5" aria-hidden /></span>
      <div className="min-w-0 flex-1">
        <h2 className="break-words font-display text-lg font-bold">{w.title}</h2>
        {w.summary && <p className="break-words text-sm text-muted">{w.summary}</p>}
        <p className="[overflow-wrap:anywhere] text-xs text-muted">
          {w.slug} · {t("workshop.list.minutes", { count: w.duration_minutes })}
          {w.proctoring && ` · ${t("adminWs.proctoring", { mode: t(`adminWs.mode.${w.proctoring}`) })}`}
        </p>
        {err && <p role="alert" className="text-sm text-bad">{err}</p>}
      </div>
      <Button variant="outline" loading={busy} onClick={() => void testRun()}><FlaskConical className="h-4 w-4" /> {t("adminWs.testRun")}</Button>
    </Card>
  );
}

const selectCls = "w-full rounded-xl border-2 border-line bg-surface px-3 py-2.5 outline-none transition focus:border-accent";

/** Create or edit a run. Times are typed in India time; the price is in rupees and goes to the server in paise. */
function RunEditor({ templates, run, onDone }: { templates: AdminTemplate[]; run: AdminRun | null; onDone: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [f, setF] = useState<RunForm>(() => (run ? runFormOf(run) : blankRunForm()));
  const [errors, setErrors] = useState<Partial<Record<keyof RunForm, string>>>({});
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const priceLocked = !!run && run.enrolled > 0;
  const set = <K extends keyof RunForm>(k: K, v: RunForm[K]) => setF((x) => ({ ...x, [k]: v }));
  const errText = (k: keyof RunForm) => (errors[k] ? t(`adminWs.runs.err.${errors[k]}`, { defaultValue: t("adminWs.runs.err.save") }) : undefined);
  const workshopLocked = !!run && run.status !== "draft";

  async function save() {
    const { errors: errs, body } = validateRunForm(f, Date.now());
    setErrors(errs);
    setProblem("");
    if (!body) return;
    setBusy(true);
    try {
      if (run) {
        const { workshop_slug, ...rest } = body;
        // The template can change only while a draft; the price not at all once someone has paid.
        await workshops.adminUpdateRun(run.id, { ...rest, ...(workshopLocked ? {} : { workshop_slug }), ...(priceLocked ? { price_paise: undefined } : {}) });
      } else await workshops.adminCreateRun(body);
      await qc.invalidateQueries({ queryKey: ["admin-workshop-runs"] });
      onDone();
    } catch (e) {
      // The server answers {code}: beside its field when it has one, else under the form.
      const code = e instanceof ApiError ? String(e.data?.code ?? "") : "";
      const field = RUN_CODE_FIELD[code];
      if (field) setErrors({ [field]: code });
      else setProblem(t(`adminWs.runs.err.${code || "save"}`, { defaultValue: t("adminWs.runs.err.save") }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-4 border-2 border-accent/40">
      <h2 className="font-display text-xl font-bold">{run ? t("adminWs.runs.edit") : t("adminWs.runs.new")}</h2>
      <div className="space-y-1">
        <label htmlFor="run-template" className="block text-sm font-medium">{t("adminWs.runs.template")}</label>
        <select id="run-template" className={cn(selectCls, errors.workshop_slug && "border-bad")} value={f.workshop_slug} disabled={workshopLocked} onChange={(e) => set("workshop_slug", e.target.value)} aria-invalid={!!errors.workshop_slug}>
          <option value="">{t("adminWs.runs.pickTemplate")}</option>
          {templates.map((w) => <option key={w.slug} value={w.slug}>{w.title}</option>)}
        </select>
        {errors.workshop_slug && <span role="alert" className="text-sm text-bad">{errText("workshop_slug")}</span>}
        {workshopLocked && <span className="block text-xs text-muted">{t("adminWs.runs.err.workshop_locked")}</span>}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("adminWs.runs.date")} name="run-date" type="date" value={f.date} onChange={(e) => set("date", e.target.value)} error={errText("date")} />
        <Field label={t("adminWs.runs.time")} name="run-time" type="time" value={f.time} onChange={(e) => set("time", e.target.value)} />
      </div>
      <p className="-mt-2 text-xs text-muted">{t("adminWs.runs.istNote")}</p>
      <Field label={t("adminWs.runs.capacity")} name="run-capacity" type="number" min={0} max={CAPACITY_MAX} inputMode="numeric" value={f.capacity} onChange={(e) => set("capacity", e.target.value)} error={errText("capacity")} />
      <p className="-mt-2 text-xs text-muted">{t("adminWs.runs.capacityHint")}</p>
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">{t("adminWs.runs.pricing")}</legend>
        <div role="radiogroup" aria-label={t("adminWs.runs.pricing")} className="flex gap-2">
          {([false, true] as const).map((paid) => (
            <button key={String(paid)} type="button" role="radio" aria-checked={f.paid === paid} disabled={priceLocked} onClick={() => set("paid", paid)}
              className={cn("rounded-full border-2 px-4 py-1.5 text-sm font-semibold transition disabled:opacity-60", f.paid === paid ? "border-accent bg-accent text-accent-ink" : "border-line bg-surface hover:border-accent")}>
              {paid ? t("adminWs.runs.paid") : t("adminWs.runs.free")}
            </button>
          ))}
        </div>
        {f.paid && (
          <>
            <Field label={t("adminWs.runs.price")} name="run-price" inputMode="decimal" value={f.price} disabled={priceLocked} onChange={(e) => set("price", e.target.value)} error={errText("price")} />
            <p className="text-xs text-muted">{t("adminWs.runs.priceHint")}</p>
          </>
        )}
        {priceLocked && <p className="text-xs text-muted">{t("adminWs.runs.priceLocked")}</p>}
      </fieldset>
      <div className="space-y-1">
        <label htmlFor="run-proctoring" className="block text-sm font-medium">{t("adminWs.runs.proctoring")}</label>
        <select id="run-proctoring" className={cn(selectCls, errors.proctoring && "border-bad")} aria-invalid={!!errors.proctoring} value={f.proctoring} onChange={(e) => set("proctoring", e.target.value as RunForm["proctoring"])}>
          <option value="">{t("adminWs.runs.proctorDefault")}</option>
          {(["off", "activity", "strict"] as const).map((m) => <option key={m} value={m}>{t(`adminWs.mode.${m}`)}</option>)}
        </select>
        {errors.proctoring && <span role="alert" className="text-sm text-bad">{errText("proctoring")}</span>}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("adminWs.runs.lateJoin")} name="run-late" type="number" min={0} max={60} inputMode="numeric" value={f.late_join_minutes} onChange={(e) => set("late_join_minutes", e.target.value)} error={errText("late_join_minutes")} />
        <Field label={t("adminWs.runs.lobby")} name="run-lobby" type="number" min={5} max={60} inputMode="numeric" value={f.lobby_opens_minutes} onChange={(e) => set("lobby_opens_minutes", e.target.value)} error={errText("lobby_opens_minutes")} />
      </div>
      {problem && <p role="alert" className="text-sm text-bad">{problem}</p>}
      <div className="flex flex-wrap gap-2">
        <Button loading={busy} onClick={() => void save()}>{run ? t("adminWs.runs.save") : t("adminWs.runs.create")}</Button>
        <Button variant="ghost" onClick={onDone}>{t("adminWs.runs.cancelEdit")}</Button>
      </div>
    </Card>
  );
}

function StatsCard({ id }: { id: number }) {
  const { t } = useTranslation();
  const { data, error } = useQuery({ queryKey: ["admin-workshop-run-stats", id], queryFn: () => workshops.adminStats(id) });
  if (error) return <p role="alert" className="text-sm text-bad">{t("adminWs.runs.err.action")}</p>;
  if (!data) return <p className="text-sm text-muted">{t("common.loading")}</p>;
  const cells: [string, string | number][] = [
    ["enrolled", data.enrolled], ["joined", data.joined], ...(data.started !== undefined ? [["started", data.started] as [string, number]] : []), ["finished", data.finished], ["passed", data.passed],
    ["avgScore", data.avg_score === null ? "—" : `${Math.round(data.avg_score * 100)}%`],
    ["avgMinutes", data.avg_minutes === null ? "—" : t("workshop.list.minutes", { count: Math.round(data.avg_minutes) })],
    ["helpRequests", data.help_requests],
  ];
  return (
    <div data-testid={`stats-${id}`} className="space-y-2 rounded-2xl bg-surface-2 p-3">
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {cells.map(([k, v]) => (
          <div key={k} className="min-w-0">
            <dt className="break-words text-xs text-muted">{t(`adminWs.runs.stat.${k}`)}</dt>
            <dd className="font-display text-lg font-bold tabular-nums">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="text-xs text-muted">{t("adminWs.runs.statsNote")}</p>
    </div>
  );
}

function RunRow({ run, onEdit }: { run: AdminRun; onEdit: () => void }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [stats, setStats] = useState(false);
  const fmt = (iso: string) => new Date(iso).toLocaleString(localeOf(i18n.language), { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata" });
  const editable = run.status === "draft" || run.status === "scheduled";

  async function act(name: string, fn: () => Promise<unknown>, confirmText?: string, danger = false) {
    if (confirmText && !(await confirmDialog(confirmText, { danger, ok: t(`adminWs.runs.${name}`) }))) return;
    setBusy(name);
    setErr("");
    try {
      await fn();
      await qc.invalidateQueries({ queryKey: ["admin-workshop-runs"] });
    } catch (e) {
      const code = e instanceof ApiError ? String(e.data?.code ?? "") : "";
      setErr(t(`adminWs.runs.err.${code || "action"}`, { defaultValue: t("adminWs.runs.err.action") }));
    } finally {
      setBusy("");
    }
  }

  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="break-words font-display text-lg font-bold">{run.workshop.title}</h3>
          <p className="text-sm text-muted">{fmt(run.starts_at)} IST</p>
        </div>
        <span className={cn("rounded-full px-2.5 py-0.5 text-xs font-bold uppercase",
          run.status === "live" ? "bg-good/15 text-good" : run.status === "cancelled" ? "bg-bad/15 text-bad" : run.status === "scheduled" ? "bg-accent/15 text-accent" : "bg-surface-2 text-muted")}>
          {t(`adminWs.runs.status.${run.status}`, { defaultValue: run.status })}
        </span>
        <span className="rounded-full bg-surface-2 px-2.5 py-0.5 text-xs font-bold">{run.price_paise ? rupees(run.price_paise) : t("adminWs.runs.free")}</span>
      </div>
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
        <span>{t("adminWs.runs.stat.enrolled")}: <b>{run.enrolled}</b>{run.capacity ? ` / ${run.capacity}` : ` · ${t("adminWs.runs.unlimited")}`}</span>
        {run.sessions_started !== undefined && <span>{t("adminWs.runs.stat.joined")}: <b>{run.sessions_started}</b></span>}
        {run.sessions_passed !== undefined && <span>{t("adminWs.runs.stat.passed")}: <b>{run.sessions_passed}</b></span>}
        {run.announced_at && <span className="text-muted">{t("adminWs.runs.announced", { time: fmt(run.announced_at) })}</span>}
      </p>
      <div className="flex flex-wrap gap-2">
        {editable && <Button variant="outline" className="py-2" onClick={onEdit}><Pencil className="h-4 w-4" /> {t("adminWs.runs.editBtn")}</Button>}
        {run.status === "draft" && <Button className="py-2" loading={busy === "publish"} onClick={() => void act("publish", () => workshops.adminPublish(run.id))}><Send className="h-4 w-4" /> {t("adminWs.runs.publish")}</Button>}
        {run.status === "scheduled" && !run.announced_at && (
          <Button className="py-2" loading={busy === "announce"} onClick={() => void act("announce", () => workshops.adminAnnounce(run.id), t("adminWs.runs.announceConfirm"))}><Megaphone className="h-4 w-4" /> {t("adminWs.runs.announce")}</Button>
        )}
        <Button variant="ghost" className="py-2" aria-expanded={stats} onClick={() => setStats((s) => !s)}><BarChart3 className="h-4 w-4" /> {stats ? t("adminWs.runs.hideStats") : t("adminWs.runs.stats")}</Button>
        {(editable || run.status === "live") && (
          <Button variant="ghost" className="py-2 text-bad" loading={busy === "cancel"} onClick={() => void act("cancel", () => workshops.adminCancel(run.id), t("adminWs.runs.cancelConfirm"), true)}><XCircle className="h-4 w-4" /> {t("adminWs.runs.cancel")}</Button>
        )}
      </div>
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
      {stats && <StatsCard id={run.id} />}
    </Card>
  );
}

function RunsTab({ templates }: { templates: AdminTemplate[] }) {
  const { t } = useTranslation();
  const { data, error, refetch } = useQuery({ queryKey: ["admin-workshop-runs"], queryFn: () => workshops.adminRuns() });
  const [editing, setEditing] = useState<AdminRun | "new" | null>(null);
  return (
    <div className="space-y-3">
      {editing ? (
        <RunEditor key={editing === "new" ? "new" : editing.id} templates={templates} run={editing === "new" ? null : editing} onDone={() => setEditing(null)} />
      ) : (
        <Button onClick={() => setEditing("new")}><CalendarPlus className="h-4 w-4" /> {t("adminWs.runs.new")}</Button>
      )}
      {error ? <PageError error={error} onRetry={() => void refetch()} /> : !data ? <p className="text-muted">{t("common.loading")}</p> : data.length === 0 ? (
        <Card className="text-muted">{t("adminWs.runs.empty")}</Card>
      ) : (
        data.map((r) => <RunRow key={r.id} run={r} onEdit={() => setEditing(r)} />)
      )}
    </div>
  );
}

/** One org: may it schedule institution workshops, and how many participants a month (empty = no cap). */
function OrgRow({ org }: { org: AdminOrgWorkshops }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [seats, setSeats] = useState(String(org.workshop_seats ?? 0));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const seatsOk = /^\d+$/.test(seats.trim()) && Number(seats) <= SEATS_MAX;

  async function save(body: Parameters<typeof adminOrgWorkshops.save>[1]) {
    setBusy(true);
    setMsg(null);
    try {
      const row = await adminOrgWorkshops.save(org.id, body);
      qc.setQueryData<AdminOrgWorkshops[]>(["admin-workshop-orgs"], (list) => list?.map((x) => (x.id === org.id ? { ...x, ...row } : x)));
      setMsg({ ok: true, text: t("adminWs.orgs.saved") });
    } catch {
      setMsg({ ok: false, text: t("adminWs.orgs.failed") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-2" data-testid={`admin-org-${org.slug}`}>
      <div className="flex flex-wrap items-baseline gap-x-3">
        <h3 className="break-words font-display text-lg font-bold">{org.name}</h3>
        <span className="[overflow-wrap:anywhere] text-xs text-muted">{org.slug}{org.members !== undefined && ` · ${t("org.membersN", { count: org.members })}`}</span>
      </div>
      <Toggle label={t("adminWs.orgs.enabled")} checked={org.workshops} onChange={(v) => void save({ workshops: v })} />
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-0 flex-1">
          <Field label={t("adminWs.orgs.seats")} name={`seats-${org.id}`} inputMode="numeric" value={seats} onChange={(e) => setSeats(e.target.value)} error={seatsOk ? undefined : t("adminWs.orgs.seatsErr")} />
        </div>
        <Button variant="outline" loading={busy} disabled={!seatsOk} onClick={() => void save({ workshop_seats: Number(seats) })}>{t("common.save")}</Button>
      </div>
      <p className="text-xs text-muted">{org.seats_used !== undefined ? t("adminWs.orgs.used", { count: org.seats_used }) : ""} {t("adminWs.orgs.seatsHint")}</p>
      {msg && <p role={msg.ok ? "status" : "alert"} className={cn("text-sm", msg.ok ? "text-good" : "text-bad")}>{msg.text}</p>}
    </Card>
  );
}

function OrgsTab() {
  const { t } = useTranslation();
  const { data, error, refetch } = useQuery({ queryKey: ["admin-workshop-orgs"], queryFn: adminOrgWorkshops.list, retry: false });
  const [q, setQ] = useState("");
  if (error) return error instanceof ApiError && error.status === 404 ? <Card className="text-muted">{t("adminWs.orgs.unavailable")}</Card> : <PageError error={error} onRetry={() => void refetch()} />;
  if (!data) return <p className="text-muted">{t("common.loading")}</p>;
  const needle = q.trim().toLowerCase();
  const shown = needle ? data.filter((o) => o.name.toLowerCase().includes(needle) || o.slug.includes(needle)) : data;
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">{t("adminWs.orgs.sub")}</p>
      <Field label={t("adminWs.orgs.search")} name="org-search" value={q} onChange={(e) => setQ(e.target.value)} />
      {shown.length === 0 ? <Card className="text-muted">{t("adminWs.orgs.empty")}</Card> : shown.map((o) => <OrgRow key={o.id} org={o} />)}
    </div>
  );
}

const TABS = ["templates", "runs", "orgs"] as const;

/** The tab index an arrow / Home / End key moves to (wrapping), or null for any other key. */
function tabKey(key: string, at: number, count: number = TABS.length): number | null {
  if (key === "ArrowRight") return (at + 1) % count;
  if (key === "ArrowLeft") return (at - 1 + count) % count;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  return null;
}

/** Admin console: workshop templates (each with a one-click test run) and scheduled public runs. */
export default function AdminWorkshops() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<(typeof TABS)[number]>("templates");
  const { data, error, refetch } = useQuery({ queryKey: ["admin-workshops"], queryFn: workshops.adminTemplates });
  return (
    <div className="mx-auto max-w-4xl space-y-5 p-4 md:p-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("adminWs.title")}</h1>
        <p className="text-muted">{t("adminWs.sub")}</p>
      </header>
      {/* ARIA tabs: only the selected tab is in the Tab order; arrow keys, Home and End move between tabs. */}
      <div role="tablist" aria-label={t("adminWs.title")} className="flex gap-2 overflow-x-auto border-b border-line" onKeyDown={(e) => {
        const next = tabKey(e.key, TABS.indexOf(tab));
        if (next === null) return;
        e.preventDefault();
        setTab(TABS[next]);
        document.getElementById(`ws-tabbtn-${TABS[next]}`)?.focus();
      }}>
        {TABS.map((k) => (
          <button key={k} role="tab" type="button" aria-selected={tab === k} aria-controls={`ws-tab-${k}`} id={`ws-tabbtn-${k}`} tabIndex={tab === k ? 0 : -1} onClick={() => setTab(k)}
            className={cn("-mb-px border-b-2 px-3 py-2 font-semibold transition", tab === k ? "border-accent text-accent" : "border-transparent text-muted hover:text-ink")}>
            {t(`adminWs.tabs.${k}`)}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`ws-tab-${tab}`} aria-labelledby={`ws-tabbtn-${tab}`} tabIndex={0} className="focus-visible:outline-offset-4">
        {tab === "orgs" ? <OrgsTab /> : error ? <PageError error={error} onRetry={() => void refetch()} /> : !data ? <p className="text-muted">{t("common.loading")}</p> : tab === "runs" ? (
          <RunsTab templates={data} />
        ) : data.length === 0 ? (
          <Card className="text-muted">{t("adminWs.empty")}</Card>
        ) : (
          <div className="space-y-3">{data.map((w) => <TemplateRow key={w.slug} w={w} />)}</div>
        )}
      </div>
    </div>
  );
}
