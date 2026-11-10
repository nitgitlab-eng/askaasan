/** Milestone 9 cockpit tabs: sub-units, company knowledge base (+ topic graph), partner cohorts, and 'Set up with Kili'. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, FileText, Plus, RotateCcw, Send, Trash2, Upload, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { confirmDialog } from "@/lib/dialog";
import { UnsentInvites } from "@/components/orgs/UnsentInvites";
import { Button, Card, Segmented } from "@/components/ui";
import { localeOf } from "@/i18n/languages";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { orgs, type InviteMail } from "@/lib/orgs";
import { KB_BUSY, layoutGraph, parseEmails, school, type Cohort, type KbGraph, type KbStatus, type Proposal, type SetupMsg, type Unit } from "@/lib/school";

const input = "rounded-lg border-2 border-line bg-surface px-2 py-1.5 text-sm outline-none focus:border-accent";
const MAX_UPLOAD = 10 * 1024 * 1024;

function useErr() {
  const { t } = useTranslation();
  const [err, setErr] = useState("");
  const run = async (fn: () => Promise<unknown>) => {
    setErr("");
    try {
      await fn();
    } catch (e) {
      const code = e instanceof ApiError ? ((e.data as { code?: string } | undefined)?.code ?? "") : "";
      setErr(t(`school.err.${code}`, { defaultValue: t("mentor.errors.generic") }));
    }
  };
  return { err, run };
}

const fmtDate = (d: string, lang: string) => new Date(d).toLocaleDateString(localeOf(lang), { day: "numeric", month: "short", year: "numeric" });

// ── Units ────────────────────────────────────────────────────────────

export function UnitsTab({ slug, scoped }: { slug: string; scoped: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["school-units", slug], queryFn: () => school.units(slug) });
  const [sel, setSel] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [parent, setParent] = useState<number | "">("");
  const { err, run } = useErr();
  if (!data) return <p className="text-muted">{t("common.loading")}</p>;
  const current = sel ?? data.units[0]?.id ?? null;
  const nameOf = (id: number | null) => data.units.find((u) => u.id === id)?.name ?? "";
  return (
    <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
      <div className="space-y-3">
        <Card className="space-y-2">
          <h2 className="font-display text-lg font-bold">{t("school.units.title")}</h2>
          <p className="text-xs text-muted">{scoped ? t("school.units.scopedHint") : t("school.units.hint")}</p>
          {!data.units.length && <p className="text-sm text-muted">{t("school.units.none")}</p>}
          <ul className="space-y-1">
            {data.units.map((u) => (
              <li key={u.id}>
                <button onClick={() => setSel(u.id)} className={cn("w-full rounded-xl px-3 py-2 text-left text-sm", current === u.id ? "bg-accent/15 font-semibold" : "hover:bg-surface-2")}>
                  {u.parent_id && <span className="text-muted">{nameOf(u.parent_id)} › </span>}{u.name}
                  <span className="block text-xs text-muted">{t("school.units.classesN", { count: u.groups.length })} · {t("school.units.learnersN", { count: u.learners })}</span>
                </button>
              </li>
            ))}
          </ul>
        </Card>
        {!scoped && (
          <Card>
            <form className="space-y-2" onSubmit={(e: FormEvent) => {
              e.preventDefault();
              void run(async () => {
                const u = await school.addUnit(slug, { name: name.trim(), parent_id: parent || null });
                setName("");
                setSel(u.id);
                await qc.invalidateQueries({ queryKey: ["school-units", slug] });
              });
            }}>
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} placeholder={t("school.units.namePh")} aria-label={t("school.units.name")} className={cn(input, "w-full")} />
              <select value={parent} onChange={(e) => setParent(e.target.value ? Number(e.target.value) : "")} aria-label={t("school.units.parent")} className={cn(input, "w-full")}>
                <option value="">{t("school.units.noParent")}</option>
                {data.units.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
              </select>
              <Button type="submit" className="w-full py-1.5 text-sm" disabled={!name.trim()}><Plus className="h-4 w-4" /> {t("school.units.add")}</Button>
              {err && <p role="alert" className="text-sm text-bad">{err}</p>}
            </form>
          </Card>
        )}
      </div>
      {current !== null && <UnitDetail key={current} slug={slug} id={current} scoped={scoped} onDeleted={() => setSel(null)} />}
    </div>
  );
}

function UnitDetail({ slug, id, scoped, onDeleted }: { slug: string; id: number; scoped: boolean; onDeleted: () => void }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const key = ["school-unit", slug, id];
  const { data: u } = useQuery({ queryKey: key, queryFn: () => school.unit(slug, id) });
  const { data: careers } = useQuery({ queryKey: ["careers"], queryFn: school.careers });
  const { data: groups } = useQuery({ queryKey: ["org-groups", slug], queryFn: () => orgs.groups(slug), enabled: !scoped });
  const { data: learners } = useQuery({ queryKey: ["school-unit-learners", slug, id], queryFn: () => school.unitLearners(slug, id) });
  const { data: assigned } = useQuery({ queryKey: ["school-unit-assign", slug, id], queryFn: () => school.unitAssignments(slug, id) });
  const [email, setEmail] = useState("");
  const [unsent, setUnsent] = useState<InviteMail | null>(null);
  const [groupName, setGroupName] = useState("");
  const [assign, setAssign] = useState<{ course: number | ""; group: number | ""; due: string }>({ course: "", group: "", due: "" });
  const { err, run } = useErr();
  if (!u) return <p className="text-muted">{t("common.loading")}</p>;
  const set = (v: Unit) => {
    qc.setQueryData(key, v);
    void qc.invalidateQueries({ queryKey: ["school-units", slug] });
  };
  const save = (body: Parameters<typeof school.saveUnit>[2]) => run(async () => set(await school.saveUnit(slug, id, body)));
  const roleSlugs = u.target_roles.map((r) => r.slug);
  const courseIds = u.courses.map((c) => c.id);
  const groupIds = u.groups.map((g) => g.id);
  return (
    <div className="space-y-4">
      <Card className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            {scoped ? <h2 className="font-display text-xl font-bold">{u.name}</h2> : (
              <input defaultValue={u.name} key={u.name} maxLength={80} aria-label={t("school.units.name")} onBlur={(e) => e.target.value.trim() && e.target.value !== u.name && void save({ name: e.target.value.trim() })}
                className="w-full rounded-lg border-2 border-transparent bg-transparent font-display text-xl font-bold outline-none hover:border-line focus:border-accent" />
            )}
            <p className="text-sm text-muted">{t("school.units.classesN", { count: u.groups.length })} · {t("school.units.learnersN", { count: u.learners })}</p>
          </div>
          {!scoped && <Button variant="ghost" className="py-1 text-sm" onClick={async () => (await confirmDialog(t("school.units.confirmDelete"), { danger: true })) && void run(async () => { await school.deleteUnit(slug, id); onDeleted(); await qc.invalidateQueries({ queryKey: ["school-units", slug] }); })}><Trash2 className="h-4 w-4" /> {t("lab.delete")}</Button>}
        </div>
        <label className="block text-sm">{t("school.units.description")}
          <textarea defaultValue={u.description} key={u.description} maxLength={300} rows={2} onBlur={(e) => e.target.value !== u.description && void save({ description: e.target.value })} className={cn(input, "mt-1 w-full")} /></label>
        <div>
          <p className="text-sm font-semibold">{t("school.units.roles")}</p>
          <p className="text-xs text-muted">{t("school.units.rolesHint")}</p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {(careers ?? []).map((c) => {
              const on = roleSlugs.includes(c.slug);
              return <button key={c.slug} onClick={() => void save({ target_roles: on ? roleSlugs.filter((s) => s !== c.slug) : [...roleSlugs, c.slug] })} aria-pressed={on}
                className={cn("rounded-full border-2 px-2.5 py-1 text-xs", on ? "border-accent bg-accent/15 font-semibold" : "border-line hover:border-accent")}>{c.emoji} {c.title}</button>;
            })}
          </div>
        </div>
        {err && <p role="alert" className="text-sm text-bad">{err}</p>}
      </Card>

      <Card className="space-y-2">
        <h3 className="font-display text-lg font-bold">{t("school.units.coverage")}</h3>
        <p className="text-xs text-muted">{t("school.units.coverageHint")}</p>
        {scoped ? (
          u.courses.length ? <ul className="text-sm">{u.courses.map((c) => <li key={c.id}>{c.emoji} {c.title}</li>)}</ul> : <p className="text-sm text-muted">{t("school.units.allCourses")}</p>
        ) : (
          <div className="grid gap-1 sm:grid-cols-2">
            {(u.course_options ?? []).map((c) => (
              <label key={c.id} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={courseIds.includes(c.id)} onChange={(e) => void save({ course_ids: e.target.checked ? [...courseIds, c.id] : courseIds.filter((x) => x !== c.id) })} />
                <span className="truncate">{c.emoji} {c.title}</span>
              </label>
            ))}
            {!u.course_options?.length && <p className="text-sm text-muted">{t("school.units.noCourses")}</p>}
          </div>
        )}
      </Card>

      <Card className="space-y-2">
        <h3 className="font-display text-lg font-bold">{t("school.units.groups")}</h3>
        {scoped ? (
          <>
            <ul className="text-sm">{u.groups.map((g) => <li key={g.id} className="flex justify-between py-0.5"><span>{g.name}</span><code className="font-mono text-xs">{g.join_code}</code></li>)}</ul>
            <form className="flex gap-2" onSubmit={(e: FormEvent) => { e.preventDefault(); void run(async () => { set(await school.addUnitGroup(slug, id, groupName.trim())); setGroupName(""); }); }}>
              <input value={groupName} onChange={(e) => setGroupName(e.target.value)} maxLength={80} placeholder={t("org.classPlaceholder")} aria-label={t("org.className")} className={cn(input, "min-w-0 flex-1")} />
              <Button type="submit" className="py-1.5 text-sm" disabled={!groupName.trim()}>{t("org.addClass")}</Button>
            </form>
          </>
        ) : (
          <div className="grid gap-1 sm:grid-cols-2">
            {(groups ?? []).filter((g) => g.name !== "Everyone").map((g) => (
              <label key={g.id} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={groupIds.includes(g.id)} onChange={(e) => void save({ group_ids: e.target.checked ? [...groupIds, g.id] : groupIds.filter((x) => x !== g.id) })} />
                {g.name} <span className="text-xs text-muted">({g.members})</span>
              </label>
            ))}
          </div>
        )}
      </Card>

      <Card className="space-y-2">
        <h3 className="font-display text-lg font-bold">{t("school.units.admins")}</h3>
        <p className="text-xs text-muted">{t("school.units.adminsHint")}</p>
        <ul className="text-sm">
          {u.admins.map((a) => (
            <li key={a.id} className="flex items-center gap-2 py-0.5">
              <span className="flex-1">{a.name} <span className="text-muted">· {a.email}</span></span>
              {!scoped && <button onClick={() => void run(async () => { await school.removeUnitAdmin(slug, id, a.id); await qc.invalidateQueries({ queryKey: key }); })} aria-label={t("lab.delete")}><X className="h-4 w-4 text-muted" /></button>}
            </li>
          ))}
          {u.pending_admins?.map((e) => <li key={e} className="text-muted">{e} · {t("school.pending")}</li>)}
        </ul>
        {!scoped && (
          <form className="flex gap-2" onSubmit={(e: FormEvent) => { e.preventDefault(); setUnsent(null); void run(async () => { const r = await school.inviteUnitAdmin(slug, id, email.trim()); set(r); setUnsent(r); setEmail(""); }); }}>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder={t("school.units.adminEmail")} aria-label={t("school.units.adminEmail")} className={cn(input, "min-w-0 flex-1")} />
            <Button type="submit" className="py-1.5 text-sm" disabled={!email.includes("@")}>{t("school.units.invite")}</Button>
          </form>
        )}
        <UnsentInvites mail={unsent} />
      </Card>

      <Card className="space-y-2">
        <h3 className="font-display text-lg font-bold">{t("school.units.assignments")}</h3>
        <form className="flex flex-wrap gap-2" onSubmit={(e: FormEvent) => {
          e.preventDefault();
          if (!assign.course || !assign.group) return;
          void run(async () => {
            await school.unitAssign(slug, id, { curriculum_id: assign.course as number, group_id: assign.group as number, due_at: assign.due ? new Date(assign.due).toISOString() : null });
            setAssign({ course: "", group: "", due: "" });
            await qc.invalidateQueries({ queryKey: ["school-unit-assign", slug, id] });
          });
        }}>
          <select value={assign.course} onChange={(e) => setAssign({ ...assign, course: e.target.value ? Number(e.target.value) : "" })} aria-label={t("school.course")} className={input}>
            <option value="">{t("school.pickCourse")}</option>
            {(u.course_options ?? []).map((c) => <option key={c.id} value={c.id}>{c.emoji} {c.title}</option>)}
          </select>
          <select value={assign.group} onChange={(e) => setAssign({ ...assign, group: e.target.value ? Number(e.target.value) : "" })} aria-label={t("org.className")} className={input}>
            <option value="">{t("school.pickGroup")}</option>
            {u.groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
          </select>
          <input type="date" value={assign.due} onChange={(e) => setAssign({ ...assign, due: e.target.value })} aria-label={t("school.due")} className={input} />
          <Button type="submit" className="py-1.5 text-sm" disabled={!assign.course || !assign.group}>{t("school.assign")}</Button>
        </form>
        <ul className="divide-y divide-line text-sm">
          {assigned?.map((a) => (
            <li key={a.id} className="flex items-center gap-2 py-1.5">
              <span className="flex-1">{a.course ? `${a.course.emoji} ${a.course.title}` : "—"} <span className="text-muted">· {a.group?.name}{a.due_at && ` · ${fmtDate(a.due_at, i18n.language)}`}</span></span>
              <span className="tabular-nums text-muted">{a.completed}/{a.learners}</span>
              <button onClick={() => void run(async () => { await school.unitUnassign(slug, id, a.id); await qc.invalidateQueries({ queryKey: ["school-unit-assign", slug, id] }); })} aria-label={t("lab.delete")}><Trash2 className="h-4 w-4 text-muted" /></button>
            </li>
          ))}
        </ul>
      </Card>

      <Card className="space-y-2">
        <h3 className="font-display text-lg font-bold">{t("school.units.learners")} ({learners?.learners.length ?? 0})</h3>
        {!learners?.learners.length ? <p className="text-sm text-muted">{t("school.units.noLearners")}</p> : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead><tr className="text-left text-xs text-muted"><th className="py-1 pr-3">{t("org.learner")}</th>{learners.fields.map((f) => <th key={f.key} className="py-1 pr-3">{f.label}</th>)}</tr></thead>
              <tbody>
                {learners.learners.map((m) => (
                  <tr key={m.id} className="border-t border-line"><td className="py-1 pr-3">{m.name} <span className="text-muted">· {m.email}</span></td>
                    {learners.fields.map((f) => <td key={f.key} className="py-1 pr-3">{m.fields[f.key] ?? ""}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

// ── Knowledge base ───────────────────────────────────────────────────

const STATUS_CLS: Record<KbStatus, string> = {
  queued: "bg-surface-2 text-muted", reading: "bg-amber-100 text-amber-800", ready: "bg-good/15 text-good", failed: "bg-bad/15 text-bad",
};

export function KnowledgeTab({ slug, canAdmin }: { slug: string; canAdmin: boolean }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [view, setView] = useState<"docs" | "graph">("docs");
  const { data } = useQuery({
    queryKey: ["school-kb", slug], queryFn: () => school.knowledge(slug),
    refetchInterval: (q) => (q.state.data?.some((d) => KB_BUSY.includes(d.status)) ? 2000 : false),
  });
  const [busy, setBusy] = useState(false);
  const { err, run } = useErr();
  const [localErr, setLocalErr] = useState("");
  const upload = async (files: FileList | null) => {
    setLocalErr("");
    const list = [...(files ?? [])];
    if (list.some((f) => f.size > MAX_UPLOAD)) return setLocalErr(t("school.err.too_large"));
    setBusy(true);
    await run(async () => {
      for (const f of list) await school.uploadKnowledge(slug, f);
    });
    setBusy(false);
    void qc.invalidateQueries({ queryKey: ["school-kb", slug] });
  };
  return (
    <div className="space-y-4">
      <Card className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="font-display text-lg font-bold">{t("school.kb.title")}</h2>
            <p className="text-xs text-muted">{t("school.kb.hint")}</p>
          </div>
          <Segmented label={t("school.kb.title")} value={view} onChange={setView} options={[{ value: "docs", label: t("school.kb.docs") }, { value: "graph", label: t("school.kb.graph") }]} />
        </div>
        {canAdmin && view === "docs" && (
          <label className={cn("flex cursor-pointer items-center justify-center gap-2 rounded-xl border-2 border-dashed border-line px-4 py-5 text-sm font-semibold text-accent hover:border-accent", busy && "pointer-events-none opacity-60")}>
            <Upload className="h-5 w-5" /> {busy ? t("studio.lecture.uploading") : t("school.kb.upload")}
            <input type="file" multiple accept=".pdf,.docx,.txt,.md,application/pdf" className="sr-only" onChange={(e) => { void upload(e.target.files); e.target.value = ""; }} />
          </label>
        )}
        {(err || localErr) && <p role="alert" className="text-sm text-bad">{localErr || err}</p>}
      </Card>
      {view === "graph" ? <KnowledgeGraph slug={slug} /> : (
        <Card>
          {!data?.length ? <p className="text-sm text-muted">{t("school.kb.none")}</p> : (
            <ul className="divide-y divide-line">
              {data.map((d) => (
                <li key={d.id} className="flex flex-wrap items-center gap-3 py-2.5">
                  <FileText className="h-5 w-5 shrink-0 text-muted" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{d.title}</p>
                    <p className="text-xs text-muted">{d.kind.toUpperCase()} · {Math.max(1, Math.round(d.size / 1024))} KB · {fmtDate(d.created_at, i18n.language)}{d.pages ? ` · ${t("school.kb.pages", { count: d.pages })}` : ""}</p>
                    {!!d.topics.length && <p className="mt-1 flex flex-wrap gap-1">{d.topics.map((x) => <span key={x} className="rounded-full bg-surface-2 px-2 py-0.5 text-xs">{x}</span>)}</p>}
                    {d.status === "failed" && <p className="text-xs text-bad">{t(`school.err.${d.error}`, { defaultValue: t("school.kb.failedGeneric") })}</p>}
                  </div>
                  {canAdmin ? (
                    <label className="flex items-center gap-1 text-xs" title={t("schoolKb.audienceHint")}>
                      <input type="checkbox" checked={d.learners_can_read} onChange={(e) => void run(async () => {
                        await school.setKnowledgeAudience(slug, d.id, e.target.checked);
                        await qc.invalidateQueries({ queryKey: ["school-kb", slug] });
                      })} /> {t("schoolKb.learnersCanRead")}
                    </label>
                  ) : <span className="text-xs text-muted">{d.learners_can_read ? t("schoolKb.learnersCanRead") : t("schoolKb.staffOnly")}</span>}
                  <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", STATUS_CLS[d.status])}>{t(`school.kb.status.${d.status}`)}</span>
                  {canAdmin && <button onClick={async () => (await confirmDialog(t("school.kb.confirmDelete"), { danger: true })) && void run(async () => { await school.deleteKnowledge(slug, d.id); await qc.invalidateQueries({ queryKey: ["school-kb", slug] }); })} aria-label={t("lab.delete")}><Trash2 className="h-4 w-4 text-muted" /></button>}
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </div>
  );
}

function KnowledgeGraph({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const { data } = useQuery({ queryKey: ["school-kb-graph", slug], queryFn: () => school.graph(slug) });
  const [focus, setFocus] = useState<string | null>(null);
  const layout = useMemo(() => layoutGraph(data ?? ({ documents: [], topics: [], links: [] } as KbGraph)), [data]);
  if (!data) return <p className="text-muted">{t("common.loading")}</p>;
  if (!data.documents.length) return <Card><p className="text-sm text-muted">{t("school.kb.graphEmpty")}</p></Card>;
  const pos = Object.fromEntries(layout.nodes.map((n) => [n.id, n]));
  const near = new Set(focus ? layout.edges.filter((e) => e.from === focus || e.to === focus).flatMap((e) => [e.from, e.to]) : []);
  return (
    <Card className="space-y-2">
      <p className="text-xs text-muted">{t("school.kb.graphHint")}</p>
      <svg viewBox="0 0 520 520" role="img" aria-label={t("school.kb.graph")} className="mx-auto w-full max-w-xl">
        {layout.edges.map((e) => (
          <line key={`${e.from}-${e.to}`} x1={pos[e.from].x} y1={pos[e.from].y} x2={pos[e.to].x} y2={pos[e.to].y}
            stroke="var(--border)" strokeWidth={focus && (e.from === focus || e.to === focus) ? 2.5 : 1} opacity={focus && !(e.from === focus || e.to === focus) ? 0.25 : 1} />
        ))}
        {layout.nodes.map((n) => (
          <g key={n.id} tabIndex={0} role="button" aria-label={n.label} onMouseEnter={() => setFocus(n.id)} onMouseLeave={() => setFocus(null)} onFocus={() => setFocus(n.id)} onBlur={() => setFocus(null)}
            opacity={focus && focus !== n.id && !near.has(n.id) ? 0.3 : 1} className="cursor-default outline-none">
            {n.kind === "topic" ? <circle cx={n.x} cy={n.y} r={n.r} fill="var(--accent)" /> : <rect x={n.x - n.r} y={n.y - n.r} width={n.r * 2} height={n.r * 2} rx={3} fill="var(--surface)" stroke="var(--text)" strokeWidth={1.5} />}
            <text x={n.x} y={n.y + n.r + 11} textAnchor="middle" fontSize={n.kind === "topic" ? 11 : 10} fontWeight={n.kind === "topic" ? 700 : 400} fill="var(--text)">
              {n.label.length > 22 ? `${n.label.slice(0, 21)}…` : n.label}
            </text>
          </g>
        ))}
      </svg>
      <p className="flex flex-wrap gap-4 text-xs text-muted">
        <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded-full bg-accent" /> {t("school.kb.legendTopic")}</span>
        <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded-sm border border-ink" /> {t("school.kb.legendDoc")}</span>
      </p>
    </Card>
  );
}

// ── Cohorts ──────────────────────────────────────────────────────────

const dayIso = (d: string, end = false) => new Date(`${d}T${end ? "23:59:00" : "00:00:00"}`).toISOString();
const toDay = (iso: string) => {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

export function CohortsTab({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["school-cohorts", slug], queryFn: () => school.cohorts(slug) });
  const { data: courses } = useQuery({ queryKey: ["school-course-options", slug], queryFn: () => school.courseOptions(slug) });
  const [f, setF] = useState({ name: "", partner: "", start: "", end: "", courses: [] as number[] });
  const { err, run } = useErr();
  return (
    <div className="space-y-4">
      <Card className="space-y-2">
        <h2 className="font-display text-lg font-bold">{t("school.cohorts.title")}</h2>
        <p className="text-xs text-muted">{t("school.cohorts.hint")}</p>
        <form className="space-y-2" onSubmit={(e: FormEvent) => {
          e.preventDefault();
          void run(async () => {
            await school.addCohort(slug, { name: f.name.trim(), partner: f.partner.trim(), starts_at: dayIso(f.start), ends_at: dayIso(f.end, true), course_ids: f.courses });
            setF({ name: "", partner: "", start: "", end: "", courses: [] });
            await qc.invalidateQueries({ queryKey: ["school-cohorts", slug] });
          });
        }}>
          <div className="flex flex-wrap gap-2">
            <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} maxLength={120} placeholder={t("school.cohorts.namePh")} aria-label={t("school.cohorts.name")} className={cn(input, "min-w-0 flex-1")} />
            <input value={f.partner} onChange={(e) => setF({ ...f, partner: e.target.value })} maxLength={120} placeholder={t("school.cohorts.partnerPh")} aria-label={t("school.cohorts.partner")} className={cn(input, "min-w-0 flex-1")} />
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <label className="flex items-center gap-1">{t("school.cohorts.start")} <input type="date" required value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} className={input} /></label>
            <label className="flex items-center gap-1">{t("school.cohorts.end")} <input type="date" required value={f.end} min={f.start} onChange={(e) => setF({ ...f, end: e.target.value })} className={input} /></label>
          </div>
          <div className="grid gap-1 sm:grid-cols-2">
            {(courses ?? []).map((c) => (
              <label key={c.id} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={f.courses.includes(c.id)} onChange={(e) => setF({ ...f, courses: e.target.checked ? [...f.courses, c.id] : f.courses.filter((x) => x !== c.id) })} />
                <span className="truncate">{c.emoji} {c.title}</span>
              </label>
            ))}
            {!courses?.length && <p className="text-sm text-muted">{t("school.units.noCourses")}</p>}
          </div>
          <Button type="submit" className="py-1.5 text-sm" disabled={!f.name.trim() || !f.start || !f.end}><Plus className="h-4 w-4" /> {t("school.cohorts.add")}</Button>
          {err && <p role="alert" className="text-sm text-bad">{err}</p>}
        </form>
      </Card>
      {data?.map((c) => <CohortCard key={c.id} slug={slug} c={c} />)}
    </div>
  );
}

function CohortCard({ slug, c }: { slug: string; c: Cohort }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const { data: groups } = useQuery({ queryKey: ["org-groups", slug], queryFn: () => orgs.groups(slug) });
  const [gids, setGids] = useState<number[]>([]);
  const [emails, setEmails] = useState("");
  const [msg, setMsg] = useState("");
  const [unsent, setUnsent] = useState<InviteMail | null>(null);
  const { err, run } = useErr();
  const refresh = () => qc.invalidateQueries({ queryKey: ["school-cohorts", slug] });
  const stateCls = { upcoming: "bg-surface-2 text-muted", active: "bg-good/15 text-good", ended: "bg-bad/15 text-bad" }[c.state];
  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="font-display text-lg font-bold">{c.name} {c.partner && <span className="text-sm font-normal text-muted">· {c.partner}</span>}</h3>
          <p className="text-sm text-muted">{fmtDate(c.starts_at, i18n.language)} → {fmtDate(c.ends_at, i18n.language)}</p>
        </div>
        <div className="flex items-center gap-2">
          <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", stateCls)}>{t(`school.cohorts.state.${c.state}`)}</span>
          <button onClick={async () => (await confirmDialog(t("school.cohorts.confirmDelete"), { danger: true })) && void run(async () => { await school.deleteCohort(slug, c.id); await refresh(); })} aria-label={t("lab.delete")}><Trash2 className="h-4 w-4 text-muted" /></button>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label className="flex items-center gap-1">{t("school.cohorts.start")} <input type="date" defaultValue={toDay(c.starts_at)} onBlur={(e) => e.target.value && e.target.value !== toDay(c.starts_at) && void run(async () => { await school.saveCohort(slug, c.id, { starts_at: dayIso(e.target.value) }); await refresh(); })} className={input} /></label>
        <label className="flex items-center gap-1">{t("school.cohorts.end")} <input type="date" defaultValue={toDay(c.ends_at)} onBlur={(e) => e.target.value && e.target.value !== toDay(c.ends_at) && void run(async () => { await school.saveCohort(slug, c.id, { ends_at: dayIso(e.target.value, true) }); await refresh(); })} className={input} /></label>
      </div>
      <p className="text-sm">{c.courses.map((x) => `${x.emoji} ${x.title}`).join(" · ") || <span className="text-muted">{t("school.cohorts.noCourses")}</span>}</p>
      <div>
        <p className="text-sm font-semibold">{t("school.cohorts.members", { n: c.members.length })}</p>
        <ul className="flex flex-wrap gap-1.5 pt-1">
          {c.members.map((m) => (
            <li key={m.id} className="flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-xs">{m.name}
              <button onClick={() => void run(async () => { await school.removeCohortMember(slug, c.id, m.id); await refresh(); })} aria-label={t("lab.delete")}><X className="h-3 w-3" /></button></li>
          ))}
          {c.pending.map((e) => <li key={e} className="rounded-full border border-dashed border-line px-2 py-0.5 text-xs text-muted">{e} · {t("school.pending")}</li>)}
        </ul>
      </div>
      <form className="space-y-2" onSubmit={(e: FormEvent) => {
        e.preventDefault();
        setUnsent(null);
        void run(async () => {
          const r = await school.addCohortMembers(slug, c.id, { group_ids: gids, emails: parseEmails(emails) });
          setMsg(t("school.cohorts.added", { added: r.added, invited: r.invited }));
          setUnsent(r);
          setGids([]);
          setEmails("");
          await refresh();
        });
      }}>
        <div className="flex flex-wrap gap-2">
          {groups?.map((g) => (
            <label key={g.id} className="flex items-center gap-1 text-sm"><input type="checkbox" checked={gids.includes(g.id)} onChange={(e) => setGids(e.target.checked ? [...gids, g.id] : gids.filter((x) => x !== g.id))} /> {g.name}</label>
          ))}
        </div>
        <textarea value={emails} onChange={(e) => setEmails(e.target.value)} rows={2} placeholder={t("school.cohorts.emailsPh")} aria-label={t("school.cohorts.emailsPh")} className={cn(input, "w-full")} />
        <div className="flex items-center gap-2">
          <Button type="submit" className="py-1.5 text-sm" disabled={!gids.length && !parseEmails(emails).length}>{t("school.cohorts.addMembers")}</Button>
          {msg && <span className="text-sm text-good">{msg}</span>}
        </div>
        <UnsentInvites mail={unsent} />
        {err && <p role="alert" className="text-sm text-bad">{err}</p>}
      </form>
    </Card>
  );
}

// ── Set up with Kili ─────────────────────────────────────────────────

export function SetupWithKili({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const key = ["school-setup-chat", slug];
  const { data } = useQuery({ queryKey: key, queryFn: () => school.setupChat(slug) });
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState<Record<number, Set<number>>>({});
  const { err, run } = useErr();
  const box = useRef<HTMLDivElement>(null);
  const msgs = data?.messages ?? [];
  useEffect(() => {
    box.current?.scrollTo({ top: box.current.scrollHeight });
  }, [msgs.length]);
  const openIdx = (m: SetupMsg) => (m.proposals ?? []).map((_, i) => i).filter((i) => !m.applied?.includes(i) && !m.rejected?.includes(i) && !m.errors?.[String(i)]);
  // Nothing is pre-selected: the admin ticks each change after reading it in full.
  const selected = (turn: number) => picked[turn] ?? new Set<number>();
  const after = () => {
    for (const k of ["org-settings", "org-setup", "org-groups", "school-units", "org-competency", "my-brand"]) void qc.invalidateQueries({ queryKey: [k] });
    for (const k of ["org-settings", "org-setup", "org-groups", "school-units", "org-competency"]) void qc.invalidateQueries({ queryKey: [k, slug] });
  };
  const describe = (p: Proposal) => {
    if (p.op === "set_feature") return t("school.kili.op.set_feature", { feature: t(`orgx.feature.${p.feature}`, { defaultValue: p.feature }), state: p.on ? t("school.kili.on") : t("school.kili.off") });
    if (p.op === "set_target_roles") return t("school.kili.op.set_target_roles", { roles: p.roles.join(", ") });
    return t(`school.kili.op.${p.op}`, { title: p.title });
  };
  const send = (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim() || busy) return;
    setBusy(true);
    void run(async () => {
      qc.setQueryData(key, await school.setupSay(slug, text.trim()));
      setText("");
    }).finally(() => setBusy(false));
  };
  const apply = (turn: number, m: SetupMsg) => {
    const sel = selected(turn), open = openIdx(m);
    setBusy(true);
    void run(async () => {
      const r = await school.setupApply(slug, turn, open.filter((i) => sel.has(i)), open.filter((i) => !sel.has(i)));
      qc.setQueryData(key, r);
      after();
    }).finally(() => setBusy(false));
  };
  const full = !!data && data.turns >= data.max_turns;
  return (
    <Card className="flex max-h-[80vh] flex-col gap-3 border-2 border-accent/40">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="font-display text-lg font-bold">{t("school.kili.title")}</h2>
          <p className="text-xs text-muted">{t("school.kili.sub")}</p>
        </div>
        {!!msgs.length && <Button variant="ghost" className="py-1 text-xs" onClick={() => void run(async () => { qc.setQueryData(key, await school.setupReset(slug)); setPicked({}); })}><RotateCcw className="h-3.5 w-3.5" /> {t("school.kili.restart")}</Button>}
      </div>
      <div ref={box} className="min-h-32 flex-1 space-y-3 overflow-y-auto pr-1" aria-live="polite">
        {!msgs.length && <p className="rounded-2xl border border-line bg-surface px-3 py-2 text-sm">{t("school.kili.hello")}</p>}
        {msgs.map((m, turn) => (
          <div key={turn} className={cn("space-y-2", m.role === "user" && "flex justify-end")}>
            <p className={cn("w-fit max-w-[95%] whitespace-pre-line rounded-2xl px-3 py-2 text-sm", m.role === "user" ? "bg-accent text-accent-ink" : "border border-line bg-surface")}>{m.content}</p>
            {m.role === "assistant" && !!m.proposals?.length && (
              <div className="space-y-1.5 rounded-2xl border-2 border-dashed border-accent/40 p-2">
                {m.proposals.map((p, i) => {
                  const applied = m.applied?.includes(i), rejected = m.rejected?.includes(i), error = m.errors?.[String(i)];
                  return (
                    <label key={i} className={cn("flex items-start gap-2 rounded-xl px-2 py-1 text-sm", applied && "bg-good/10", (rejected || error) && "opacity-60")}>
                      {applied ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-good" /> : rejected || error ? <X className="mt-0.5 h-4 w-4 shrink-0 text-muted" /> : (
                        <input type="checkbox" className="mt-1" checked={selected(turn).has(i)} onChange={() => setPicked((s) => {
                          const n = new Set(s[turn] ?? selected(turn));
                          if (n.has(i)) n.delete(i);
                          else n.add(i);
                          return { ...s, [turn]: n };
                        })} />
                      )}
                      <span className="min-w-0">
                        <span className="font-medium">{describe(p)}</span>
                        {p.text && <span className="block whitespace-pre-line break-words text-xs text-muted">{p.text}</span>}
                        {error && <span className="block text-xs text-bad">{t(`school.err.${error}`, { defaultValue: error })}</span>}
                      </span>
                    </label>
                  );
                })}
                {openIdx(m).length > 0 && (
                  <div className="flex gap-2 pt-1">
                    <Button className="py-1.5 text-sm" loading={busy} onClick={() => apply(turn, m)}>{t("school.kili.apply", { n: selected(turn).size })}</Button>
                    <Button variant="ghost" className="py-1.5 text-sm" onClick={() => setPicked((s) => ({ ...s, [turn]: new Set() }))}>{t("studio.chat.none")}</Button>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        {busy && <p className="text-sm text-muted">{t("mentor.thinking")}</p>}
      </div>
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
      {full ? <p className="text-sm text-muted">{t("school.kili.full")}</p> : (
        <form onSubmit={send} className="flex gap-2">
          <input value={text} onChange={(e) => setText(e.target.value)} maxLength={1500} placeholder={t("school.kili.ph")} aria-label={t("school.kili.ph")}
            className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent" />
          <button disabled={!text.trim() || busy} aria-label={t("mentor.send")} className="rounded-xl bg-accent p-2.5 text-accent-ink disabled:opacity-50"><Send className="h-4 w-4" /></button>
        </form>
      )}
    </Card>
  );
}
