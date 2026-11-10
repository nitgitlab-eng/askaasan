import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, UserPlus } from "lucide-react";
import { Fragment, useState } from "react";
import { useTranslation } from "react-i18next";

import { Pager } from "@/components/admin/Pager";
import { Button, Card } from "@/components/ui";
import { query, type Paged, type StaffRole } from "@/lib/admin";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";

interface Staffer { id: number; email: string; name: string; roles: StaffRole[]; superuser: boolean; last_login: string | null }
interface Entry { id: number; at: string; actor: string; method: string; path: string; section: string; target: string; data: unknown; status: number; ip: string | null }
/** Role codes are shown as-is (they match the server and the audit log); what each allows is admin.staff.roles.<role>. */
const ROLES: StaffRole[] = ["superadmin", "support", "finance", "content"];
const CODES = ["user_not_found", "cannot_demote_self", "last_superadmin", "superuser_fixed"];
const input = "rounded-lg border-2 border-line bg-surface px-2 py-1.5 text-sm";

/** Superadmin: who can use the console and in which role, and every change made through it. */
export default function AdminStaff() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: staff } = useQuery({ queryKey: ["admin-staff"], queryFn: () => api<Staffer[]>("/api/admin/staff/") });
  const [err, setErr] = useState("");
  const save = async (email: string, roles: StaffRole[]) => {
    setErr("");
    try {
      await api("/api/admin/staff/", { method: "POST", json: { email, roles } });
      void qc.invalidateQueries({ queryKey: ["admin-staff"] });
    } catch (e) {
      const code = e instanceof ApiError ? String(e.data?.code ?? "") : "";
      setErr(CODES.includes(code) ? t(`admin.staff.errors.${code}`) : t("admin.common.failed"));
    }
  };
  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-8">
      <h1 className="font-display text-3xl font-extrabold">{t("admin.staff.title")}</h1>
      <Card className="space-y-3">
        <h2 className="font-display text-xl font-bold">{t("admin.staff.rolesTitle")}</h2>
        <ul className="grid gap-1 text-sm sm:grid-cols-2">{ROLES.map((r) => <li key={r}><b>{r}</b> — <span className="text-muted">{t(`admin.staff.roles.${r}`)}</span></li>)}</ul>
        <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          void save(String(f.get("email") ?? "").trim(), f.getAll("roles") as StaffRole[]);
          e.currentTarget.reset();
        }}>
          <label className="flex flex-col text-xs font-medium">{t("admin.common.email")}<input name="email" type="email" required className={cn(input, "w-64")} /></label>
          <fieldset className="flex gap-3 text-sm">{ROLES.map((r) => <label key={r} className="flex items-center gap-1"><input type="checkbox" name="roles" value={r} /> {r}</label>)}</fieldset>
          <Button type="submit"><UserPlus className="h-4 w-4" /> {t("admin.staff.add")}</Button>
        </form>
        {err && <p role="alert" className="text-sm text-bad">{err}</p>}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted"><tr><th className="py-1">{t("admin.common.email")}</th>{ROLES.map((r) => <th key={r}>{r}</th>)}<th /></tr></thead>
            <tbody>{staff?.map((s) => (
              <tr key={s.id} className="border-t border-line">
                <td className="py-1.5 font-medium">{s.email}{s.superuser && <span className="ml-1 text-xs text-muted">{t("admin.staff.superuser")}</span>}</td>
                {ROLES.map((r) => (
                  <td key={r}>
                    <input type="checkbox" aria-label={t("admin.staff.roleFor", { role: r, email: s.email })} disabled={s.superuser} checked={s.roles.includes(r)}
                      onChange={(e) => void save(s.email, e.target.checked ? [...s.roles, r] : s.roles.filter((x) => x !== r))} />
                  </td>
                ))}
                <td>{!s.superuser && <button type="button" className="text-xs font-semibold text-bad" onClick={() => void save(s.email, [])}>{t("admin.staff.remove")}</button>}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </Card>
      <AuditLog />
    </div>
  );
}

function AuditLog() {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<number | null>(null);
  const qs = query({ q: search, page });
  const { data } = useQuery({ queryKey: ["admin-audit", qs], queryFn: () => api<Paged<Entry>>(`/api/admin/audit/${qs}`) });
  return (
    <Card className="space-y-3">
      <h2 className="font-display text-xl font-bold">{t("admin.staff.audit")}</h2>
      <p className="text-sm text-muted">{t("admin.staff.auditHint")}</p>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setSearch(q.trim()); setPage(1); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("admin.staff.searchPh")} aria-label={t("admin.staff.search")} className={cn(input, "w-72")} />
        <Button type="submit" variant="outline"><Search className="h-4 w-4" /> {t("admin.common.search")}</Button>
      </form>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-sm">
          <thead className="text-left text-xs text-muted"><tr><th className="py-1">{t("admin.staff.th.when")}</th><th>{t("admin.staff.th.who")}</th><th>{t("admin.staff.th.action")}</th><th>{t("admin.staff.th.section")}</th><th>{t("admin.staff.th.target")}</th><th>{t("admin.staff.th.result")}</th></tr></thead>
          <tbody>{data?.results.map((a) => (
            <Fragment key={a.id}>
              <tr className="cursor-pointer border-t border-line hover:bg-surface-2" onClick={() => setOpen(open === a.id ? null : a.id)}>
                <td className="py-1.5 whitespace-nowrap">{new Date(a.at).toLocaleString("en-IN")}</td><td>{a.actor}</td>
                <td className="font-mono text-xs">{a.method} {a.path}</td><td>{a.section}</td><td className="font-mono text-xs">{a.target}</td>
                <td className={cn("tabular-nums", a.status >= 400 && "text-bad")}>{a.status}</td>
              </tr>
              {open === a.id && <tr><td colSpan={6}><pre className="overflow-x-auto rounded-lg bg-surface-2 p-2 text-xs">{JSON.stringify(a.data, null, 2)}{a.ip ? `\n${t("admin.staff.from", { ip: a.ip })}` : ""}</pre></td></tr>}
            </Fragment>
          ))}</tbody>
        </table>
      </div>
      {data && <Pager page={data.page} pages={data.pages} count={data.count} onPage={setPage} csvUrl={`/api/admin/audit/${query({ q: search, export: "csv" })}`} csvName="aasan-audit.csv" />}
    </Card>
  );
}
