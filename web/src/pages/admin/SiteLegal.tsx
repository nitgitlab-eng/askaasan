import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ExternalLink, Save } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Button, Card } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { SiteInfo } from "@/lib/legal";

/** Field order; label is admin.site.fields.<k>, and hint (when `hint`) is admin.site.fields.<k>_hint. */
const FIELDS: { k: keyof SiteInfo; hint?: boolean; type?: string; area?: boolean }[] = [
  { k: "brand" },
  { k: "legal_name", hint: true },
  { k: "address", area: true },
  { k: "city" },
  { k: "support_email", type: "email" },
  { k: "phone" },
  { k: "grievance_officer", hint: true },
  { k: "grievance_email", type: "email" },
  { k: "gstin" },
  { k: "state", hint: true },
  { k: "hsn_sac", hint: true },
  { k: "refund_days", type: "number" },
];
const PAGES = [["/privacy", "privacy"], ["/terms", "terms"], ["/refunds", "refunds"], ["/contact", "contact"]] as const;

function Form({ info }: { info: SiteInfo }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [d, setD] = useState(info);
  const [msg, setMsg] = useState("");
  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      const r = await api<SiteInfo>("/api/admin/site/", { method: "PATCH", json: { ...d, refund_days: Number(d.refund_days) } });
      qc.setQueryData(["admin-site"], r);
      qc.setQueryData(["site-info"], r);
      setMsg(t("admin.site.saved"));
    } catch (x) {
      setMsg(x instanceof ApiError ? JSON.stringify(x.data) : t("admin.common.saveFailed"));
    }
  }
  const missing = (["legal_name", "address", "support_email", "grievance_officer", "grievance_email"] as const).filter((k) => !info[k]);
  return (
    <form onSubmit={save} className="space-y-4">
      {missing.length > 0 && (
        <p className="flex items-start gap-2 rounded-xl bg-amber-100 px-3 py-2 text-sm text-amber-900"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {t("admin.site.fillBefore", { fields: missing.map((k) => t(`admin.site.fields.${k}`)).join(", ") })}</p>
      )}
      <Card className="grid gap-3 sm:grid-cols-2">
        {FIELDS.map((f) => (
          <label key={f.k} className={f.area ? "text-sm font-medium sm:col-span-2" : "text-sm font-medium"}>
            {t(`admin.site.fields.${f.k}`)}
            {f.area ? (
              <textarea rows={3} value={String(d[f.k] ?? "")} onChange={(e) => setD({ ...d, [f.k]: e.target.value })} className="mt-1 w-full rounded-xl border-2 border-line bg-surface px-3 py-2" />
            ) : (
              <input type={f.type ?? "text"} min={0} max={30} value={String(d[f.k] ?? "")} onChange={(e) => setD({ ...d, [f.k]: e.target.value })} className="mt-1 w-full rounded-xl border-2 border-line bg-surface px-3 py-2" />
            )}
            {f.hint && <span className="mt-0.5 block text-xs font-normal text-muted">{t(`admin.site.fields.${f.k}_hint`)}</span>}
          </label>
        ))}
        <div className="flex items-center gap-3 sm:col-span-2"><Button type="submit"><Save className="h-4 w-4" /> {t("admin.common.save")}</Button><span className="text-sm text-muted">{msg}</span></div>
      </Card>
    </form>
  );
}

export default function SiteLegal() {
  const { t } = useTranslation();
  const { data } = useQuery({ queryKey: ["admin-site"], queryFn: () => api<SiteInfo>("/api/admin/site/") });
  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("admin.site.title")}</h1>
        <p className="text-muted">{t("admin.site.sub")}</p>
      </header>
      <Card className="text-sm">
        <p className="font-semibold">{t("admin.site.publicPages")}</p>
        <div className="mt-2 flex flex-wrap gap-4">
          {PAGES.map(([to, k]) => (
            <Link key={to} to={to} target="_blank" className="flex items-center gap-1 text-accent underline">{t(`admin.site.pages.${k}`)} <ExternalLink className="h-3.5 w-3.5" /></Link>
          ))}
        </div>
        <p className="mt-3 text-muted">{t("admin.site.legalNote")}</p>
      </Card>
      {data && <Form key={data.terms_version + data.legal_name} info={data} />}
    </div>
  );
}
