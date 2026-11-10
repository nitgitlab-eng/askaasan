import { Gift } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { giftPlan, rupees, type CheckoutOpts, type PlanInfo } from "@/lib/billing";

const MESSAGE_MAX = 300;
const ERRORS = ["gift_self", "bad_gift_email", "gift_org", "gift_pay_once"];

/** "Gift this plan": recipient email + a short message, then Razorpay Checkout (pay once). */
export function GiftDialog({ plan, opts, onClose, onDone }: {
  plan: PlanInfo;
  opts?: Omit<CheckoutOpts, "gift" | "org" | "seats">;
  onClose: () => void;
  onDone: (text: string) => void;
}) {
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#f97316";
      await giftPlan(plan.code, accent, { recipient_email: email.trim(), message: message.trim() || undefined }, opts);
      onDone(t("billing.gift.sent", { plan: plan.name, email: email.trim() }));
    } catch (e) {
      const code = e instanceof ApiError ? String(e.data?.code ?? "") : (e as Error).message;
      if (code === "dismissed") setErr("");
      else if (code === "payment_pending") onDone(t("billing.gift.pending"));
      else setErr(ERRORS.includes(code) ? t(`billing.gift.errors.${code}`) : t(`billing.errors.${code}`, { defaultValue: t("billing.errors.generic") }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[110] flex items-end justify-center bg-black/40 p-4 sm:items-center" onClick={() => !busy && onClose()}>
      <form role="dialog" aria-modal="true" aria-labelledby="gift-title" onSubmit={submit} onClick={(e) => e.stopPropagation()} className="w-full max-w-md space-y-4 rounded-3xl bg-surface p-6 shadow-xl">
        <h2 id="gift-title" className="flex items-center gap-2 font-display text-xl font-bold"><Gift className="h-5 w-5 text-accent" /> {t("billing.gift.title", { plan: plan.name })}</h2>
        <p className="text-sm text-muted">{t("billing.gift.intro", { price: rupees(plan.price_paise), count: plan.period_days })}</p>
        <label className="block text-sm font-medium">{t("billing.gift.email")}
          <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} maxLength={254} autoComplete="off" className="mt-1 w-full rounded-xl border-2 border-line bg-surface px-3 py-2" />
        </label>
        <label className="block text-sm font-medium">{t("billing.gift.message")}
          <textarea value={message} onChange={(e) => setMessage(e.target.value.slice(0, MESSAGE_MAX))} rows={3} className="mt-1 w-full rounded-xl border-2 border-line bg-surface px-3 py-2" />
          <span className="block text-right text-xs text-muted">{message.length}/{MESSAGE_MAX}</span>
        </label>
        <p className="text-xs text-muted">{t("billing.gift.fine")}</p>
        {err && <p role="alert" className="text-sm text-bad">{err}</p>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" disabled={busy} onClick={onClose}>{t("dialog.cancel")}</Button>
          <Button type="submit" loading={busy} disabled={!email.trim()}>{t("billing.gift.pay", { price: rupees(plan.price_paise) })}</Button>
        </div>
      </form>
    </div>
  );
}
