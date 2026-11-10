import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, Undo2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Pager } from "@/components/admin/Pager";
import { Button, Card } from "@/components/ui";
import { date, query, type Paged } from "@/lib/admin";
import { api, ApiError } from "@/lib/api";
import { rupees } from "@/lib/billing";
import { cn } from "@/lib/cn";
import { confirmDialog } from "@/lib/dialog";

interface Order { id: number; email: string; plan: string; amount_paise: number; refunded_paise: number; status: string; mode: string; paid_at: string | null; payment_id: string }
interface RefundRow { id: number; order_id: number; email: string; label: string; amount_paise: number; reason: string; status: "pending" | "processed" | "failed"; error: string; access_ended: boolean; by: string; created_at: string }
const input = "rounded-lg border-2 border-line bg-surface px-2 py-1.5 text-sm";
const STATUS = { pending: "bg-surface-2", processed: "bg-good/15 text-good", failed: "bg-bad/15 text-bad" } as const;
const CODES = ["reason_required", "bad_amount", "order_not_refundable", "payments_not_configured", "gateway_error"];

/** Finance: find a paid order, refund all or part of it through Razorpay, optionally end the access it bought. */
export default function AdminRefunds() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [picked, setPicked] = useState<Order | null>(null);
  const [err, setErr] = useState("");
  const { data: orders } = useQuery({
    queryKey: ["admin-refund-orders", search],
    queryFn: () => api<{ orders: Order[] }>(`/api/admin/payments/orders/${query({ q: search, status: "paid" })}`),
    enabled: !!search,
  });
  const lq = query({ page });
  const { data: refunds } = useQuery({
    queryKey: ["admin-refunds", lq],
    queryFn: () => api<Paged<RefundRow> & { total_paise: number }>(`/api/admin/refunds/${lq}`),
  });

  const submit = async (form: HTMLFormElement) => {
    if (!picked) return;
    const f = new FormData(form);
    const rupeeAmt = String(f.get("amount") || "").trim();
    const left = picked.amount_paise - picked.refunded_paise;
    const amount = rupeeAmt ? Math.round(Number(rupeeAmt) * 100) : left;
    if (!(await confirmDialog(t("admin.refunds.confirm", { amount: rupees(amount), email: picked.email }), { danger: true }))) return;
    setErr("");
    try {
      await api("/api/admin/refunds/", { method: "POST", json: { order_id: picked.id, amount_paise: amount, reason: f.get("reason"), end_access: f.get("end_access") === "on" } });
      setPicked(null);
      void qc.invalidateQueries({ queryKey: ["admin-refunds"] });
      void qc.invalidateQueries({ queryKey: ["admin-refund-orders"] });
    } catch (e) {
      const code = e instanceof ApiError ? String(e.data?.code ?? "") : "";
      setErr(CODES.includes(code) ? t(`admin.refunds.errors.${code}`) : t("admin.common.failed"));
      void qc.invalidateQueries({ queryKey: ["admin-refunds"] });
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-8">
      <h1 className="font-display text-3xl font-extrabold">{t("admin.refunds.title")}</h1>
      <Card className="space-y-3">
        <h2 className="font-display text-xl font-bold">{t("admin.refunds.newRefund")}</h2>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setSearch(q.trim()); setPicked(null); }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("admin.refunds.findPh")} aria-label={t("admin.refunds.find")} className={cn(input, "w-96")} />
          <Button type="submit" variant="outline"><Search className="h-4 w-4" /> {t("admin.refunds.findBtn")}</Button>
        </form>
        {orders && (orders.orders.length ? (
          <ul className="space-y-1">{orders.orders.map((o) => {
            const left = o.amount_paise - o.refunded_paise;
            return (
              <li key={o.id}>
                <button type="button" disabled={left <= 0} onClick={() => setPicked(o)}
                  className={cn("w-full rounded-lg border-2 px-3 py-2 text-left text-sm disabled:opacity-50", picked?.id === o.id ? "border-accent" : "border-line")}>
                  <b>{o.email}</b> · {t("admin.refunds.orderLine", { plan: o.plan, amount: rupees(o.amount_paise), mode: o.mode, date: date(o.paid_at) })}
                  {o.refunded_paise > 0 && <span className="text-muted"> · {t("admin.refunds.alreadyRefunded", { amount: rupees(o.refunded_paise) })}</span>}
                </button>
              </li>
            );
          })}</ul>
        ) : <p className="text-sm text-muted">{t("admin.refunds.noOrders")}</p>)}
        {picked && (
          <form className="flex flex-wrap items-end gap-2 rounded-xl bg-surface-2 p-3" onSubmit={(e) => { e.preventDefault(); void submit(e.currentTarget); }}>
            <label className="flex flex-col text-xs font-medium">{t("admin.refunds.amount", { amount: rupees(picked.amount_paise - picked.refunded_paise) })}
              <input name="amount" type="number" min={1} step="0.01" className={cn(input, "w-36")} />
            </label>
            <label className="flex flex-col text-xs font-medium">{t("admin.refunds.reason")}<input name="reason" required minLength={3} maxLength={200} className={cn(input, "w-64")} /></label>
            <label className="flex items-center gap-2 text-sm"><input name="end_access" type="checkbox" /> {t("admin.refunds.endAccess")}</label>
            <Button type="submit"><Undo2 className="h-4 w-4" /> {t("admin.refunds.refund")}</Button>
          </form>
        )}
        {err && <p role="alert" className="text-sm text-bad">{err}</p>}
      </Card>
      <Card className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-display text-xl font-bold">{t("admin.refunds.history")}</h2>
          {refunds && <span className="text-sm text-muted">{t("admin.refunds.total", { amount: rupees(refunds.total_paise) })}</span>}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem] text-sm">
            <thead className="text-left text-xs text-muted"><tr><th className="py-1">{t("admin.refunds.th.when")}</th><th>{t("admin.refunds.th.buyer")}</th><th>{t("admin.refunds.th.for")}</th><th>{t("admin.refunds.th.amount")}</th><th>{t("admin.refunds.th.reason")}</th><th>{t("admin.refunds.th.by")}</th><th>{t("admin.refunds.th.status")}</th></tr></thead>
            <tbody>{refunds?.results.map((r) => (
              <tr key={r.id} className="border-t border-line">
                <td className="py-1.5">{date(r.created_at)}</td><td>{r.email}</td><td>{r.label}</td><td className="tabular-nums">{rupees(r.amount_paise)}</td>
                <td>{r.reason}{r.access_ended && <span className="text-muted"> · {t("admin.refunds.accessEnded")}</span>}</td><td className="text-muted">{r.by}</td>
                <td><span title={r.error} className={cn("rounded px-1.5 py-0.5 text-xs font-semibold", STATUS[r.status])}>{t(`admin.refunds.status.${r.status}`)}</span></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
        {refunds && <Pager page={refunds.page} pages={refunds.pages} count={refunds.count} onPage={setPage} csvUrl="/api/admin/refunds/?export=csv" csvName="aasan-refunds.csv" />}
      </Card>
    </div>
  );
}
