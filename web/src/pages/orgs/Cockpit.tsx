import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Armchair, Award, MonitorPlay, BarChart3, Briefcase, ClipboardList, Copy, Download, Megaphone, Plug, Plus, Presentation, RefreshCw, Settings2, Sparkles, Users } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { alertDialog, confirmDialog } from "@/lib/dialog";
import { localeOf } from "@/i18n/languages";
import { HBars, NpsBar, TimeBars } from "@/components/charts";
import { PageError } from "@/components/PageState";
import { Button, Card, Segmented } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { dropInviteLink, orgs, RANK, type InviteMail, type Role } from "@/lib/orgs";
import { AskOrg } from "@/components/orgs/AskOrg";
import { ClassBoardToggle } from "@/components/orgs/ClassBoard";
import { PendingInvites } from "@/components/orgs/PendingInvites";
import { UnsentInvites } from "@/components/orgs/UnsentInvites";
import { useAuth } from "@/stores/auth";
import { useAutoTour } from "@/components/tour/tourStore";

import { GrowthTab, SeatsTab, SettingsTab, SetupChecklist } from "./OrgAdmin";
import { CohortsTab, KnowledgeTab, UnitsTab } from "./School";
import { Building2, CalendarRange, Library } from "lucide-react";
import { BanksManager, SurveyBuilder } from "./SurveyBuilder";
import AssignmentsTab from "./teach/AssignmentsTab";
import PilotReport from "./teach/PilotReport";
import { OrgCertificates } from "@/components/credentials/OrgCertificates";
import { ResultsHeader } from "@/components/surveys/ResultsHeader";
import { downloadFile } from "@/lib/download";
import { studio } from "@/lib/studio";
import { orgWorkshops, runsKey } from "@/lib/orgWorkshops";

import IntegrationsTab from "./IntegrationsTab";
import WorkshopsTab from "./WorkshopsTab";

type Tab = "integrations" | "workshops" | "units" | "knowledge" | "cohorts" | "overview" | "classes" | "members" | "assignments" | "certificates" | "surveys" | "competency" | "settings" | "growth" | "seats" | "pilot";
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`);

function Kpi({ label, value }: { label: string; value: ReactNode }) {
  return <Card className="p-4"><p className="text-xs text-muted">{label}</p><p className="font-display text-2xl font-extrabold tabular-nums">{value}</p></Card>;
}

function Overview({ slug }: { slug: string }) {
  const { t, i18n } = useTranslation();
  const { data: a, error, refetch } = useQuery({ queryKey: ["org-analytics", slug], queryFn: () => orgs.analytics(slug) });
  const [ins, setIns] = useState<{ headline: string; insights: string[]; actions: string[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState<number[]>([]);
  const [msg, setMsg] = useState("");
  if (error && !a) return <PageError error={error} onRetry={() => void refetch()} />;
  if (!a) return <p className="text-muted">{t("common.loading")}</p>;
  const fmtDay = (d: string) => new Date(d).toLocaleDateString(localeOf(i18n.language), { day: "numeric", month: "short" });
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Kpi label={t("org.kpi.learners")} value={a.kpis.learners} />
        <Kpi label={t("org.kpi.active7")} value={a.kpis.active_7d} />
        <Kpi label={t("org.kpi.lessons30")} value={a.kpis.lessons_completed_30d} />
        <Kpi label={t("org.kpi.avgScore")} value={pct(a.kpis.avg_score)} />
        <Kpi label={t("org.kpi.assignments")} value={a.kpis.assignments} />
        <Kpi label={t("org.kpi.completion")} value={pct(a.kpis.completion_rate)} />
      </div>
      <Card className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 font-display text-lg font-bold"><Sparkles className="h-5 w-5 text-accent" /> {t("org.insights")}</h2>
          <div className="flex flex-wrap gap-2">
            <Button variant="ghost" className="py-1.5 text-sm" onClick={() => void downloadFile(studio.urls.orgXlsx(slug), "analytics.xlsx")}><Download className="h-4 w-4" /> Excel</Button>
            <Button variant="outline" className="py-1.5 text-sm" loading={busy} onClick={async () => { setBusy(true); try { setIns(await orgs.insights(slug)); } finally { setBusy(false); } }}>{t("org.getInsights")}</Button>
          </div>
        </div>
        {ins && (
          <div className="space-y-2 text-sm">
            <p className="font-semibold">{ins.headline}</p>
            <ul className="list-disc pl-5">{ins.insights.map((x) => <li key={x}>{x}</li>)}</ul>
            <p className="font-semibold">{t("org.nextSteps")}</p>
            <ul className="list-disc pl-5">{ins.actions.map((x) => <li key={x}>{x}</li>)}</ul>
          </div>
        )}
      </Card>
      <AskOrg slug={slug} />
      <div className="grid gap-5 lg:grid-cols-2">
        <Card><TimeBars title={t("org.chart.active")} valueLabel={t("org.chart.learners")} data={a.daily.map((d) => ({ label: fmtDay(d.day), value: d.active }))} /></Card>
        <Card><TimeBars title={t("org.chart.xp")} valueLabel="XP" data={a.daily.map((d) => ({ label: fmtDay(d.day), value: d.xp }))} /></Card>
        <Card><HBars title={t("org.chart.skills")} valueLabel={t("mastery.overall")} max={1} format={pct} empty={t("org.noSkills")}
          data={a.skills.map((s) => ({ label: s.name, value: s.mastery, note: t("org.membersN", { count: s.learners }) }))} /></Card>
        <Card><HBars title={t("org.chart.assignments")} valueLabel={t("org.kpi.completion")} max={1} format={pct} empty={t("org.noAssignments")}
          data={a.assignments.map((x) => ({ label: `${(x.course ?? x.scenario)?.emoji ?? ""} ${(x.course ?? x.scenario)?.title ?? ""}`, value: x.avg_pct }))} /></Card>
      </div>
      <Card className="space-y-3">
        <h2 className="flex items-center gap-2 font-display text-lg font-bold"><AlertTriangle className="h-5 w-5 text-amber-600" /> {t("org.atRisk")} ({a.at_risk.length})</h2>
        {a.at_risk.length === 0 ? <p className="text-sm text-muted">{t("org.allGood")}</p> : (
          <>
            <ul className="divide-y divide-line">
              {a.at_risk.map((r) => (
                <li key={r.user_id} className="flex items-center gap-3 py-2">
                  <input type="checkbox" checked={picked.includes(r.user_id)} onChange={(e) => setPicked(e.target.checked ? [...picked, r.user_id] : picked.filter((x) => x !== r.user_id))} aria-label={r.name} />
                  <span className="flex-1 font-medium">{r.name}</span>
                  {r.reasons.map((x) => <span key={x} className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">{t(`org.reason.${x}`)}</span>)}
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap items-center gap-2">
              <Button disabled={!picked.length} onClick={async () => { const r = await orgs.nudge(slug, picked); setMsg(t("org.nudged", { count: r.nudged })); setPicked([]); }}>
                <Megaphone className="h-4 w-4" /> {t("org.nudge")} ({picked.length})
              </Button>
              {msg && <span className="text-sm text-good">{msg}</span>}
            </div>
          </>
        )}
      </Card>
    </div>
  );
}

function Classes({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["org-groups", slug], queryFn: () => orgs.groups(slug) });
  const [name, setName] = useState("");
  const [copied, setCopied] = useState<number | null>(null);
  return (
    <div className="space-y-4">
      <Card>
        <form className="flex gap-2" onSubmit={async (e: FormEvent) => { e.preventDefault(); qc.setQueryData(["org-groups", slug], await orgs.addGroup(slug, name.trim())); setName(""); }}>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} placeholder={t("org.classPlaceholder")} className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2" aria-label={t("org.className")} />
          <Button type="submit" disabled={!name.trim()}>{t("org.addClass")}</Button>
        </form>
      </Card>
      <div className="grid gap-3 sm:grid-cols-2">
        {data?.map((g) => (
          <Card key={g.id} className="space-y-2">
            <p className="font-display text-lg font-bold">{g.name}</p>
            <p className="text-sm text-muted">{t("org.membersN", { count: g.members })}</p>
            <div className="flex flex-wrap items-center gap-2">
              <code className="rounded-lg bg-surface-2 px-3 py-1.5 font-mono text-lg tracking-[0.3em]">{g.join_code}</code>
              <Button variant="ghost" className="py-1 text-sm" onClick={() => { void navigator.clipboard.writeText(`${location.origin}/join/${g.join_code}`); setCopied(g.id); }}>
                <Copy className="h-4 w-4" /> {copied === g.id ? t("game.copied") : t("org.copyJoin")}
              </Button>
              <Button variant="ghost" className="py-1 text-sm" title={t("org.newCode")} onClick={async () => { await orgs.newCode(slug, g.id); void qc.invalidateQueries({ queryKey: ["org-groups", slug] }); }}><RefreshCw className="h-4 w-4" /></Button>
            </div>
            <ClassBoardToggle slug={slug} id={g.id} />
          </Card>
        ))}
      </div>
    </div>
  );
}

function Members({ slug, myRole }: { slug: string; myRole: Role }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: all } = useQuery({ queryKey: ["org-members", slug], queryFn: () => orgs.members(slug) });
  const { data: st } = useQuery({ queryKey: ["org-settings", slug], queryFn: () => orgs.settings(slug) });
  const defs = st?.member_fields ?? [];
  const [filter, setFilter] = useState<{ key: string; value: string }>({ key: "", value: "" });
  const data = all?.filter((m) => !filter.key || !filter.value || (m.fields ?? {})[filter.key] === filter.value);
  const [emails, setEmails] = useState("");
  const [role, setRole] = useState<Role>("learner");
  const [msg, setMsg] = useState("");
  const [unsent, setUnsent] = useState<InviteMail | null>(null);
  const canManage = RANK[myRole] >= RANK.admin;
  const grantable = (["learner", "manager", "admin", "owner"] as Role[]).filter((r) => RANK[r] <= RANK[myRole]);
  async function invite(e: FormEvent) {
    e.preventDefault();
    const list = emails.split(/[\s,;]+/).filter((x) => x.includes("@"));
    setUnsent(null);
    try {
      const r = await orgs.invite(slug, list, role);
      setMsg(r.emailed === false ? "" : t("org.invited", { count: r.invited.length }));
      setUnsent(r);
      setEmails("");
      void qc.invalidateQueries({ queryKey: ["org-pending-invites", slug] });
    } catch {
      setMsg(t("mentor.errors.generic"));
    }
  }
  return (
    <div className="space-y-4">
      <Card>
        <form onSubmit={invite} className="space-y-2">
          <h2 className="font-display text-lg font-bold">{t("org.inviteTitle")}</h2>
          <textarea value={emails} onChange={(e) => setEmails(e.target.value)} rows={2} placeholder="student1@school.in, student2@school.in" className="w-full rounded-xl border-2 border-line bg-surface p-2 text-sm" aria-label={t("auth.email")} />
          <div className="flex flex-wrap items-center gap-2">
            <Segmented label={t("org.role")} value={role} onChange={setRole} options={(myRole === "manager" ? ["learner"] as Role[] : grantable.filter((r) => r !== "owner")).map((r) => ({ value: r, label: t(`org.roles.${r}`) }))} />
            <Button type="submit" disabled={!emails.includes("@")}>{t("org.sendInvites")}</Button>
          </div>
          {msg && <p role="status" className="text-sm text-muted">{msg}</p>}
          <UnsentInvites mail={unsent} />
        </form>
        <PendingInvites slug={slug} onRevoked={(email) => setUnsent((u) => dropInviteLink(u, email))} />
      </Card>
      {!!defs.length && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted">{t("orgx.filter")}</span>
          <select value={filter.key} onChange={(e) => setFilter({ key: e.target.value, value: "" })} className="rounded-lg border-2 border-line bg-surface px-2 py-1" aria-label={t("orgx.filter")}>
            <option value="">—</option>{defs.map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}
          </select>
          {filter.key && <input value={filter.value} onChange={(e) => setFilter({ ...filter, value: e.target.value })} className="rounded-lg border-2 border-line bg-surface px-2 py-1" aria-label={t("orgx.value")} />}
          <span className="text-xs text-muted">{t("orgx.shown", { n: data?.length ?? 0 })}</span>
        </div>
      )}
      <Card className="divide-y divide-line p-0">
        {data?.map((m) => (
          <div key={m.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
            <div className="min-w-0 flex-1"><p className="font-semibold">{m.name}{m.seat && <span className="ml-2 rounded-full bg-good/15 px-2 py-0.5 text-[10px] font-semibold text-good">{t("orgx.seat")}</span>}</p><p className="truncate text-xs text-muted">{m.email}</p></div>
            {defs.map((d) => d.type === "select" ? (
              <select key={d.key} value={(m.fields ?? {})[d.key] ?? ""} aria-label={d.label} onChange={async (e) => { await orgs.setFields(slug, m.id, { [d.key]: e.target.value }); void qc.invalidateQueries({ queryKey: ["org-members", slug] }); }}
                className="rounded-lg border-2 border-line bg-surface px-2 py-1 text-xs"><option value="">{d.label}</option>{d.options?.map((o) => <option key={o} value={o}>{o}</option>)}</select>
            ) : (
              <input key={d.key} defaultValue={(m.fields ?? {})[d.key] ?? ""} placeholder={d.label} aria-label={d.label} maxLength={80}
                onBlur={async (e) => { if (e.target.value !== ((m.fields ?? {})[d.key] ?? "")) { await orgs.setFields(slug, m.id, { [d.key]: e.target.value }); void qc.invalidateQueries({ queryKey: ["org-members", slug] }); } }}
                className="w-24 rounded-lg border-2 border-line bg-surface px-2 py-1 text-xs" />
            ))}
            {canManage && RANK[m.role] <= RANK[myRole] ? (
              <select value={m.role} onChange={async (e) => {
                try { await orgs.setRole(slug, m.id, e.target.value as Role); } catch (err) { if (err instanceof ApiError) void alertDialog(t(`org.err.${err.data?.code ?? "generic"}`, { defaultValue: t("mentor.errors.generic") })); }
                void qc.invalidateQueries({ queryKey: ["org-members", slug] });
              }} className="rounded-lg border-2 border-line bg-surface px-2 py-1 text-sm" aria-label={t("org.role")}>
                {grantable.map((r) => <option key={r} value={r}>{t(`org.roles.${r}`)}</option>)}
              </select>
            ) : <span className="rounded-full bg-surface-2 px-2.5 py-0.5 text-xs font-semibold">{t(`org.roles.${m.role}`)}</span>}
          </div>
        ))}
      </Card>
    </div>
  );
}

function Surveys({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["org-surveys", slug], queryFn: () => orgs.surveys(slug) });
  const { data: templates } = useQuery({ queryKey: ["survey-templates"], queryFn: orgs.templates });
  const [open, setOpen] = useState<number | null>(null);
  const [allAttempts, setAllAttempts] = useState(false);
  const res = useQuery({ queryKey: ["survey-results", slug, open, allAttempts], queryFn: () => orgs.results(slug, open!, allAttempts), enabled: !!open });
  const [summary, setSummary] = useState<Awaited<ReturnType<typeof orgs.summary>> | null>(null);
  const [sumErr, setSumErr] = useState("");
  const [building, setBuilding] = useState<"new" | number | null>(null);
  const [copied, setCopied] = useState<number | null>(null);
  const refresh = () => void qc.invalidateQueries({ queryKey: ["org-surveys", slug] });
  async function csv(id: number) {
    const r = await fetch(`/api/orgs/${slug}/surveys/${id}/results/?export=csv`, { headers: { Authorization: `Bearer ${useAuth.getState().access}` } });
    const url = URL.createObjectURL(await r.blob());
    Object.assign(document.createElement("a"), { href: url, download: `survey-${id}.csv` }).click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="space-y-4">
      <Card className="space-y-2">
        <h2 className="font-display text-lg font-bold">{t("org.newSurvey")}</h2>
        <div className="flex flex-wrap gap-2">
          <Button className="py-1.5 text-sm" onClick={() => setBuilding("new")}><Plus className="h-4 w-4" /> {t("survey.newCustom")}</Button>
          {templates?.map((tp) => <Button key={tp.key} variant="outline" className="py-1.5 text-sm" onClick={async () => { await orgs.createSurvey(slug, { template: tp.key }); refresh(); }}>{tp.title}</Button>)}
        </div>
        <p className="text-xs text-muted">{t("org.surveyHint")}</p>
      </Card>
      {building === "new" && <SurveyBuilder slug={slug} onSaved={() => { setBuilding(null); refresh(); }} onCancel={() => setBuilding(null)} />}
      <BanksManager slug={slug} />
      {data?.map((s) => (
        <Card key={s.id} className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <ClipboardList className="h-5 w-5 text-accent" />
            <p className="flex-1 font-semibold">{s.title} <span className="text-xs text-muted">· {s.anonymous ? t("org.anonymous") : t("org.named")} · {t("org.responsesN", { count: s.responses })}</span></p>
            <span className={cn("rounded-full px-2.5 py-0.5 text-xs font-semibold", s.status === "open" ? "bg-good/15 text-good" : "bg-surface-2 text-muted")}>{t(`org.status.${s.status}`)}</span>
            {s.status !== "open" ? <Button className="py-1 text-sm" onClick={async () => { await orgs.setSurvey(slug, s.id, { status: "open" }); refresh(); }}>{t("org.openSurvey")}</Button>
              : <Button variant="outline" className="py-1 text-sm" onClick={async () => { await orgs.setSurvey(slug, s.id, { status: "closed" }); refresh(); }}>{t("org.closeSurvey")}</Button>}
            <Button variant="ghost" className="py-1 text-sm" onClick={() => { setOpen(open === s.id ? null : s.id); setSummary(null); setSumErr(""); }}><BarChart3 className="h-4 w-4" /> {t("org.results")}</Button>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs">
            {s.status === "draft" && <button className="font-semibold text-accent" onClick={() => setBuilding(building === s.id ? null : s.id)}>{t("lab.edit")}</button>}
            <button className="font-semibold text-accent" onClick={async () => { await orgs.cloneSurvey(slug, s.id); refresh(); }}>{t("survey.clone")}</button>
            {s.public && s.public_url && (
              <button className="font-semibold text-accent" onClick={() => { void navigator.clipboard.writeText(s.public_url!); setCopied(s.id); }}>🔗 {copied === s.id ? t("game.copied") : t("survey.copyPublic")}</button>
            )}
            {!!s.draw?.bank && <span className="text-muted">{t("survey.drawsN", { n: s.draw.n })}</span>}
            <button className="ml-auto text-muted hover:text-bad" onClick={async () => { if (await confirmDialog(t("survey.confirmDelete"), { danger: true })) { await orgs.deleteSurvey(slug, s.id); refresh(); } }}>{t("lab.delete")}</button>
          </div>
          {building === s.id && <SurveyBuilder slug={slug} editing={s} onSaved={() => { setBuilding(null); refresh(); }} onCancel={() => setBuilding(null)} />}
          {open === s.id && res.data && (
            <div className="space-y-4">
              <ResultsHeader data={res.data} all={allAttempts} onAll={setAllAttempts} />
              {res.data.results.map((q) => (
                <div key={q.id}>
                  {q.type === "rating" && <HBars title={`${q.text} · ${t("org.avg")} ${q.avg ?? "—"}`} valueLabel={t("org.count")} data={[5, 4, 3, 2, 1].map((n) => ({ label: "★".repeat(n), value: q.distribution[n] ?? 0 }))} />}
                  {(q.type === "choice" || q.type === "multi") && <HBars title={q.text} valueLabel={t("org.count")} data={q.options.map((o: { option: string; count: number }) => ({ label: o.option, value: o.count }))} />}
                  {q.type === "scale" && <HBars title={`${q.text} · ${t("org.avg")} ${q.avg ?? "—"}`} valueLabel={t("org.count")}
                    data={Array.from({ length: q.max - q.min + 1 }, (_, i) => q.min + i).map((n: number) => ({ label: String(n), value: q.distribution[n] ?? 0 }))} />}
                  {q.type === "matrix" && (
                    <div>
                      <p className="mb-1 font-display text-base font-bold">{q.text}</p>
                      <table className="w-full text-sm">
                        <thead><tr><th />{q.rows[0]?.options.map((o: { option: string }) => <th key={o.option} className="px-2 text-xs text-muted">{o.option}</th>)}</tr></thead>
                        <tbody>{q.rows.map((r: { row: string; options: { option: string; count: number }[] }) => (
                          <tr key={r.row} className="border-t border-line"><th scope="row" className="py-1 text-left font-medium">{r.row}</th>
                            {r.options.map((o) => <td key={o.option} className="text-center tabular-nums">{o.count}</td>)}</tr>
                        ))}</tbody>
                      </table>
                    </div>
                  )}
                  {q.type === "nps" && <NpsBar title={q.text} distribution={q.distribution} nps={q.nps} />}
                  {q.type === "text" && (
                    <div>
                      <p className="mb-1 font-display text-base font-bold">{q.text}</p>
                      <ul className="max-h-48 space-y-1 overflow-y-auto text-sm">{q.answers.map((a: { text: string; name: string | null }, i: number) => <li key={i} className="rounded-lg bg-surface-2 px-3 py-1.5">{a.name && <b>{a.name}: </b>}{a.text}</li>)}</ul>
                    </div>
                  )}
                </div>
              ))}
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={async () => { setSumErr(""); try { setSummary(await orgs.summary(slug, s.id)); } catch (e) { setSumErr(e instanceof ApiError && e.data?.code === "not_enough_text" ? t("org.needMore") : t("mentor.errors.generic")); } }}><Sparkles className="h-4 w-4" /> {t("org.summarise")}</Button>
                <Button variant="ghost" onClick={() => csv(s.id)}><Download className="h-4 w-4" /> CSV</Button>
                <Button variant="ghost" onClick={() => void downloadFile(studio.urls.surveyXlsx(slug, s.id), "survey.xlsx")}><Download className="h-4 w-4" /> Excel</Button>
              </div>
              {sumErr && <p className="text-sm text-bad">{sumErr}</p>}
              {summary && (
                <div className="grid gap-3 rounded-xl bg-surface-2 p-3 text-sm sm:grid-cols-2">
                  {(["themes", "positives", "concerns", "suggested_actions"] as const).map((k) => (
                    <div key={k}><p className="font-semibold">{t(`org.sum.${k}`)}</p><ul className="list-disc pl-5">{summary[k].map((x) => <li key={x}>{x}</li>)}</ul></div>
                  ))}
                </div>
              )}
            </div>
          )}
        </Card>
      ))}
    </div>
  );
}

function DpaBanner({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["org-dpa", slug], queryFn: () => api<{ up_to_date: boolean; accepted_at: string | null; accepted_by: string | null; current_version: string }>(`/api/orgs/${slug}/dpa/`) });
  const [agree, setAgree] = useState(false);
  if (!data) return null;
  if (data.up_to_date) return <p className="text-xs text-muted">✅ {t("org.dpaAccepted", { date: new Date(data.accepted_at!).toLocaleDateString(), who: data.accepted_by })} · <Link to="/dpa" className="underline">{t("legal.dpa")}</Link></p>;
  return (
    <Card className="space-y-2 border-2 border-amber-400">
      <p className="font-semibold">{t("org.dpaTitle")}</p>
      <p className="text-sm text-muted">{t("org.dpaSub")}</p>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={agree} onChange={(e) => setAgree(e.target.checked)} /> <span>{t("org.dpaAgree")} <Link to="/dpa" target="_blank" className="font-semibold text-accent underline">{t("legal.dpa")}</Link></span></label>
      <Button disabled={!agree} onClick={async () => { qc.setQueryData(["org-dpa", slug], await api(`/api/orgs/${slug}/dpa/`, { method: "POST", json: { accept: true } })); }}>{t("org.dpaAccept")}</Button>
    </Card>
  );
}

export default function Cockpit() {
  const { t } = useTranslation();
  const { slug = "" } = useParams();
  const { data: org, error } = useQuery({ queryKey: ["org", slug], queryFn: () => orgs.get(slug), retry: false });
  const [tab, setTab] = useState<Tab>("overview");
  useAutoTour("cockpit", !!org && org.role !== "learner");
  // The Workshops tab exists only where the platform admin switched the feature on (the runs list answers 403 otherwise).
  // The org's own `features.workshops` decides when the server sends it; older servers: probe the runs list instead.
  const flag = org?.features?.workshops;
  const { data: wsRuns } = useQuery({ queryKey: runsKey(slug), queryFn: () => orgWorkshops.runs(slug), enabled: !!org && org.role !== "learner" && !org.scoped && typeof flag !== "boolean", retry: false });
  const workshopsOn = !!org && !org.scoped && (typeof flag === "boolean" ? flag : !!wsRuns);
  if (error) return <p className="p-8 text-muted">{t("org.notFound")}</p>;
  if (!org) return <p className="p-8 text-muted">{t("common.loading")}</p>;
  if (org.role === "learner") return <p className="p-8 text-muted">{t("org.learnersOnly")}</p>;
  if (org.scoped) return ( // unit admins: a unit-only cockpit (org-wide pages refuse them server-side)
    <div className="mx-auto max-w-6xl space-y-5 px-4 py-8">
      <header>
        <p className="text-sm text-muted">{t(`org.kinds.${org.kind}`)} · {t("school.units.scopedRole", { units: (org.units ?? []).map((u) => u.name).join(", ") })}</p>
        <h1 className="font-display text-3xl font-extrabold">{org.name}</h1>
        <Link to={`/org/${slug}/journeys`} className="text-sm font-semibold text-accent hover:underline">{t("jr.cockpitLink")}</Link>
      </header>
      <UnitsTab slug={slug} scoped />
    </div>
  );
  const isAdmin = RANK[org.role] >= RANK.admin;
  const tabs: { k: Tab; icon: typeof Users }[] = [
    { k: "overview", icon: BarChart3 }, { k: "classes", icon: Users }, { k: "members", icon: Users }, { k: "assignments", icon: ClipboardList }, { k: "certificates", icon: Award }, { k: "surveys", icon: ClipboardList }, { k: "competency", icon: Briefcase }, { k: "pilot", icon: Presentation },
    { k: "settings", icon: Settings2 }, { k: "growth", icon: Megaphone }, ...(RANK[org.role] >= RANK.admin ? [{ k: "seats" as Tab, icon: Armchair }] : []),
    ...(isAdmin ? [{ k: "units" as Tab, icon: Building2 }] : []), { k: "knowledge" as Tab, icon: Library }, ...(isAdmin ? [{ k: "cohorts" as Tab, icon: CalendarRange }] : []),
    ...(workshopsOn ? [{ k: "workshops" as Tab, icon: MonitorPlay }] : []),
    ...(isAdmin ? [{ k: "integrations" as Tab, icon: Plug }] : []),
  ];
  return (
    <div className="mx-auto max-w-6xl space-y-5 px-4 py-8">
      <header>
        <p className="text-sm text-muted">{t(`org.kinds.${org.kind}`)} · {t(`org.roles.${org.role}`)}</p>
        <h1 className="font-display text-3xl font-extrabold">{org.name}</h1>
        <Link to={`/guests?org=${slug}&tab=campaigns`} className="text-sm font-semibold text-accent hover:underline">{t("guest.entryOrg")}</Link>
        <Link to={`/org/${slug}/journeys`} className="ml-3 text-sm font-semibold text-accent hover:underline">{t("jr.cockpitLink")}</Link>
      </header>
      {RANK[org.role] >= RANK.admin && <DpaBanner slug={slug} />}
      <div role="tablist" className="flex flex-wrap gap-1 rounded-2xl bg-surface-2 p-1">
        {tabs.map(({ k, icon: Icon }) => (
          <button key={k} role="tab" data-tour-tab={k} aria-selected={tab === k} onClick={() => setTab(k)} className={cn("flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold", tab === k ? "bg-surface shadow" : "text-muted hover:text-ink")}>
            <Icon className="h-4 w-4" /> {k === "workshops" ? t("orgWs.tab") : k === "certificates" ? t("cred.tab") : k === "pilot" ? t("teach.tabPilot") : ["units", "knowledge", "cohorts"].includes(k) ? t(`school.tabs.${k}`) : t(`org.tabs.${k}`)}
          </button>
        ))}
      </div>
      {tab === "overview" && RANK[org.role] >= RANK.admin && <SetupChecklist slug={slug} go={(k) => setTab(k as Tab)} />}
      {tab === "overview" && <Overview slug={slug} />}
      {tab === "classes" && <Classes slug={slug} />}
      {tab === "members" && <Members slug={slug} myRole={org.role} />}
      {tab === "assignments" && <AssignmentsTab slug={slug} />}
      {tab === "pilot" && <PilotReport slug={slug} />}
      {tab === "certificates" && <OrgCertificates slug={slug} />}
      {tab === "surveys" && <Surveys slug={slug} />}
      {tab === "competency" && <Competency slug={slug} canEdit={RANK[org.role] >= RANK.admin} />}
      {tab === "settings" && <SettingsTab slug={slug} canAdmin={RANK[org.role] >= RANK.admin} />}
      {tab === "growth" && <GrowthTab slug={slug} canAdmin={RANK[org.role] >= RANK.admin} />}
      {tab === "seats" && <SeatsTabLoader slug={slug} />}
      {tab === "units" && <UnitsTab slug={slug} scoped={false} />}
      {tab === "knowledge" && <KnowledgeTab slug={slug} canAdmin={isAdmin} />}
      {tab === "cohorts" && <CohortsTab slug={slug} />}
      {tab === "workshops" && workshopsOn && <WorkshopsTab slug={slug} role={org.role} />}
      {tab === "integrations" && isAdmin && <IntegrationsTab slug={slug} />}
    </div>
  );
}

/** Competency heat-map: each learner's level (0–4) per skill of the org's target role. */
function Competency({ slug, canEdit }: { slug: string; canEdit: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["org-competency", slug], queryFn: () => orgs.competencies(slug) });
  const [busy, setBusy] = useState(false);
  if (!data) return <p className="text-muted">{t("common.loading")}</p>;
  const setCareer = async (career: string) => {
    setBusy(true);
    try {
      qc.setQueryData(["org-competency", slug], await orgs.setCompetencyCareer(slug, career));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="font-display text-xl font-bold">{data.career ? `${data.career.emoji} ${data.career.title}` : t("org.compTitle")}</h2>
          <p className="text-sm text-muted">{t("org.compSub")}</p>
        </div>
        {canEdit && (
          <select value={data.career?.slug ?? ""} disabled={busy} onChange={(e) => void setCareer(e.target.value)} aria-label={t("org.compRole")}
            className="rounded-xl border-2 border-line bg-surface px-3 py-2 text-sm">
            <option value="">{t("org.compPick")}</option>
            {data.options.map((o) => <option key={o.slug} value={o.slug}>{o.emoji} {o.title}</option>)}
          </select>
        )}
      </div>
      {!data.career && <p className="text-sm text-muted">{canEdit ? t("org.compNone") : t("org.compNoneAsk")}</p>}
      {data.career && !data.rows?.length && <p className="text-sm text-muted">{t("org.compNoLearners")}</p>}
      {data.career && !!data.rows?.length && (
        <div className="overflow-x-auto">
          <table className="min-w-full border-separate border-spacing-0.5 text-sm">
            <thead>
              <tr>
                <th className="sticky left-0 bg-surface px-2 py-1 text-left text-xs text-muted">{t("org.learner")}</th>
                {data.skills!.map((s) => <th key={s.slug} className="px-1 py-1 text-xs font-medium text-muted"><span className="block max-w-24 truncate" title={s.name}>{s.name}</span><span className="tabular-nums">≥{s.required}</span></th>)}
              </tr>
            </thead>
            <tbody>
              {[...data.rows!, { user_id: 0, name: t("org.compAverage"), levels: data.average! }].map((r) => (
                <tr key={r.user_id} className={r.user_id === 0 ? "font-semibold" : ""}>
                  <td className="sticky left-0 bg-surface px-2 py-1">{r.name}</td>
                  {data.skills!.map((s) => {
                    const v = r.levels[s.slug] ?? 0;
                    const below = v < s.required;
                    return (
                      <td key={s.slug} title={`${r.name} · ${s.name}: ${v}/${s.required}`} className="rounded-md px-2 py-1 text-center tabular-nums"
                        style={{ background: `color-mix(in srgb, var(--accent) ${Math.round((Math.min(v, 4) / 4) * 70) + 6}%, var(--surface))` }}>
                        {Number.isInteger(v) ? v : v.toFixed(1)}{below && <span className="ml-0.5 text-[10px]" aria-label={t("org.compBelow")}>▾</span>}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-muted">{t("org.compLegend")}</p>
        </div>
      )}
    </Card>
  );
}

function SeatsTabLoader({ slug }: { slug: string }) {
  const { data } = useQuery({ queryKey: ["org-members", slug], queryFn: () => orgs.members(slug) });
  return <SeatsTab slug={slug} members={data ?? []} />;
}
