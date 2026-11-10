import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Pager } from "@/components/admin/Pager";
import { TemplateEditor } from "@/components/certificates/TemplateEditor";
import { Button, Card } from "@/components/ui";
import { date, query, type Paged } from "@/lib/admin";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { confirmDialog } from "@/lib/dialog";
import { useMe } from "@/lib/useMe";

interface Row { id: number; code: string; kind: string; title: string; learner: string; email: string; issuer: string; org_id: number | null; issued_at: string; revoked: boolean; hidden: boolean }
interface Stats { total: number; last_30d: number; revoked: number; by_kind: Record<string, number> }
const input = "rounded-lg border-2 border-line bg-surface px-2 py-1.5 text-sm";
const KINDS = ["course", "workshop", "test", "scenario"] as const;

/** Every certificate issued (search, revoke, fix a name) and how they look (templates). */
export default function AdminCertificates() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const canDesign = !!me?.staff_roles?.some((r) => r === "superadmin" || r === "content");
  const [tab, setTab] = useState<"issued" | "design">("issued");
  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-8">
      <h1 className="font-display text-3xl font-extrabold">{t("admin.certs.title")}</h1>
      <div role="tablist" className="flex gap-2">
        {(["issued", ...(canDesign ? ["design"] : [])] as const).map((k) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k as typeof tab)}
            className={cn("rounded-full border-2 px-4 py-1.5 text-sm font-semibold", tab === k ? "border-accent bg-accent text-accent-ink" : "border-line")}>
            {k === "issued" ? t("admin.certs.tabIssued") : t("admin.certs.tabDesign")}
          </button>
        ))}
      </div>
      {tab === "issued" ? <Issued /> : (
        <>
          <p className="text-sm text-muted">{t("admin.certs.designHint")}</p>
          <TemplateEditor base="/api/admin/certificate-templates/" />
        </>
      )}
    </div>
  );
}

function Issued() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const qs = query({ q: search, kind, status, page });
  const { data } = useQuery({ queryKey: ["admin-certs", qs], queryFn: () => api<Paged<Row> & { stats: Stats }>(`/api/admin/certificates/${qs}`) });
  const kindName = (k: string) => ((KINDS as readonly string[]).includes(k) ? t(`admin.certs.kinds.${k}`) : k);
  const act = async (id: number, what: "revoke" | "refresh-name", confirm?: string) => {
    if (confirm && !(await confirmDialog(confirm, { danger: true }))) return;
    await api(`/api/admin/certificates/${id}/${what}/`, { method: "POST" }).catch(() => null);
    void qc.invalidateQueries({ queryKey: ["admin-certs"] });
  };
  return (
    <Card className="space-y-3">
      {data && (
        <p className="text-sm text-muted">
          {t("admin.certs.stats", { total: data.stats.total, last30: data.stats.last_30d, revoked: data.stats.revoked })} ·{" "}
          {Object.entries(data.stats.by_kind).map(([k, n]) => `${n} ${kindName(k)}`).join(", ")}
        </p>
      )}
      <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); setSearch(q.trim()); setPage(1); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("admin.certs.searchPh")} aria-label={t("admin.certs.search")} className={cn(input, "w-72")} />
        <Button type="submit" variant="outline"><Search className="h-4 w-4" /> {t("admin.common.search")}</Button>
        <select aria-label={t("admin.common.kind")} value={kind} onChange={(e) => { setKind(e.target.value); setPage(1); }} className={input}>
          <option value="">{t("admin.common.allKinds")}</option>{KINDS.map((k) => <option key={k} value={k}>{t(`admin.certs.kinds.${k}`)}</option>)}
        </select>
        <select aria-label={t("admin.common.status")} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} className={input}>
          <option value="">{t("admin.certs.anyStatus")}</option><option value="active">{t("admin.certs.active")}</option><option value="revoked">{t("admin.certs.revoked")}</option>
        </select>
      </form>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-sm">
          <thead className="text-left text-xs text-muted"><tr><th className="py-1">{t("admin.certs.th.learner")}</th><th>{t("admin.certs.th.title")}</th><th>{t("admin.certs.th.kind")}</th><th>{t("admin.certs.th.issuer")}</th><th>{t("admin.certs.th.issued")}</th><th>{t("admin.certs.th.id")}</th><th /></tr></thead>
          <tbody>{data?.results.map((c) => (
            <tr key={c.id} className={cn("border-t border-line", c.revoked && "text-muted line-through")}>
              <td className="py-1.5">{c.learner}<span className="block text-xs text-muted no-underline">{c.email}</span></td>
              <td>{c.title}</td><td>{kindName(c.kind)}</td><td>{c.issuer}</td><td>{date(c.issued_at)}</td><td className="font-mono text-xs">{c.code}</td>
              <td className="space-x-2 whitespace-nowrap text-xs">
                {!c.revoked && <button type="button" className="font-semibold text-accent" onClick={() => void act(c.id, "refresh-name")}>{t("admin.certs.updateName")}</button>}
                {!c.revoked && <button type="button" className="font-semibold text-bad" onClick={() => void act(c.id, "revoke", t("admin.certs.revokeConfirm", { learner: c.learner, title: c.title }))}>{t("admin.certs.revoke")}</button>}
              </td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      {data && <Pager page={data.page} pages={data.pages} count={data.count} onPage={setPage} csvUrl={`/api/admin/certificates/${query({ q: search, kind, status, export: "csv" })}`} csvName="aasan-certificates.csv" />}
    </Card>
  );
}
