import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Copy, Download, Plus, Sparkles, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { alertDialog, confirmDialog } from "@/lib/dialog";
import { Button, Card, Segmented } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { downloadFile } from "@/lib/download";
import {
  byDay, draftToInput, ITEM_KINDS, journeys, todayIso, type Draft, type ItemInput, type ItemKind, type Journey, type JourneyItem, type Phase,
} from "@/lib/journeys";

const KNOWN_ERRORS = ["lessons_not_ready", "not_published", "items_beyond_length", "colleague_required", "note_required", "course_not_found",
  "scenario_not_found", "document_not_found", "feature_off", "bad_day", "name_required", "no_members", "bad_start_date", "too_many_journeys", "too_many_items"];
const input = "w-full rounded-xl border-2 border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent";

function useErr() {
  const { t } = useTranslation();
  return (e: unknown) => {
    const code = e instanceof ApiError ? (e.data?.code as string | undefined) : undefined;
    return code && KNOWN_ERRORS.includes(code) ? t(`jr.errors.${code}`) : t("jr.saveFailed");
  };
}

/** /org/:slug/journeys — HR onboarding journeys: design (admins, org-wide managers), assign and follow (also unit admins). */
export default function OrgJourneysPage() {
  const { t } = useTranslation();
  const { slug = "" } = useParams();
  const { data, error } = useQuery({ queryKey: ["org-journeys", slug], queryFn: () => journeys.list(slug), retry: false });
  const [open, setOpen] = useState<number | null>(null);
  if (error) return <p className="p-8 text-muted">{t("org.notFound")}</p>;
  if (!data) return <p className="p-8 text-muted">{t("common.loading")}</p>;
  return (
    <div className="mx-auto max-w-5xl space-y-5 px-4 py-8">
      <header>
        <Link to={`/org/${slug}`} className="flex items-center gap-1 text-sm font-semibold text-accent hover:underline"><ArrowLeft className="h-4 w-4" /> {t("jr.backCockpit")}</Link>
        <h1 className="font-display text-3xl font-extrabold">{t("jr.manage")}</h1>
        <p className="text-muted">{t("jr.manageSub")}</p>
        {!data.can_edit && <p className="mt-1 text-sm text-muted">{t("jr.noUnitEdit")}</p>}
      </header>
      {open ? (
        <JourneyDetail slug={slug} id={open} canEdit={data.can_edit} back={() => setOpen(null)} />
      ) : (
        <>
          {data.can_edit && <div className="grid gap-4 md:grid-cols-2"><NewJourney slug={slug} onMade={setOpen} /><AiDraft slug={slug} onMade={setOpen} /></div>}
          <JourneyList slug={slug} rows={data.journeys} canEdit={data.can_edit} onOpen={setOpen} />
        </>
      )}
    </div>
  );
}

function JourneyList({ slug, rows, canEdit, onOpen }: { slug: string; rows: Journey[]; canEdit: boolean; onOpen: (id: number) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: ["org-journeys", slug] });
  if (!rows.length) return <Card><p className="text-muted">{t("jr.noJourneys")}</p></Card>;
  return (
    <ul className="grid gap-3 sm:grid-cols-2">
      {rows.map((j) => (
        <li key={j.id}>
          <Card className="space-y-2">
            <button onClick={() => onOpen(j.id)} className="text-left">
              <p className="font-display text-lg font-bold hover:text-accent">{j.name}</p>
              <p className="text-sm text-muted">{t("jr.lengthN", { count: j.length_days })} · {t("jr.itemsN", { count: j.items_n })} · {t("jr.assignees", { count: j.assignees_n })}</p>
            </button>
            {j.description && <p className="line-clamp-2 text-sm">{j.description}</p>}
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => onOpen(j.id)}>{t("jr.open")}</Button>
              {canEdit && <Button variant="ghost" onClick={async () => { const c = await journeys.duplicate(slug, j.id); if (c.dropped.length) await alertDialog(t("jr2.dupDropped", { count: c.dropped.length, titles: c.dropped.map((d) => d.title).join(", ") })); await refresh(); onOpen(c.id); }}><Copy className="h-4 w-4" /> {t("jr.duplicate")}</Button>}
              {canEdit && <Button variant="ghost" className="text-bad" onClick={async () => { if (await confirmDialog(t("jr.confirmDelete"), { danger: true })) { await journeys.remove(slug, j.id); await refresh(); } }}><Trash2 className="h-4 w-4" /> {t("jr.delete")}</Button>}
            </div>
          </Card>
        </li>
      ))}
    </ul>
  );
}

const LENGTHS = [30, 60, 90] as const;

function DaysPick({ label, value, onChange }: { label: string; value: number; onChange: (n: number) => void }) {
  return (
    <label className="flex items-center gap-2 text-sm">{label}
      <select className="rounded-xl border-2 border-line bg-surface px-3 py-1.5 text-sm" value={value} onChange={(e) => onChange(Number(e.target.value))}>
        {LENGTHS.map((n) => <option key={n} value={n}>{n}</option>)}
      </select>
    </label>
  );
}

function NewJourney({ slug, onMade }: { slug: string; onMade: (id: number) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const err = useErr();
  const [name, setName] = useState("");
  const [days, setDays] = useState<number>(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const j = await journeys.create(slug, { name: name.trim(), length_days: days });
      void qc.invalidateQueries({ queryKey: ["org-journeys", slug] });
      onMade(j.id);
    } catch (e2) {
      setError(err(e2));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card>
      <form onSubmit={submit} className="space-y-3">
        <h2 className="font-display text-lg font-bold">{t("jr.newJourney")}</h2>
        <input className={input} value={name} onChange={(e) => setName(e.target.value)} placeholder={t("jr.namePlaceholder")} aria-label={t("jr.name")} maxLength={120} />
        <DaysPick label={t("jr.lengthDays")} value={days} onChange={setDays} />
        {error && <p role="alert" className="text-sm text-bad">{error}</p>}
        <Button type="submit" loading={busy} disabled={!name.trim()}><Plus className="h-4 w-4" /> {t("jr.create")}</Button>
      </form>
    </Card>
  );
}

function AiDraft({ slug, onMade }: { slug: string; onMade: (id: number) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const err = useErr();
  const [role, setRole] = useState("");
  const [company, setCompany] = useState("");
  const [days, setDays] = useState<number>(30);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [rejected, setRejected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function go(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      setDraft(await journeys.draft(slug, { role: role.trim(), company: company.trim(), days }));
      setRejected(new Set());
    } catch (e2) {
      const code = e2 instanceof ApiError ? (e2.data?.code as string | undefined) : undefined;
      setError(code === "ai_budget_exceeded" ? t("jr.aiBudget") : t("jr.aiFailed"));
    } finally {
      setBusy(false);
    }
  }
  async function create() {
    if (!draft) return;
    setBusy(true);
    setError("");
    try {
      const items = draft.items.filter((i) => !rejected.has(i.key)).map(draftToInput);
      const j = await journeys.create(slug, { name: draft.name, description: draft.description, length_days: draft.length_days, phases: draft.phases, items });
      void qc.invalidateQueries({ queryKey: ["org-journeys", slug] });
      onMade(j.id);
    } catch (e2) {
      setError(err(e2));
    } finally {
      setBusy(false);
    }
  }
  const toggle = (k: number, accept: boolean) => setRejected((s) => { const n = new Set(s); if (accept) n.delete(k); else n.add(k); return n; });
  const kept = draft ? draft.items.length - rejected.size : 0;

  return (
    <Card className="space-y-3 bg-gradient-to-br from-accent/10 to-surface">
      <form onSubmit={go} className="space-y-3">
        <h2 className="flex items-center gap-2 font-display text-lg font-bold"><Sparkles className="h-5 w-5 text-accent" /> {t("jr.aiTitle")}</h2>
        <input className={input} value={role} onChange={(e) => setRole(e.target.value)} placeholder={t("jr.aiRole")} aria-label={t("jr.aiRole")} maxLength={120} />
        <textarea className={input} rows={2} value={company} onChange={(e) => setCompany(e.target.value)} placeholder={t("jr.aiCompany")} aria-label={t("jr.aiCompany")} maxLength={600} />
        <DaysPick label={t("jr.aiDays")} value={days} onChange={setDays} />
        <p className="text-xs text-muted">{t("jr.aiCost")}</p>
        <Button type="submit" loading={busy && !draft} disabled={role.trim().length < 2}>{t("jr.aiGo")}</Button>
      </form>
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      {draft && (
        <div className="space-y-3 border-t border-line pt-3">
          <p className="font-display text-lg font-bold">{draft.name}</p>
          {draft.description && <p className="text-sm text-muted">{draft.description}</p>}
          <ul className="flex flex-wrap gap-1 text-xs">{draft.phases.map((p) => <li key={p.start_day} className="rounded-full bg-surface-2 px-2 py-0.5">{p.title} · {t("jr.dayRange", { a: p.start_day, b: p.end_day })}</li>)}</ul>
          <ul className="max-h-96 space-y-1.5 overflow-y-auto">
            {draft.items.map((i) => {
              const on = !rejected.has(i.key);
              return (
                <li key={i.key} className={cn("flex items-start gap-2 rounded-xl border border-line p-2 text-sm", !on && "opacity-50")}>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs text-muted">{t("jr.dayN", { n: i.day })} · {t(`jr.kinds.${i.kind}`)}{i.ref_title && <> · {i.ref_title}</>}{i.colleague_role && <> · {i.colleague_role}</>}</p>
                    <p className="font-medium">{i.title}</p>
                    {i.notes && <p className="text-xs text-muted">{i.notes}</p>}
                  </div>
                  <Segmented label={i.title} value={on ? "y" : "n"} onChange={(v) => toggle(i.key, v === "y")} options={[{ value: "y", label: t("jr.accept") }, { value: "n", label: t("jr.reject") }]} />
                </li>
              );
            })}
          </ul>
          <Button loading={busy} onClick={() => void create()}>{t("jr.createFromDraft", { count: kept })}</Button>
        </div>
      )}
    </Card>
  );
}

type DetailTab = "plan" | "assign" | "progress";

function JourneyDetail({ slug, id, canEdit, back }: { slug: string; id: number; canEdit: boolean; back: () => void }) {
  const { t } = useTranslation();
  const { data: j } = useQuery({ queryKey: ["org-journey", slug, id], queryFn: () => journeys.get(slug, id) });
  const [tab, setTab] = useState<DetailTab>(canEdit ? "plan" : "progress");
  if (!j) return <p className="text-muted">{t("common.loading")}</p>;
  return (
    <div className="space-y-4">
      <button onClick={back} className="flex items-center gap-1 text-sm font-semibold text-accent hover:underline"><ArrowLeft className="h-4 w-4" /> {t("jr.back")}</button>
      <div>
        <h2 className="font-display text-2xl font-extrabold">{j.name}</h2>
        <p className="text-sm text-muted">{t("jr.lengthN", { count: j.length_days })} · {t("jr.itemsN", { count: j.items?.length ?? 0 })} · {t("jr.assignees", { count: j.assignees_n })}</p>
      </div>
      <Segmented label={j.name} value={tab} onChange={setTab} options={(["plan", "assign", "progress"] as DetailTab[]).map((k) => ({ value: k, label: t(`jr.tabs.${k}`) }))} />
      {tab === "plan" && <PlanEditor slug={slug} j={j} canEdit={canEdit} />}
      {tab === "assign" && <AssignPanel slug={slug} j={j} />}
      {tab === "progress" && <ProgressPanel slug={slug} j={j} />}
    </div>
  );
}

function PlanEditor({ slug, j, canEdit }: { slug: string; j: Journey; canEdit: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const reload = () => {
    void qc.invalidateQueries({ queryKey: ["org-journey", slug, j.id] });
    void qc.invalidateQueries({ queryKey: ["org-journeys", slug] });
  };
  const describe = (i: JourneyItem) => i.kind === "lesson" ? [i.course?.title, i.lesson?.title].filter(Boolean).join(" · ")
    : i.kind === "scenario" ? i.scenario?.title : i.kind === "document" ? i.document?.title : i.kind === "shadow" ? [i.colleague_name, i.colleague_role].filter(Boolean).join(" · ") : "";
  return (
    <div className="space-y-4">
      {canEdit && <PhasesEditor slug={slug} j={j} onSaved={reload} />}
      {canEdit && <AddItem slug={slug} j={j} onAdded={reload} />}
      <Card className="space-y-3">
        <h3 className="font-display text-lg font-bold">{t("jr.items")}</h3>
        {!j.items?.length && <p className="text-sm text-muted">{t("jr.noItems")}</p>}
        {byDay(j.items ?? []).map(([day, rows]) => (
          <div key={day}>
            <p className="text-sm font-semibold text-muted">{t("jr.dayN", { n: day })}{(() => { const p = j.phases.find((x) => x.start_day <= day && day <= x.end_day); return p ? ` · ${p.title}` : ""; })()}</p>
            <ul className="mt-1 space-y-1">
              {rows.map((i) => (
                <li key={i.id} className="flex items-start gap-2 rounded-xl border border-line p-2 text-sm">
                  <div className="min-w-0 flex-1">
                    <p><span className="text-xs font-semibold uppercase text-muted">{t(`jr.kinds.${i.kind}`)}</span> {i.title}</p>
                    {describe(i) && <p className="text-xs text-muted">{describe(i)}</p>}
                    {i.notes && <p className="text-xs">{i.notes}</p>}
                  </div>
                  {canEdit && <button aria-label={t("jr.remove")} className="text-muted hover:text-bad" onClick={async () => { await journeys.removeItem(slug, j.id, i.id); reload(); }}><Trash2 className="h-4 w-4" /></button>}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </Card>
    </div>
  );
}

function PhasesEditor({ slug, j, onSaved }: { slug: string; j: Journey; onSaved: () => void }) {
  const { t } = useTranslation();
  const err = useErr();
  const [rows, setRows] = useState<Phase[]>(j.phases);
  const [msg, setMsg] = useState("");
  const set = (k: number, patch: Partial<Phase>) => setRows((r) => r.map((p, n) => (n === k ? { ...p, ...patch } : p)));
  async function save() {
    setMsg("");
    try {
      const out = await journeys.update(slug, j.id, { phases: rows });
      setRows(out.phases);
      setMsg(t("jr.saved"));
      onSaved();
    } catch (e) {
      setMsg(err(e));
    }
  }
  const last = rows.length ? rows[rows.length - 1].end_day : 0;
  return (
    <Card className="space-y-2">
      <h3 className="font-display text-lg font-bold">{t("jr.phases")}</h3>
      {rows.map((p, k) => (
        <div key={k} className="flex flex-wrap items-center gap-2">
          <input className={cn(input, "min-w-48 flex-1")} value={p.title} onChange={(e) => set(k, { title: e.target.value })} placeholder={t("jr.phaseTitle")} aria-label={t("jr.phaseTitle")} maxLength={80} />
          <label className="flex items-center gap-1 text-sm">{t("jr.from")}<input type="number" min={1} max={j.length_days} className={cn(input, "w-20")} value={p.start_day} onChange={(e) => set(k, { start_day: Number(e.target.value) })} /></label>
          <label className="flex items-center gap-1 text-sm">{t("jr.to")}<input type="number" min={1} max={j.length_days} className={cn(input, "w-20")} value={p.end_day} onChange={(e) => set(k, { end_day: Number(e.target.value) })} /></label>
          <button aria-label={t("jr.remove")} className="text-muted hover:text-bad" onClick={() => setRows((r) => r.filter((_, n) => n !== k))}><Trash2 className="h-4 w-4" /></button>
        </div>
      ))}
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" disabled={last >= j.length_days} onClick={() => setRows((r) => [...r, { title: "", start_day: last + 1, end_day: Math.min(j.length_days, last + 7) }])}><Plus className="h-4 w-4" /> {t("jr.addPhase")}</Button>
        <Button onClick={() => void save()}>{t("jr.savePhases")}</Button>
        {msg && <span role="status" className="text-sm text-muted">{msg}</span>}
      </div>
    </Card>
  );
}

function AddItem({ slug, j, onAdded }: { slug: string; j: Journey; onAdded: () => void }) {
  const { t } = useTranslation();
  const err = useErr();
  const { data: opts } = useQuery({ queryKey: ["journey-options", slug], queryFn: () => journeys.options(slug) });
  const blank: ItemInput = { kind: "lesson", day: 1, title: "", notes: "", curriculum_id: null, lesson_id: null, scenario_id: null, document_id: null, colleague_name: "", colleague_role: "" };
  const [f, setF] = useState<ItemInput>(blank);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (patch: Partial<ItemInput>) => setF((x) => ({ ...x, ...patch }));
  const course = opts?.courses.find((c) => c.id === f.curriculum_id);
  const num = (v: string) => (v ? Number(v) : null);

  async function add(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await journeys.addItem(slug, j.id, f);
      setF({ ...blank, kind: f.kind, day: f.day });
      onAdded();
    } catch (e2) {
      setError(err(e2));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card>
      <form onSubmit={add} className="space-y-2">
        <h3 className="font-display text-lg font-bold">{t("jr.addItem")}</h3>
        <div className="grid gap-2 sm:grid-cols-[1fr_6rem]">
          <select className={input} value={f.kind} onChange={(e) => set({ kind: e.target.value as ItemKind })} aria-label={t("jr.kind")}>
            {ITEM_KINDS.map((k) => <option key={k} value={k}>{t(`jr.kinds.${k}`)}</option>)}
          </select>
          <label className="flex items-center gap-1 text-sm">{t("jr.day")}<input type="number" min={1} max={j.length_days} className={input} value={f.day} onChange={(e) => set({ day: Number(e.target.value) })} /></label>
        </div>
        {f.kind === "lesson" && (
          <div className="grid gap-2 sm:grid-cols-2">
            <select className={input} value={f.curriculum_id ?? ""} onChange={(e) => set({ curriculum_id: num(e.target.value), lesson_id: null })} aria-label={t("jr.course")}>
              <option value="">{t("jr.pickCourse")}</option>
              {opts?.courses.map((c) => <option key={c.id} value={c.id}>{c.emoji} {c.title}</option>)}
            </select>
            <select className={input} value={f.lesson_id ?? ""} disabled={!course} onChange={(e) => set({ lesson_id: num(e.target.value) })} aria-label={t("jr.lesson")}>
              <option value="">{t("jr.wholeCourse")}</option>
              {course?.lessons.map((l) => <option key={l.id} value={l.id}>{l.title}</option>)}
            </select>
          </div>
        )}
        {f.kind === "scenario" && (
          <select className={input} value={f.scenario_id ?? ""} onChange={(e) => set({ scenario_id: num(e.target.value) })} aria-label={t("jr.scenario")}>
            <option value="">{t("jr.pickScenario")}</option>
            {opts?.scenarios.map((s) => <option key={s.id} value={s.id}>{s.emoji} {s.title}</option>)}
          </select>
        )}
        {f.kind === "document" && (
          <>
            <select className={input} value={f.document_id ?? ""} onChange={(e) => set({ document_id: num(e.target.value) })} aria-label={t("jr.document")}>
              <option value="">{t("jr.pickDocument")}</option>
              {opts?.documents.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
            </select>
            {opts && !opts.documents.length && <p className="text-xs text-muted">{t("jr.noDocs")}</p>}
          </>
        )}
        {f.kind === "shadow" && (
          <div className="grid gap-2 sm:grid-cols-2">
            <input className={input} value={f.colleague_name} onChange={(e) => set({ colleague_name: e.target.value })} placeholder={t("jr.colleagueName")} aria-label={t("jr.colleagueName")} maxLength={80} />
            <input className={input} value={f.colleague_role} onChange={(e) => set({ colleague_role: e.target.value })} placeholder={t("jr.colleagueRole")} aria-label={t("jr.colleagueRole")} maxLength={80} />
          </div>
        )}
        <input className={input} value={f.title} onChange={(e) => set({ title: e.target.value })} placeholder={t("jr.titleOptional")} aria-label={t("jr.title")} maxLength={160} />
        <textarea className={input} rows={2} value={f.notes} onChange={(e) => set({ notes: e.target.value })} placeholder={t("jr.notes")} aria-label={t("jr.notes")} maxLength={1000} />
        {error && <p role="alert" className="text-sm text-bad">{error}</p>}
        <Button type="submit" loading={busy}><Plus className="h-4 w-4" /> {t("jr.add")}</Button>
      </form>
    </Card>
  );
}

function AssignPanel({ slug, j }: { slug: string; j: Journey }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const err = useErr();
  const { data: ppl } = useQuery({ queryKey: ["journey-people", slug], queryFn: () => journeys.people(slug) });
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [group, setGroup] = useState<number | null>(null);
  const [start, setStart] = useState(todayIso());
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  if (!ppl) return <p className="text-muted">{t("common.loading")}</p>;
  const shown = ppl.members.filter((m) => `${m.name} ${m.email}`.toLowerCase().includes(q.toLowerCase()));

  async function go() {
    setBusy(true);
    setMsg("");
    try {
      const r = await journeys.assign(slug, j.id, { membership_ids: [...picked], group_id: group, start_date: start });
      setMsg(t("jr.assigned", { n: r.assigned, skipped: r.skipped }) + (r.not_granted.length ? ` ${t("jr2.notGranted", { titles: r.not_granted.map((c) => c.title).join(", ") })}` : ""));
      setPicked(new Set());
      void qc.invalidateQueries({ queryKey: ["org-journey", slug, j.id] });
      void qc.invalidateQueries({ queryKey: ["journey-progress", slug, j.id] });
    } catch (e) {
      setMsg(err(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card className="space-y-3">
      <label className="block text-sm font-medium">{t("jr.startDate")}<input type="date" className={cn(input, "mt-1 max-w-48")} value={start} onChange={(e) => setStart(e.target.value)} /></label>
      <label className="block text-sm font-medium">{t("jr.group")}
        <select className={cn(input, "mt-1")} value={group ?? ""} onChange={(e) => setGroup(e.target.value ? Number(e.target.value) : null)}>
          <option value="">{t("jr.noGroup")}</option>
          {ppl.groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
        </select>
      </label>
      <div>
        <p className="text-sm font-medium">{t("jr.members")}</p>
        <input className={cn(input, "mt-1")} value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("jr.search")} aria-label={t("jr.search")} />
        <ul className="mt-2 max-h-72 space-y-1 overflow-y-auto">
          {shown.map((m) => (
            <li key={m.id}>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={picked.has(m.id)} onChange={(e) => setPicked((s) => { const n = new Set(s); if (e.target.checked) n.add(m.id); else n.delete(m.id); return n; })} />
                <span className="font-medium">{m.name}</span> <span className="text-muted">{m.email}</span>
              </label>
            </li>
          ))}
        </ul>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button loading={busy} disabled={!picked.size && !group} onClick={() => void go()}>{t("jr.assignGo")}</Button>
        {msg && <span role="status" className="text-sm">{msg}</span>}
      </div>
    </Card>
  );
}

function ProgressPanel({ slug, j }: { slug: string; j: Journey }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["journey-progress", slug, j.id], queryFn: () => journeys.progress(slug, j.id) });
  const [dlError, setDlError] = useState(false);
  if (!data) return <p className="text-muted">{t("common.loading")}</p>;
  const stuck = data.rows.filter((r) => r.stuck).length;
  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted">{t("jr.progressSummary", { count: data.rows.length, stuck })}</p>
        <Button variant="outline" disabled={!data.rows.length} onClick={() => downloadFile(journeys.csvUrl(slug, j.id), `journey-${j.id}-progress.csv`).catch(() => setDlError(true))}>
          <Download className="h-4 w-4" /> {t("jr.exportCsv")}
        </Button>
      </div>
      {dlError && <p role="alert" className="text-sm text-bad">{t("jr.saveFailed")}</p>}
      {!data.rows.length ? <p className="text-sm text-muted">{t("jr.noAssignees")}</p> : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted">
                <th className="px-2 py-1">{t("jr.colName")}</th><th className="px-2 py-1">{t("jr.colDay")}</th><th className="px-2 py-1">{t("jr.colDone")}</th>
                <th className="px-2 py-1">{t("jr.colOverdue")}</th><th className="px-2 py-1">{t("jr.colPhase")}</th><th className="px-2 py-1" /><th className="px-2 py-1" />
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.assignment_id} className="border-t border-line align-top">
                  <td className="px-2 py-1.5"><p className="font-medium">{r.name}</p><p className="text-xs text-muted">{r.email}</p></td>
                  <td className="px-2 py-1.5 tabular-nums">{r.started ? t("jr.dayOf", { day: Math.min(r.day, r.length_days), n: r.length_days }) : new Date(`${r.start_date}T00:00:00`).toLocaleDateString(i18n.language)}</td>
                  <td className="px-2 py-1.5 tabular-nums">{r.done}/{r.total}</td>
                  <td className={cn("px-2 py-1.5 tabular-nums", r.overdue > 0 && "font-semibold text-bad")}>{r.overdue}</td>
                  <td className="px-2 py-1.5">
                    <p>{r.phase_title || "—"}</p>
                    <div className="mt-1 flex gap-0.5" aria-hidden>{r.phases.map((p) => <span key={p.start_day} title={`${p.title}: ${t(`jr.phaseStatus.${p.status}`)}`} className={cn("h-1.5 w-6 rounded-full", p.status === "done" ? "bg-good" : p.status === "behind" ? "bg-bad" : p.status === "active" ? "bg-accent" : "bg-surface-2")} />)}</div>
                  </td>
                  <td className="px-2 py-1.5">{r.stuck ? <span className="inline-flex items-center gap-1 rounded-full bg-bad/15 px-2 py-0.5 text-xs font-bold text-bad"><AlertTriangle className="h-3 w-3" /> {t("jr.stuck")}</span>
                    : r.finished ? <span className="text-xs font-semibold text-good">{t("jr.finished")}</span> : <span className="text-xs text-muted">{t("jr.onTrack")}</span>}</td>
                  <td className="px-2 py-1.5"><button className="text-xs text-muted hover:text-bad" onClick={async () => { await journeys.unassign(slug, j.id, r.assignment_id); void qc.invalidateQueries({ queryKey: ["journey-progress", slug, j.id] }); }}>{t("jr.unassign")}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
