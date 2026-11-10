import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Pager } from "@/components/admin/Pager";
import { Button, Card } from "@/components/ui";
import { date, query, type Paged } from "@/lib/admin";
import { api, ApiError } from "@/lib/api";
import { rupees } from "@/lib/billing";
import { cn } from "@/lib/cn";
import { confirmDialog } from "@/lib/dialog";

interface Row { id: number; email: string; name: string; joined: string; last_login: string | null; active: boolean; verified: boolean; staff: boolean; creator: boolean; minor: boolean; orgs: number; courses: number }
type DetailOut = Omit<Row, "orgs" | "courses"> & {
  roles: string[];
  age_band: string;
  guardian_email: string;
  plans: { plan: string; source: string; starts_at: string; ends_at: string; active: boolean; note: string }[];
  payments: { count: number; total_paise: number };
  orgs: { id: number; name: string; slug: string; role: string }[];
  courses: { own: number; enrolled: number };
  certificates: { id: number; title: string; kind: string; issued_at: string; revoked: boolean }[];
  ai_30d: { calls: number; tokens: number };
  devices: { passkeys: number; extension: number };
};

/** Filter value → label key under admin.users.filters. */
const FILTERS = [["", "all"], ["paying", "paying"], ["staff", "staff"], ["creator", "creator"], ["inactive", "inactive"], ["unverified", "unverified"], ["minor", "minor"]] as const;
const DONE = ["deactivate", "reactivate", "force_logout", "verify_email", "set_creator", "unset_creator"];
const input = "rounded-lg border-2 border-line bg-surface px-2 py-1.5 text-sm";

/** Every account: search, filter, export; open one to see plans, orgs, certificates, AI use and act on it. */
export default function AdminUsers() {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<number | null>(null);
  const qs = query({ q: search, filter, page });
  const { data } = useQuery({
    queryKey: ["admin-users", qs],
    queryFn: () => api<Paged<Row> & { totals: { total: number; active_7d: number } }>(`/api/admin/users/${qs}`),
  });
  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-8">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h1 className="font-display text-3xl font-extrabold">{t("admin.users.title")}</h1>
        {data && <p className="text-sm text-muted">{t("admin.users.totals", { total: data.totals.total, active: data.totals.active_7d })}</p>}
      </div>
      <Card className="space-y-3">
        <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); setSearch(q.trim()); setPage(1); }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("admin.users.searchPh")} aria-label={t("admin.users.search")} className={cn(input, "w-72")} />
          <Button type="submit" variant="outline"><Search className="h-4 w-4" /> {t("admin.common.search")}</Button>
          <select aria-label={t("admin.common.filter")} value={filter} onChange={(e) => { setFilter(e.target.value); setPage(1); }} className={input}>
            {FILTERS.map(([v, k]) => <option key={v} value={v}>{t(`admin.users.filters.${k}`)}</option>)}
          </select>
        </form>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem] text-sm">
            <thead className="text-left text-xs text-muted"><tr><th className="py-1">{t("admin.users.th.email")}</th><th>{t("admin.users.th.name")}</th><th>{t("admin.users.th.joined")}</th><th>{t("admin.users.th.lastSeen")}</th><th>{t("admin.users.th.orgs")}</th><th>{t("admin.users.th.courses")}</th><th>{t("admin.users.th.flags")}</th></tr></thead>
            <tbody>{data?.results.map((u) => (
              <tr key={u.id} className="cursor-pointer border-t border-line hover:bg-surface-2" onClick={() => setOpen(u.id)}>
                <td className="py-1.5 font-medium">{u.email}</td><td>{u.name}</td><td>{date(u.joined)}</td><td>{date(u.last_login)}</td>
                <td className="tabular-nums">{u.orgs}</td><td className="tabular-nums">{u.courses}</td>
                <td className="space-x-1 text-xs">
                  {!u.active && <span className="rounded bg-bad/15 px-1 text-bad">{t("admin.users.flags.deactivated")}</span>}
                  {u.staff && <span className="rounded bg-accent/15 px-1 text-accent">{t("admin.users.flags.staff")}</span>}
                  {u.creator && <span className="rounded bg-surface-2 px-1">{t("admin.users.flags.creator")}</span>}
                  {u.minor && <span className="rounded bg-surface-2 px-1">{t("admin.users.flags.minor")}</span>}
                  {!u.verified && <span className="rounded bg-surface-2 px-1">{t("admin.users.flags.unverified")}</span>}
                </td>
              </tr>
            ))}</tbody>
          </table>
        </div>
        {data && <Pager page={data.page} pages={data.pages} count={data.count} onPage={setPage} csvUrl={`/api/admin/users/${query({ q: search, filter, export: "csv" })}`} csvName="aasan-users.csv" />}
      </Card>
      {open && <UserDrawer id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function UserDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [err, setErr] = useState("");
  const [done, setDone] = useState("");
  const { data: u } = useQuery({ queryKey: ["admin-user", id], queryFn: () => api<DetailOut>(`/api/admin/users/${id}/`) });
  const act = async (action: string, confirm?: string) => {
    if (confirm && !(await confirmDialog(confirm, { danger: true }))) return;
    setErr("");
    setDone("");
    try {
      qc.setQueryData(["admin-user", id], await api<DetailOut>(`/api/admin/users/${id}/action/`, { method: "POST", json: { action } }));
      void qc.invalidateQueries({ queryKey: ["admin-users"] });
      setDone(t(`admin.users.done.${DONE.includes(action) ? action : "default"}`));
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 403 ? t("admin.users.forbidden") : t("admin.common.failed"));
    }
  };
  return (
    <div role="dialog" aria-label={t("admin.users.dialog")} className="fixed inset-y-0 right-0 z-40 w-full max-w-lg overflow-y-auto border-l border-line bg-bg p-5 shadow-2xl">
      <button type="button" aria-label={t("admin.common.close")} onClick={onClose} className="float-right text-muted hover:text-ink"><X className="h-5 w-5" /></button>
      {!u ? <p className="text-muted">{t("admin.common.loading")}</p> : (
        <div className="space-y-4">
          <div>
            <h2 className="font-display text-2xl font-bold">{u.name || u.email}</h2>
            <p className="text-sm text-muted">{t("admin.users.meta", { email: u.email, joined: date(u.joined), seen: date(u.last_login) })}</p>
            {u.roles.length > 0 && <p className="text-sm">{t("admin.users.roles", { roles: u.roles.join(", ") })}</p>}
            {u.minor && <p className="text-sm">{t("admin.users.minorGuardian", { email: u.guardian_email || "—" })}</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            {u.active
              ? <Button variant="outline" onClick={() => void act("deactivate", t("admin.users.deactivateConfirm", { email: u.email }))}>{t("admin.users.deactivate")}</Button>
              : <Button variant="outline" onClick={() => void act("reactivate")}>{t("admin.users.reactivate")}</Button>}
            <Button variant="outline" onClick={() => void act("force_logout", t("admin.users.signOutConfirm", { email: u.email }))}>{t("admin.users.signOut")}</Button>
            {!u.verified && <Button variant="outline" onClick={() => void act("verify_email")}>{t("admin.users.verifyEmail")}</Button>}
            <Button variant="outline" onClick={() => void act(u.creator ? "unset_creator" : "set_creator")}>{u.creator ? t("admin.users.removeCreator") : t("admin.users.makeCreator")}</Button>
          </div>
          {err && <p role="alert" className="text-sm text-bad">{err}</p>}
          {done && <p role="status" className="text-sm text-good">{done}</p>}
          <Section title={t("admin.users.plans")}>
            {u.plans.length ? u.plans.map((p, i) => (
              <p key={i} className="text-sm">{t("admin.users.planLine", { plan: p.plan, source: p.source, from: date(p.starts_at), to: date(p.ends_at) })} {p.active && <span className="text-good">{t("admin.users.activeTag")}</span>}</p>
            )) : <p className="text-sm text-muted">{t("admin.users.freePlan")}</p>}
            <p className="text-sm text-muted">{t("admin.users.payments", { count: u.payments.count, total: rupees(u.payments.total_paise) })}</p>
          </Section>
          <Section title={t("admin.users.orgs")}>
            {u.orgs.length ? u.orgs.map((o) => <p key={o.id} className="text-sm">{o.name} <span className="text-muted">({o.role})</span></p>) : <p className="text-sm text-muted">{t("admin.users.none")}</p>}
          </Section>
          <Section title={t("admin.users.learning")}>
            <p className="text-sm">{t("admin.users.ownCourses", { count: u.courses.own })} · {t("admin.users.enrolled", { count: u.courses.enrolled })}</p>
            {u.certificates.map((c) => <p key={c.id} className={cn("text-sm", c.revoked && "line-through text-muted")}>🎓 {c.title} · {c.kind} · {date(c.issued_at)}</p>)}
          </Section>
          <Section title={t("admin.users.usage")}>
            <p className="text-sm">{t("admin.users.ai", { calls: t("admin.users.calls", { count: u.ai_30d.calls }), tokens: t("admin.users.tokens", { count: u.ai_30d.tokens }) })}</p>
            <p className="text-sm">{t("admin.users.passkeys", { count: u.devices.passkeys })} · {t("admin.users.extDevices", { count: u.devices.extension })}</p>
          </Section>
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-1 border-t border-line pt-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</h3>
      {children}
    </section>
  );
}
