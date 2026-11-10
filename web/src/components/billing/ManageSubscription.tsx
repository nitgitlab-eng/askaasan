import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CreditCard, RefreshCcw } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { confirmDialog } from "@/lib/dialog";
import { localeOf } from "@/i18n/languages";
import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { billing, rupees, subNeedsAttention, type SubscriptionState } from "@/lib/billing";
import { cn } from "@/lib/cn";

/** Self-serve auto-renew: status, next charge, masked payment method, cancel at period end, resume (paused only). */
export function ManageSubscription() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["billing-subscription"], queryFn: billing.subscription });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const sub = data?.subscription;
  if (!sub) return null;
  const date = (d: string) => new Date(d).toLocaleDateString(localeOf(i18n.language), { day: "numeric", month: "short", year: "numeric" });

  async function run(fn: () => Promise<SubscriptionState>, okText: string) {
    setBusy(true);
    setMsg(null);
    try {
      qc.setQueryData(["billing-subscription"], await fn());
      void qc.invalidateQueries({ queryKey: ["billing"] });
      setMsg({ ok: true, text: okText });
    } catch (e) {
      const code = e instanceof ApiError ? String(e.data?.code ?? "") : "";
      setMsg({ ok: false, text: code === "cannot_resume" ? t("intgSub.noResume") : t(`intgSub.errors.${code}`, { defaultValue: t("intgSub.errors.generic") }) });
    } finally {
      setBusy(false);
    }
  }
  const warn = subNeedsAttention(sub.status);
  const until = data.access_until;
  return (
    <Card className={cn("space-y-3", warn && "border-2 border-amber-500")}>
      <div className="flex flex-wrap items-center gap-2">
        <RefreshCcw className="h-5 w-5 text-accent" />
        <h2 className="flex-1 font-display text-lg font-bold">{t("intgSub.manage")}</h2>
        {sub.mode === "test" && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">{t("intgSub.test")}</span>}
        <span className={cn("rounded-full px-2.5 py-0.5 text-xs font-bold", sub.status === "active" ? "bg-good/15 text-good" : warn ? "bg-amber-100 text-amber-800" : "bg-surface-2 text-muted")}>
          {t(`intgSub.status.${sub.status}`)}
        </span>
      </div>
      <p className="font-semibold">{sub.plan} · <span className="font-normal text-muted">{t("intgSub.every", { amount: rupees(sub.amount_paise), count: sub.period_days })}</span></p>
      <ul className="space-y-1 text-sm">
        {sub.next_charge_at && <li>{t("intgSub.nextCharge", { amount: rupees(sub.amount_paise), date: date(sub.next_charge_at) })}</li>}
        {sub.cancel_at_period_end && until && <li>{t("intgSub.endsOn", { date: date(until) })}</li>}
        {sub.method && <li className="flex items-center gap-1.5"><CreditCard className="h-4 w-4 text-muted" /> {t("intgSub.method", { method: sub.method })}</li>}
        {sub.grace_until && <li className="flex items-start gap-1.5 text-amber-800 dark:text-amber-200"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {t("intgSub.grace", { date: date(sub.grace_until) })}</li>}
        {sub.status === "halted" && <li className="text-muted">{t("intgSub.haltedHelp")}</li>}
      </ul>
      <div className="flex flex-wrap gap-2">
        {sub.can_resume && <Button loading={busy} onClick={() => void run(billing.subResume, t("intgSub.resumed"))}>{t("intgSub.resume")}</Button>}
        {sub.can_cancel && (
          <Button variant="outline" loading={busy} onClick={async () => { if (await confirmDialog(t("intgSub.cancelConfirm"), { danger: true })) void run(billing.subCancel, t("intgSub.cancelled")); }}>
            {t("intgSub.cancel")}
          </Button>
        )}
      </div>
      {msg && <p role="status" className={cn("text-sm", msg.ok ? "text-good" : "text-bad")}>{msg.text}</p>}
    </Card>
  );
}
