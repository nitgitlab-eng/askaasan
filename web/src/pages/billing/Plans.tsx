import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Crown, FlaskConical, Gift, Receipt, Users } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";
import type { TFunction } from "i18next";

import { localeOf } from "@/i18n/languages";
import { LegalLinks } from "@/components/LegalLinks";
import { GiftDialog } from "@/components/billing/GiftDialog";
import { ManageFamily } from "@/components/billing/ManageFamily";
import { ManageSubscription } from "@/components/billing/ManageSubscription";
import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { billing, LIMIT_KEYS, payForPlan, renewInterval, rupees, subscribeToPlan, type LimitKey, type PlanInfo } from "@/lib/billing";
import { cn } from "@/lib/cn";
import { downloadFile } from "@/lib/download";
import { mascot } from "@/mascot/store";

const INDIAN_STATES = ["Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chandigarh", "Chhattisgarh",
  "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand", "Karnataka",
  "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab",
  "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal"];

function limitText(t: TFunction, key: LimitKey, v: number | null | undefined) {
  return v === null || v === undefined ? t(`billing.limits.${key}_unlimited`) : t(`billing.limits.${key}`, { n: v, count: v });
}

function Meter({ label, used, max }: { label: string; used: number; max: number | null }) {
  const { t } = useTranslation();
  const pct = max ? Math.min(1, used / max) : 0;
  return (
    <div>
      <div className="flex justify-between text-sm"><span>{label}</span><span className="tabular-nums text-muted">{max === null ? t("billing.unlimited") : `${used} / ${max}`}</span></div>
      <div className="mt-1 h-2 overflow-hidden rounded-full bg-surface-2">
        <div className={cn("h-full rounded-full", pct >= 1 ? "bg-bad" : "bg-accent")} style={{ width: `${max === null ? 0 : pct * 100}%` }} />
      </div>
    </div>
  );
}

export default function PlansPage() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["billing"], queryFn: billing.overview });
  const { data: hist } = useQuery({ queryKey: ["billing-history"], queryFn: billing.history });
  const { data: subState } = useQuery({ queryKey: ["billing-subscription"], queryFn: billing.subscription });
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [promo, setPromo] = useState("");
  const [promoState, setPromoState] = useState<{ code: string; ok: boolean; note: string } | null>(null);
  const [quotes, setQuotes] = useState<Record<string, number>>({});
  const [gst, setGst] = useState({ open: false, name: "", gstin: "", state: "" });
  // A gift email links to /plans?code=XXXX-XXXX-XXXX: the code is filled in, the learner presses Redeem.
  const [params] = useSearchParams();
  const [redeemCode, setRedeemCode] = useState(() => (params.get("code") ?? "").toUpperCase().replace(/[^A-Z0-9-]/g, "").slice(0, 20));
  const [gifting, setGifting] = useState<PlanInfo | null>(null);
  if (!data) return <p className="p-8 text-muted">{t("common.loading")}</p>;
  const date = (d: string) => new Date(d).toLocaleDateString(localeOf(i18n.language), { day: "numeric", month: "short", year: "numeric" });

  async function buy(code: string) {
    setBusy(code);
    setMsg(null);
    try {
      const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#f97316";
      const r = await payForPlan(code, accent, {
        promo: promoState?.ok ? promoState.code : undefined,
        ...(gst.open ? { buyer_name: gst.name || undefined, buyer_gstin: gst.gstin || undefined, buyer_state: gst.state || undefined } : {}),
      });
      mascot.react("celebrate");
      setMsg({ ok: true, text: r.ends_at ? t("billing.success", { plan: r.plan, date: date(r.ends_at) }) : t("billing.freeSuccess", { plan: r.plan }) });
      void qc.invalidateQueries({ queryKey: ["billing"] });
      void qc.invalidateQueries({ queryKey: ["billing-history"] });
    } catch (e) {
      const code = e instanceof ApiError ? (e.data?.code as string) : (e as Error).message;
      if (code === "payment_pending") {
        // Paid, but the server is still confirming with Razorpay: say so, and look again shortly.
        setMsg({ ok: true, text: t("billing.errors.payment_pending") });
        setTimeout(() => void qc.invalidateQueries({ queryKey: ["billing"] }), 15_000);
      } else if (code !== "dismissed") setMsg({ ok: false, text: t(`billing.errors.${code}`, { defaultValue: t("billing.errors.generic") }) });
    } finally {
      setBusy(null);
    }
  }

  async function buyAuto(code: string) {
    setBusy(`auto:${code}`);
    setMsg(null);
    try {
      const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#f97316";
      const r = await subscribeToPlan(code, accent, gst.open ? { buyer_name: gst.name || undefined, buyer_gstin: gst.gstin || undefined, buyer_state: gst.state || undefined } : {});
      mascot.react("celebrate");
      setMsg({ ok: true, text: r.subscription?.status === "active" ? t("intgSub.started", { plan: r.plan }) : t("intgSub.startedPending") });
      qc.setQueryData(["billing-subscription"], r);
      void qc.invalidateQueries({ queryKey: ["billing"] });
      void qc.invalidateQueries({ queryKey: ["billing-history"] });
    } catch (e) {
      const code = e instanceof ApiError ? (e.data?.code as string) : (e as Error).message;
      if (code !== "dismissed") setMsg({ ok: false, text: t(`intgSub.errors.${code}`, { defaultValue: t(`billing.errors.${code}`, { defaultValue: t("billing.errors.generic") }) }) });
    } finally {
      setBusy(null);
    }
  }
  const liveSub = !!subState?.subscription && !["cancelled", "completed", "expired"].includes(subState.subscription.status);
  const autoLabel = (days: number) => {
    const iv = renewInterval(days);
    return iv === "month" ? t("intgSub.autoMonth") : iv === "year" ? t("intgSub.autoYear") : t("intgSub.autoDays", { count: days });
  };

  const paid = data.plans.filter((p) => p.price_paise > 0);
  async function applyPromo() {
    const code = promo.trim().toUpperCase();
    setPromoState(null);
    setQuotes({});
    if (!code) return;
    const out: Record<string, number> = {};
    let ok = false, note = "", lastErr = "";
    for (const p of paid) {
      try {
        const q = await billing.quote(p.code, { promo: code });
        out[p.code] = q.total_paise;
        ok = true;
        note = q.promo_note;
      } catch (e) {
        lastErr = e instanceof ApiError ? String(e.data?.code) : "promo_invalid";
      }
    }
    setQuotes(out);
    setPromoState({ code, ok, note: ok ? note : t(`billing.promoErr.${lastErr}`, { defaultValue: t("billing.promoErr.promo_invalid") }) });
  }
  async function doRedeem() {
    setMsg(null);
    try {
      const r = await billing.redeem(redeemCode);
      mascot.react("celebrate");
      setMsg({ ok: true, text: t("billing.redeemed", { plan: r.plan, date: date(r.ends_at) }) });
      setRedeemCode("");
      void qc.invalidateQueries({ queryKey: ["billing"] });
    } catch (e) {
      const code = e instanceof ApiError ? String(e.data?.code) : "code_invalid";
      setMsg({ ok: false, text: t(`billing.redeemErr.${code}`, { defaultValue: t("billing.redeemErr.code_invalid") }) });
    }
  }
  const free = data.plans.find((p) => p.code === "free");
  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("billing.title")}</h1>
        <p className="text-muted">{t("billing.sub")}</p>
      </header>

      {data.checkout.mode === "test" && (
        <div role="note" className="flex items-start gap-3 rounded-2xl border-2 border-dashed border-amber-500 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          <FlaskConical className="mt-0.5 h-5 w-5 shrink-0" />
          <p>{t("billing.testMode")}</p>
        </div>
      )}

      <Card className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <Crown className="h-6 w-6 text-accent" />
          <div className="flex-1">
            <p className="text-sm text-muted">{t("billing.current")}</p>
            <p className="font-display text-xl font-bold">{data.plan.name}</p>
          </div>
          {data.paid_until && <p className="text-sm text-muted">{t("billing.until", { date: date(data.paid_until) })}</p>}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          {LIMIT_KEYS.filter((k) => data.usage[k]).map((k) => <Meter key={k} label={t(`billing.meter.${k}`)} used={data.usage[k].used} max={data.usage[k].max} />)}
        </div>
      </Card>

      <ManageSubscription />
      <ManageFamily />

      {msg && <p role="status" className={cn("rounded-xl px-4 py-3 font-medium", msg.ok ? "bg-good/15 text-good" : "bg-bad/15 text-bad")}>{msg.text}</p>}

      <Card className="space-y-3">
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col text-sm font-medium">{t("billing.promo")}
            <input value={promo} onChange={(e) => setPromo(e.target.value.toUpperCase())} maxLength={32} className="w-44 rounded-xl border-2 border-line bg-surface px-3 py-2 uppercase" /></label>
          <Button variant="outline" disabled={!promo.trim()} onClick={() => void applyPromo()}>{t("billing.apply")}</Button>
          {promoState && <span role="status" className={cn("text-sm", promoState.ok ? "text-good" : "text-bad")}>{promoState.ok ? `✓ ${t("billing.promoOk")}${promoState.note ? ` — ${promoState.note}` : ""}` : promoState.note}</span>}
        </div>
        <button className="text-sm font-semibold text-accent" aria-expanded={gst.open} onClick={() => setGst({ ...gst, open: !gst.open })}>{t("billing.gstToggle")}</button>
        {gst.open && (
          <div className="flex flex-wrap gap-2">
            <input value={gst.name} onChange={(e) => setGst({ ...gst, name: e.target.value })} maxLength={160} placeholder={t("billing.gstName")} aria-label={t("billing.gstName")} className="rounded-xl border-2 border-line bg-surface px-3 py-2 text-sm" />
            <input value={gst.gstin} onChange={(e) => setGst({ ...gst, gstin: e.target.value.toUpperCase() })} maxLength={15} placeholder="GSTIN" aria-label="GSTIN" className="w-44 rounded-xl border-2 border-line bg-surface px-3 py-2 text-sm uppercase" />
            <select value={gst.state} onChange={(e) => setGst({ ...gst, state: e.target.value })} aria-label={t("billing.gstState")} className="rounded-xl border-2 border-line bg-surface px-3 py-2 text-sm">
              <option value="">{t("billing.gstState")}</option>{INDIAN_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <p className="w-full text-xs text-muted">{t("billing.gstHint")}</p>
          </div>
        )}
        <div className="flex flex-wrap items-end gap-2 border-t border-line pt-3">
          <label className="flex flex-col text-sm font-medium">{t("billing.redeemLabel")}
            <input value={redeemCode} onChange={(e) => setRedeemCode(e.target.value.toUpperCase())} maxLength={20} placeholder="XXXX-XXXX-XXXX" className="w-52 rounded-xl border-2 border-line bg-surface px-3 py-2 font-mono uppercase" /></label>
          <Button variant="outline" disabled={redeemCode.replace(/-/g, "").length < 12} onClick={() => void doRedeem()}>{t("billing.redeem")}</Button>
        </div>
      </Card>

      <div className="grid gap-4 md:grid-cols-3">
        {[free, ...paid].filter(Boolean).map((p) => {
          const mine = data.plan.code === p!.code;
          return (
            <Card key={p!.code} className={cn("flex flex-col gap-3", p!.badge && "border-2 border-accent")}>
              <div className="flex items-start justify-between gap-2">
                <p className="font-display text-lg font-bold">{p!.name}</p>
                {p!.badge && <span className="rounded-full bg-accent px-2.5 py-0.5 text-xs font-bold text-accent-ink">{p!.badge}</span>}
              </div>
              <p className="font-display text-3xl font-extrabold">
                {p!.price_paise > 0 && quotes[p!.code] !== undefined && quotes[p!.code] !== p!.price_paise && <s className="mr-2 text-lg font-normal text-muted">{rupees(p!.price_paise)}</s>}
                {p!.price_paise ? rupees(quotes[p!.code] ?? p!.price_paise) : t("billing.free")}
                {p!.price_paise > 0 && <span className="text-base font-medium text-muted"> / {t("billing.days", { count: p!.period_days })}</span>}
              </p>
              {p!.description && <p className="text-sm text-muted">{p!.description}</p>}
              {p!.family && !!p!.max_members && <p className="flex items-center gap-1.5 text-sm font-semibold text-accent"><Users className="h-4 w-4" /> {t("billing.family.cardLine", { count: p!.max_members })}</p>}
              <ul className="flex-1 space-y-1.5 text-sm">
                {LIMIT_KEYS.map((k) => <li key={k} className="flex gap-2"><Check className="h-4 w-4 shrink-0 text-good" /> {limitText(t, k, p!.limits[k])}</li>)}
              </ul>
              {p!.price_paise > 0 && p!.auto_renew && !liveSub && data.checkout.available ? (
                <div className="space-y-2">
                  <Button className="w-full" loading={busy === `auto:${p!.code}`} disabled={!!busy} onClick={() => buyAuto(p!.code)}>{autoLabel(p!.period_days)}</Button>
                  <Button variant="outline" className="w-full" loading={busy === p!.code} disabled={!!busy} onClick={() => buy(p!.code)}>{t("intgSub.payOnce")}</Button>
                  <p className="text-xs text-muted">{t("intgSub.autoHint")}</p>
                </div>
              ) : p!.price_paise > 0 ? (
                <Button loading={busy === p!.code} disabled={!data.checkout.available || !!busy} onClick={() => buy(p!.code)}>
                  {data.paid_until ? t("billing.extend") : t("billing.upgrade")}
                </Button>
              ) : (
                <p className="text-center text-sm font-semibold text-muted">{mine ? t("billing.yourPlan") : " "}</p>
              )}
              {p!.price_paise > 0 && data.checkout.available && (
                <button type="button" className="flex items-center justify-center gap-1.5 text-sm font-semibold text-accent disabled:opacity-50" disabled={!!busy} onClick={() => setGifting(p!)}>
                  <Gift className="h-4 w-4" /> {t("billing.gift.cta")}
                </button>
              )}
            </Card>
          );
        })}
      </div>
      {gifting && (
        <GiftDialog
          plan={gifting}
          opts={{ promo: promoState?.ok ? promoState.code : undefined, ...(gst.open ? { buyer_name: gst.name || undefined, buyer_gstin: gst.gstin || undefined, buyer_state: gst.state || undefined } : {}) }}
          onClose={() => setGifting(null)}
          onDone={(text) => {
            setGifting(null);
            mascot.react("celebrate");
            setMsg({ ok: true, text });
            void qc.invalidateQueries({ queryKey: ["billing-history"] });
          }}
        />
      )}
      {!data.checkout.available && <p className="text-sm text-muted">{t("billing.unavailable")}</p>}
      <p className="text-xs text-muted">{t("billing.fineprint")}</p>
      <LegalLinks className="justify-start" />

      {!!hist?.length && (
        <Card>
          <h2 className="mb-3 flex items-center gap-2 font-display text-lg font-bold"><Receipt className="h-5 w-5" /> {t("billing.history")}</h2>
          <ul className="divide-y divide-line text-sm">
            {hist.map((o) => (
              <li key={o.id} className="flex flex-wrap items-center gap-3 py-2">
                <span className="flex-1">{o.workshop_run ? <Link to={`/workshops/${o.workshop_run}`} className="hover:underline">{o.plan}</Link> : o.plan}{o.org && <span className="text-xs text-muted"> · {o.org} × {o.seats}</span>}
                  {o.gift && <span className="block text-xs text-muted">{t(o.gift.claimed ? "billing.gift.histClaimed" : o.gift.sent ? "billing.gift.histSent" : "billing.gift.histPending", { email: o.gift.recipient_email })}{o.gift.code && <> · <span className="font-mono">{o.gift.code}</span></>}</span>}</span>
                <span className="text-muted">{date(o.created_at)}</span>
                <span className="tabular-nums">{rupees(o.amount_paise)}</span>
                <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", o.status === "paid" ? "bg-good/15 text-good" : o.status === "failed" ? "bg-bad/15 text-bad" : "bg-surface-2 text-muted")}>{t(`billing.status.${o.status}`)}</span>
                {o.auto_renew && <span className="rounded-full bg-accent/15 px-2 py-0.5 text-xs font-semibold">{t("intgSub.autoTag")}</span>}
                {o.mode === "test" && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">TEST</span>}
                {o.invoice && <button className="text-xs font-semibold text-accent" onClick={() => void downloadFile(billing.invoiceUrl(o.invoice!), "invoice.pdf")}>{t("billing.invoice")}</button>}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
