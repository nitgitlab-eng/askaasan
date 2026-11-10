import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card } from "@/components/ui";
import { date } from "@/lib/admin";
import { api, ApiError } from "@/lib/api";
import { rupees } from "@/lib/billing";
import { cn } from "@/lib/cn";
import { downloadFile } from "@/lib/download";

interface Promo { id: number; code: string; kind: "percent" | "fixed"; value: number; plans: string[]; expires_at: string | null; max_uses: number; uses: number; per_user: number; max_seats: number; active: boolean; note: string; purpose?: "" | "winback_lapse" }
interface Code { code: string; plan: string; days: number; batch: string; expires_at: string | null; redeemed: boolean; redeemed_by: string | null }
interface Inv { number: string; issued_at: string; buyer: string; total_paise: number; taxable_paise: number; gst_paise: number; mode: string }
const input = "rounded-lg border-2 border-line bg-surface px-2 py-1.5 text-sm";

/** Super admin: promo codes, prepaid redeem codes (batches, optionally for a school), GST invoices. */
export default function AdminCodes() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: promos } = useQuery({ queryKey: ["admin-promos"], queryFn: () => api<Promo[]>("/api/admin/promos/") });
  const { data: codes } = useQuery({ queryKey: ["admin-codes"], queryFn: () => api<Code[]>("/api/admin/redeem-codes/") });
  const { data: invs } = useQuery({ queryKey: ["admin-invoices"], queryFn: () => api<Inv[]>("/api/admin/invoices/") });
  const { data: plans } = useQuery({ queryKey: ["admin-plans"], queryFn: () => api<{ code: string; name: string; price_paise: number }[]>("/api/admin/plans/") });
  const [err, setErr] = useState("");
  const [batchMsg, setBatchMsg] = useState("");
  const batches = [...new Set((codes ?? []).map((c) => c.batch))];
  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-8">
      <h1 className="font-display text-3xl font-extrabold">{t("admin.codes.title")}</h1>
      <Card className="space-y-3">
        <h2 className="font-display text-xl font-bold">{t("admin.codes.promos")}</h2>
        <form className="flex flex-wrap items-end gap-2" onSubmit={async (e) => {
          e.preventDefault();
          const form = e.currentTarget;
          setErr("");
          const f = new FormData(form);
          try {
            await api("/api/admin/promos/", { method: "POST", json: {
              code: f.get("code"), kind: f.get("kind"), value: f.get("kind") === "fixed" ? Math.round(Number(f.get("value")) * 100) : Number(f.get("value")),
              plans: f.getAll("plans"), max_uses: Number(f.get("max_uses") || 0), per_user: Number(f.get("per_user") || 1), max_seats: Number(f.get("max_seats") || 0),
              expires_at: f.get("expires") ? new Date(String(f.get("expires"))).toISOString() : null, note: f.get("note"), purpose: f.get("purpose") || "" } });
            form.reset();
            void qc.invalidateQueries({ queryKey: ["admin-promos"] });
          } catch (x) { setErr(x instanceof ApiError ? JSON.stringify(x.data) : t("admin.codes.failed")); }
        }}>
          <label className="flex flex-col text-xs font-medium">{t("admin.codes.code")}<input name="code" required className={cn(input, "w-32 uppercase")} placeholder={t("admin.codes.codePh")} /></label>
          <label className="flex flex-col text-xs font-medium">{t("admin.codes.type")}<select name="kind" className={input}><option value="percent">{t("admin.codes.percentOff")}</option><option value="fixed">{t("admin.codes.fixedOff")}</option></select></label>
          <label className="flex flex-col text-xs font-medium">{t("admin.codes.value")}<input name="value" type="number" min={1} required className={cn(input, "w-20")} /></label>
          <label className="flex flex-col text-xs font-medium">{t("admin.codes.plans")}<select name="plans" multiple className={cn(input, "h-16")}>{plans?.filter((p) => p.price_paise > 0).map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}</select></label>
          <label className="flex flex-col text-xs font-medium">{t("admin.codes.maxUses")}<input name="max_uses" type="number" min={0} defaultValue={0} className={cn(input, "w-24")} /></label>
          <label className="flex flex-col text-xs font-medium">{t("admin.codes.perUser")}<input name="per_user" type="number" min={0} defaultValue={1} className={cn(input, "w-20")} /></label>
          <label className="flex flex-col text-xs font-medium" title={t("admin.codes.seatsHint")}>{t("admin.codes.seats")}<input name="max_seats" type="number" min={0} defaultValue={0} className={cn(input, "w-24")} /></label>
          <label className="flex flex-col text-xs font-medium">{t("admin.codes.expires")}<input name="expires" type="date" className={input} /></label>
          <label className="flex flex-col text-xs font-medium">{t("admin.codes.note")}<input name="note" maxLength={160} className={input} /></label>
          <label className="flex flex-col text-xs font-medium" title={t("admin.codes.purposeHint")}>{t("admin.codes.purpose")}<select name="purpose" className={input}><option value="">{t("admin.codes.purposeAny")}</option><option value="winback_lapse">{t("admin.codes.purposeWinback")}</option></select></label>
          <Button type="submit"><Plus className="h-4 w-4" /> {t("admin.codes.add")}</Button>
        </form>
        {err && <p role="alert" className="text-sm text-bad">{err}</p>}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem] text-sm">
            <thead className="text-left text-xs text-muted"><tr><th className="py-1">{t("admin.codes.th.code")}</th><th>{t("admin.codes.th.discount")}</th><th>{t("admin.codes.th.plans")}</th><th>{t("admin.codes.th.used")}</th><th>{t("admin.codes.th.expires")}</th><th>{t("admin.codes.th.purpose")}</th><th>{t("admin.codes.th.active")}</th></tr></thead>
            <tbody>{promos?.map((p) => (
              <tr key={p.id} className="border-t border-line">
                <td className="py-1.5 font-mono font-bold">{p.code}</td><td>{p.kind === "percent" ? `${p.value}%` : rupees(p.value)}</td><td>{p.plans.join(", ") || t("admin.codes.allPlans")}</td>
                <td className="tabular-nums">{p.uses}{p.max_uses ? ` / ${p.max_uses}` : ""}</td><td>{date(p.expires_at)}</td>
                <td><select value={p.purpose ?? ""} aria-label={t("admin.codes.purposeFor", { code: p.code })} title={t("admin.codes.purposeHint")} className="rounded-lg border border-line bg-surface px-1 py-0.5 text-xs" onChange={async (e) => { await api(`/api/admin/promos/${p.id}/`, { method: "PATCH", json: { purpose: e.target.value } }); void qc.invalidateQueries({ queryKey: ["admin-promos"] }); }}><option value="">{t("admin.codes.purposeAny")}</option><option value="winback_lapse">{t("admin.codes.purposeWinback")}</option></select></td>
                <td><input type="checkbox" checked={p.active} aria-label={t("admin.codes.activeFor", { code: p.code })} onChange={async () => { await api(`/api/admin/promos/${p.id}/`, { method: "PATCH", json: { active: !p.active } }); void qc.invalidateQueries({ queryKey: ["admin-promos"] }); }} /></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </Card>

      <Card className="space-y-3">
        <h2 className="font-display text-xl font-bold">{t("admin.codes.redeemTitle")}</h2>
        <p className="text-sm text-muted">{t("admin.codes.redeemHint")}</p>
        <form className="flex flex-wrap items-end gap-2" onSubmit={async (e) => {
          e.preventDefault();
          const form = e.currentTarget;
          const f = new FormData(form);
          try {
            const r = await api<{ created: number }>("/api/admin/redeem-codes/", { method: "POST", json: { plan: f.get("plan"), days: Number(f.get("days")), count: Number(f.get("count")), batch: f.get("batch"), org: f.get("org") || "" } });
            setBatchMsg(t("admin.codes.created", { count: r.created }));
            void qc.invalidateQueries({ queryKey: ["admin-codes"] });
          } catch (x) { setBatchMsg(x instanceof ApiError ? JSON.stringify(x.data) : t("admin.codes.failed")); }
        }}>
          <label className="flex flex-col text-xs font-medium">{t("admin.codes.plan")}<select name="plan" className={input}>{plans?.filter((p) => p.price_paise > 0).map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}</select></label>
          <label className="flex flex-col text-xs font-medium">{t("admin.codes.days")}<input name="days" type="number" min={1} max={730} defaultValue={90} className={cn(input, "w-20")} /></label>
          <label className="flex flex-col text-xs font-medium">{t("admin.codes.howMany")}<input name="count" type="number" min={1} max={1000} defaultValue={50} className={cn(input, "w-20")} /></label>
          <label className="flex flex-col text-xs font-medium">{t("admin.codes.batch")}<input name="batch" required maxLength={80} className={input} placeholder={t("admin.codes.batchPh")} /></label>
          <label className="flex flex-col text-xs font-medium">{t("admin.codes.orgSlug")}<input name="org" className={input} /></label>
          <Button type="submit"><Plus className="h-4 w-4" /> {t("admin.codes.generate")}</Button>
        </form>
        {batchMsg && <p role="status" className="text-sm">{batchMsg}</p>}
        {batches.map((b) => {
          const rows = (codes ?? []).filter((c) => c.batch === b);
          return (
            <div key={b} className="flex items-center gap-3 text-sm">
              <b>{b}</b><span className="text-muted">{t("admin.codes.redeemed", { redeemed: rows.filter((r) => r.redeemed).length, total: rows.length })} · {rows[0]?.plan} · {t("admin.codes.daysN", { count: rows[0]?.days ?? 0 })}</span>
              <button className="flex items-center gap-1 font-semibold text-accent" onClick={() => void downloadFile(`/api/admin/redeem-codes/?batch=${encodeURIComponent(b)}&export=csv`, "codes.csv")}><Download className="h-4 w-4" /> {t("admin.codes.csv")}</button>
            </div>
          );
        })}
      </Card>

      <Card className="space-y-2">
        <h2 className="font-display text-xl font-bold">{t("admin.codes.invoices")}</h2>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem] text-sm">
            <thead className="text-left text-xs text-muted"><tr><th className="py-1">{t("admin.codes.inv.number")}</th><th>{t("admin.codes.inv.date")}</th><th>{t("admin.codes.inv.buyer")}</th><th>{t("admin.codes.inv.taxable")}</th><th>{t("admin.codes.inv.gst")}</th><th>{t("admin.codes.inv.total")}</th><th /></tr></thead>
            <tbody>{invs?.map((i) => (
              <tr key={i.number} className="border-t border-line">
                <td className="py-1.5 font-mono">{i.number}{i.mode === "test" && <span className="ml-1 text-xs text-amber-700">{t("admin.codes.test")}</span>}</td><td>{date(i.issued_at)}</td><td>{i.buyer}</td>
                <td className="tabular-nums">{rupees(i.taxable_paise)}</td><td className="tabular-nums">{rupees(i.gst_paise)}</td><td className="tabular-nums">{rupees(i.total_paise)}</td>
                <td><button className="text-accent" onClick={() => void downloadFile(`/api/billing/invoices/${i.number.replace(/\//g, "_")}.pdf`, "invoice.pdf")} aria-label={t("admin.codes.download", { number: i.number })}><Download className="h-4 w-4" /></button></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
        {!invs?.length && <p className="text-sm text-muted">{t("admin.codes.noInvoices")}</p>}
      </Card>
    </div>
  );
}
