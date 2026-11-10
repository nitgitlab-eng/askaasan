import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Copy, FlaskConical, Gift, KeyRound, Plus, Save, Users, XCircle } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import i18n from "@/i18n";
import { confirmDialog } from "@/lib/dialog";
import { Button, Card, Toggle } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { LIMIT_KEYS, rupees, type LimitKey } from "@/lib/billing";
import { cn } from "@/lib/cn";

interface PayConfig {
  key_id: string; mode: "test" | "live" | null; enabled: boolean; allow_live: boolean; ready: boolean; business_name: string;
  secret: string | null; webhook_secret: string | null; source: Record<"key_id" | "secret" | "webhook_secret", "admin" | "env" | null>; webhook_path: string; webhook_events: string[];
}
interface Plan { id: number; code: string; name: string; description: string; price_paise: number; period_days: number; limits: Partial<Record<LimitKey, number | null>>; badge: string; active: boolean; sort: number; rp_plan_id: string; auto_renew: boolean; family: boolean; max_members: number }
interface Subs { subscriptions: { id: string; email: string; plan: string; status: string; mode: string; amount_paise: number; paid_count: number; charge_at: string | null; cancel_at_period_end: boolean }[] }
interface Orders {
  summary: { paid: number; revenue_paise: number; failed: number; by_plan: { plan__name: string; n: number; revenue: number }[] };
  orders: { id: number; email: string; plan: string; amount_paise: number; status: string; mode: string; created_at: string; payment_id: string; order_id: string; error: string }[];
}

const input = "w-full rounded-xl border-2 border-line bg-surface px-3 py-2 outline-none focus:border-accent";
const errText = (e: unknown) => (e instanceof ApiError ? String(e.data?.detail ?? e.data?.code ?? JSON.stringify(e.data)) : i18n.t("mentor.errors.generic"));

function KeysCard({ cfg }: { cfg: PayConfig }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [keyId, setKeyId] = useState(cfg.key_id);
  const [secret, setSecret] = useState("");
  const [hook, setHook] = useState("");
  const [name, setName] = useState(cfg.business_name);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(null);
  const webhookUrl = `${location.origin}${cfg.webhook_path}`;

  async function patch(body: object) {
    setBusy(true);
    setResult(null);
    try {
      qc.setQueryData(["admin-pay-config"], await api<PayConfig>("/api/admin/payments/config/", { method: "PATCH", json: body }));
      return true;
    } catch (e) {
      setResult({ ok: false, detail: errText(e) });
      return false;
    } finally {
      setBusy(false);
    }
  }
  async function save(e: FormEvent) {
    e.preventDefault();
    const body: Record<string, string> = { business_name: name };
    if (keyId !== cfg.key_id) body.key_id = keyId.trim();
    if (secret) body.key_secret = secret;
    if (hook) body.webhook_secret = hook;
    if (await patch(body)) {
      setSecret("");
      setHook("");
      setResult({ ok: true, detail: t("adminPay.saved") });
    }
  }
  async function test() {
    setBusy(true);
    try {
      setResult(await api("/api/admin/payments/test/", { method: "POST" }));
    } catch (e) {
      setResult({ ok: false, detail: e instanceof ApiError ? String(e.data?.detail ?? e.data?.code) : t("adminPay.testFailed") });
    } finally {
      setBusy(false);
    }
  }
  const badge = (from: string | null) => from && <span className="ml-2 rounded bg-surface-2 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-muted">{from === "env" ? t("adminPay.fromEnv") : t("adminPay.fromAdmin")}</span>;

  return (
    <Card className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 font-display text-xl font-bold"><KeyRound className="h-5 w-5" /> {t("adminPay.keysTitle")}</h2>
          <p className="text-xs text-muted">{t("adminPay.keysHint")}</p>
        </div>
        <div className="flex items-center gap-2">
          {cfg.mode && <span className={cn("flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-bold", cfg.mode === "test" ? "bg-amber-100 text-amber-800" : "bg-bad/15 text-bad")}>{cfg.mode === "test" && <FlaskConical className="h-3.5 w-3.5" />}{cfg.mode === "test" ? t("adminPay.modeTest") : t("adminPay.modeLive")}</span>}
          <span className={cn("rounded-full px-2.5 py-1 text-xs font-bold", cfg.ready ? "bg-good/15 text-good" : "bg-surface-2 text-muted")}>{cfg.ready ? t("adminPay.checkoutOn") : t("adminPay.checkoutOff")}</span>
        </div>
      </header>
      <form onSubmit={save} className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm font-medium">{t("adminPay.keyId")} {badge(cfg.source.key_id)}
          <input value={keyId} onChange={(e) => setKeyId(e.target.value)} placeholder="rzp_test_…" className={cn(input, "mt-1 font-mono")} autoComplete="off" />
        </label>
        <label className="text-sm font-medium">{t("adminPay.keySecret")} {badge(cfg.source.secret)}
          <input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder={cfg.secret ?? t("adminPay.pasteKeySecret")} className={cn(input, "mt-1 font-mono")} autoComplete="new-password" />
        </label>
        <label className="text-sm font-medium">{t("adminPay.webhookSecret")} <span className="font-normal text-muted">{t("adminPay.optional")}</span> {badge(cfg.source.webhook_secret)}
          <input type="password" value={hook} onChange={(e) => setHook(e.target.value)} placeholder={cfg.webhook_secret ?? t("adminPay.pasteWebhook")} className={cn(input, "mt-1 font-mono")} autoComplete="new-password" />
        </label>
        <label className="text-sm font-medium">{t("adminPay.checkoutName")}
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} className={cn(input, "mt-1")} />
        </label>
        <div className="flex flex-wrap gap-2 sm:col-span-2">
          <Button type="submit" loading={busy}><Save className="h-4 w-4" /> {t("common.save")}</Button>
          <Button type="button" variant="outline" disabled={busy || !cfg.key_id} onClick={test}>{t("adminPay.test")}</Button>
        </div>
      </form>
      {result && <p role="status" className={cn("flex items-center gap-2 text-sm", result.ok ? "text-good" : "text-bad")}>{result.ok ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />} {result.detail}</p>}
      <div className="flex flex-wrap gap-6 border-t border-line pt-4">
        <Toggle checked={cfg.enabled} onChange={(v) => void patch({ enabled: v })} label={t("adminPay.enabled")} />
        <Toggle checked={cfg.allow_live} onChange={async (v) => { if (!v || (await confirmDialog(t("admin.allowLiveConfirm"), { danger: true }))) void patch({ allow_live: v }); }} label={t("admin.allowLive")} />
      </div>
      <div className="rounded-xl bg-surface-2 p-3 text-sm">
        <p className="font-semibold">{t("adminPay.webhookTitle")}</p>
        <p className="text-muted">{t("adminPay.webhookHelp1")} {cfg.webhook_events.map((ev) => <code key={ev} className="mr-1 inline-block">{ev}</code>)} {t("adminPay.webhookHelp2")}</p>
        <div className="mt-2 flex items-center gap-2">
          <code className="min-w-0 flex-1 truncate rounded bg-surface px-2 py-1">{webhookUrl}</code>
          <Button variant="ghost" className="py-1 text-sm" aria-label={t("adminPay.copyWebhook")} onClick={() => void navigator.clipboard.writeText(webhookUrl)}><Copy className="h-4 w-4" /></Button>
        </div>
      </div>
    </Card>
  );
}

function PlanRow({ p }: { p: Plan }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [d, setD] = useState({ name: p.name, description: p.description, badge: p.badge, price: String(p.price_paise / 100), days: String(p.period_days), active: p.active, limits: { ...p.limits }, rp: p.rp_plan_id, auto: p.auto_renew, family: p.family, members: String(p.max_members) });
  const [msg, setMsg] = useState("");
  const free = p.code === "free";
  async function save() {
    setMsg("");
    try {
      await api(`/api/admin/plans/${p.id}/`, { method: "PATCH", json: {
        name: d.name, description: d.description, badge: d.badge, active: d.active, limits: d.limits,
        ...(free ? {} : { price_paise: Math.round(Number(d.price) * 100), period_days: Number(d.days), rp_plan_id: d.rp.trim(), auto_renew: d.auto, family: d.family, max_members: Number(d.members) }),
      } });
      setMsg(t("adminPay.planSaved"));
      void qc.invalidateQueries({ queryKey: ["admin-plans"] });
    } catch (e) {
      setMsg(errText(e));
    }
  }
  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <code className="rounded bg-surface-2 px-2 py-0.5 text-xs">{p.code}</code>
        <input value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} className={cn(input, "w-auto flex-1 font-semibold")} aria-label={t("adminPay.planName")} />
        {!free && <Toggle checked={d.active} onChange={(v) => setD({ ...d, active: v })} label={t("adminPay.onSale")} />}
      </div>
      <div className="grid gap-2 sm:grid-cols-4">
        <label className="text-xs text-muted">{t("adminPay.price")}<input type="number" min={free ? 0 : 1} step="1" disabled={free} value={d.price} onChange={(e) => setD({ ...d, price: e.target.value })} className={input} /></label>
        <label className="text-xs text-muted">{t("adminPay.days")}<input type="number" min={1} disabled={free} value={d.days} onChange={(e) => setD({ ...d, days: e.target.value })} className={input} /></label>
        <label className="text-xs text-muted sm:col-span-2">{t("adminPay.badge")}<input value={d.badge} maxLength={40} onChange={(e) => setD({ ...d, badge: e.target.value })} placeholder={t("adminPay.badgePh")} className={input} /></label>
      </div>
      {!free && (
        <div className="flex flex-wrap items-end gap-3 rounded-xl bg-surface-2 p-3">
          <label className="text-xs text-muted">{t("adminPay.rpPlan")}
            <input value={d.rp} onChange={(e) => setD({ ...d, rp: e.target.value })} placeholder="plan_XXXXXXXXXXXX" className={cn(input, "font-mono")} autoComplete="off" />
          </label>
          <Toggle checked={d.auto} onChange={(v) => setD({ ...d, auto: v })} label={t("adminPay.offerAuto")} />
          <p className="w-full text-xs text-muted">{t("adminPay.rpHelp", { price: d.price })}</p>
        </div>
      )}
      {!free && (
        <div className="flex flex-wrap items-end gap-3 rounded-xl bg-surface-2 p-3">
          <Users className="mb-2 h-5 w-5 text-accent" />
          <Toggle checked={d.family} onChange={(v) => setD({ ...d, family: v })} label={t("adminPay.family")} />
          <label className="text-xs text-muted">{t("adminPay.maxMembers")}
            <input type="number" min={2} max={20} disabled={!d.family} value={d.members} onChange={(e) => setD({ ...d, members: e.target.value })} className={cn(input, "w-24")} />
          </label>
          <p className="w-full text-xs text-muted">{t("adminPay.familyHelp")}</p>
        </div>
      )}
      <label className="block text-xs text-muted">{t("adminPay.description")}<input value={d.description} maxLength={240} onChange={(e) => setD({ ...d, description: e.target.value })} className={input} /></label>
      <div className="grid gap-2 sm:grid-cols-3">
        {LIMIT_KEYS.map((k) => (
          <label key={k} className="text-xs text-muted">{t(`adminPay.limits.${k}`)}
            <input type="number" min={0} value={d.limits[k] ?? ""} placeholder={t("adminPay.unlimited")} onChange={(e) => setD({ ...d, limits: { ...d.limits, [k]: e.target.value === "" ? null : Number(e.target.value) } })} className={input} />
          </label>
        ))}
      </div>
      <div className="flex items-center gap-3"><Button onClick={save} className="py-1.5 text-sm"><Save className="h-4 w-4" /> {t("adminPay.savePlan")}</Button><span className="text-sm text-muted">{msg}</span></div>
    </Card>
  );
}

function Grant({ plans }: { plans: Plan[] }) {
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [plan, setPlan] = useState(plans.find((p) => p.price_paise > 0)?.code ?? "");
  const [days, setDays] = useState("30");
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState("");
  async function go(e: FormEvent) {
    e.preventDefault();
    try {
      const r = await api<{ email: string; plan: string; ends_at: string }>("/api/admin/payments/grant/", { method: "POST", json: { email, plan, days: Number(days), note } });
      setMsg(t("adminPay.granted", { email: r.email, plan: r.plan, date: new Date(r.ends_at).toLocaleDateString() }));
      setEmail("");
    } catch (x) {
      setMsg(x instanceof ApiError && x.data?.code === "user_not_found" ? t("adminPay.noUser") : errText(x));
    }
  }
  return (
    <Card>
      <form onSubmit={go} className="grid gap-2 sm:grid-cols-5">
        <h2 className="flex items-center gap-2 font-display text-lg font-bold sm:col-span-5"><Gift className="h-5 w-5" /> {t("adminPay.grantTitle")}</h2>
        <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="learner@email.com" className={cn(input, "sm:col-span-2")} aria-label={t("adminPay.email")} />
        <select value={plan} onChange={(e) => setPlan(e.target.value)} className={input} aria-label={t("adminPay.plan")}>{plans.filter((p) => p.price_paise > 0).map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}</select>
        <input type="number" min={1} max={3660} value={days} onChange={(e) => setDays(e.target.value)} className={input} aria-label={t("adminPay.daysField")} />
        <Button type="submit">{t("adminPay.grant")}</Button>
        <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} placeholder={t("adminPay.note")} className={cn(input, "sm:col-span-5")} aria-label={t("adminPay.note")} />
        {msg && <p className="text-sm text-muted sm:col-span-5">{msg}</p>}
      </form>
    </Card>
  );
}

/** A new paid plan (e.g. a family plan): code, name, price and days; limits and the rest are edited on its card. */
function NewPlan() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [d, setD] = useState({ code: "", name: "", price: "", days: "30", family: false });
  const [msg, setMsg] = useState("");
  async function create(e: FormEvent) {
    e.preventDefault();
    setMsg("");
    try {
      await api("/api/admin/plans/", { method: "POST", json: {
        code: d.code.trim(), name: d.name.trim(), price_paise: Math.round(Number(d.price) * 100), period_days: Number(d.days),
        limits: {}, active: false, family: d.family, max_members: 5,
      } });
      setD({ code: "", name: "", price: "", days: "30", family: false });
      setOpen(false);
      void qc.invalidateQueries({ queryKey: ["admin-plans"] });
    } catch (err) {
      setMsg(errText(err));
    }
  }
  if (!open) return <Button variant="outline" onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> {t("adminPay.newPlan")}</Button>;
  return (
    <Card>
      <form onSubmit={create} className="grid gap-2 sm:grid-cols-5">
        <label className="text-xs text-muted">{t("adminPay.planCode")}<input required value={d.code} onChange={(e) => setD({ ...d, code: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, "") })} maxLength={40} placeholder="family_year" className={cn(input, "font-mono")} /></label>
        <label className="text-xs text-muted sm:col-span-2">{t("adminPay.planName")}<input required value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} maxLength={80} className={input} /></label>
        <label className="text-xs text-muted">{t("adminPay.price")}<input required type="number" min={1} value={d.price} onChange={(e) => setD({ ...d, price: e.target.value })} className={input} /></label>
        <label className="text-xs text-muted">{t("adminPay.days")}<input required type="number" min={1} value={d.days} onChange={(e) => setD({ ...d, days: e.target.value })} className={input} /></label>
        <div className="flex flex-wrap items-center gap-3 sm:col-span-5">
          <Toggle checked={d.family} onChange={(v) => setD({ ...d, family: v })} label={t("adminPay.family")} />
          <Button type="submit" className="py-1.5 text-sm">{t("adminPay.createPlan")}</Button>
          <Button type="button" variant="ghost" className="py-1.5 text-sm" onClick={() => setOpen(false)}>{t("dialog.cancel")}</Button>
          <span className="text-sm text-muted">{msg || t("adminPay.newPlanHint")}</span>
        </div>
      </form>
    </Card>
  );
}

export default function AdminPayments() {
  const { t } = useTranslation();
  const { data: cfg } = useQuery({ queryKey: ["admin-pay-config"], queryFn: () => api<PayConfig>("/api/admin/payments/config/") });
  const { data: plans } = useQuery({ queryKey: ["admin-plans"], queryFn: () => api<Plan[]>("/api/admin/plans/") });
  const [mode, setMode] = useState<"test" | "live">("test");
  const { data: orders } = useQuery({ queryKey: ["admin-orders", mode], queryFn: () => api<Orders>(`/api/admin/payments/orders/?mode=${mode}`) });
  const { data: subs } = useQuery({ queryKey: ["admin-subs"], queryFn: () => api<Subs>("/api/admin/payments/subscriptions/") });
  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("adminPay.title")}</h1>
        <p className="text-muted">{t("adminPay.sub")}</p>
      </header>
      {cfg && <KeysCard key={`${cfg.key_id}:${cfg.secret}:${cfg.webhook_secret}`} cfg={cfg} />}

      <section className="space-y-3">
        <h2 className="font-display text-2xl font-bold">{t("adminPay.plans")}</h2>
        <p className="text-sm text-muted">{t("adminPay.plansHint")}</p>
        {plans?.map((p) => <PlanRow key={`${p.id}:${p.price_paise}:${JSON.stringify(p.limits)}:${p.rp_plan_id}:${p.auto_renew}:${p.family}:${p.max_members}`} p={p} />)}
        <NewPlan />
      </section>

      {plans && <Grant plans={plans} />}

      {!!subs?.subscriptions.length && (
        <section className="space-y-3">
          <h2 className="font-display text-2xl font-bold">{t("adminPay.subsTitle")}</h2>
          <Card className="overflow-x-auto p-0">
            <table className="w-full min-w-[36rem] text-sm">
              <thead className="text-left text-xs text-muted"><tr><th className="px-4 py-2">{t("adminPay.th.learner")}</th><th>{t("adminPay.th.plan")}</th><th>{t("adminPay.th.status")}</th><th>{t("adminPay.th.charges")}</th><th>{t("adminPay.th.nextCharge")}</th><th>{t("adminPay.th.id")}</th></tr></thead>
              <tbody>
                {subs.subscriptions.map((s) => (
                  <tr key={s.id} className="border-t border-line">
                    <td className="px-4 py-2">{s.email}</td><td>{s.plan} · {rupees(s.amount_paise)}</td>
                    <td>{s.status}{s.cancel_at_period_end && ` ${t("adminPay.endsAtPeriodEnd")}`}{s.mode === "test" && ` · ${t("adminPay.testTag")}`}</td>
                    <td className="tabular-nums">{s.paid_count}</td>
                    <td>{s.charge_at && !s.cancel_at_period_end ? new Date(s.charge_at).toLocaleDateString() : "—"}</td>
                    <td className="font-mono text-xs">{s.id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
          <p className="text-xs text-muted">{t("adminPay.subsNote")}</p>
        </section>
      )}

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-display text-2xl font-bold">{t("adminPay.payments")}</h2>
          <div className="flex gap-1 rounded-xl bg-surface-2 p-1 text-sm">
            {(["test", "live"] as const).map((m) => <button key={m} onClick={() => setMode(m)} className={cn("rounded-lg px-3 py-1 font-semibold", mode === m ? "bg-surface shadow" : "text-muted")}>{m === "test" ? t("adminPay.testBtn") : t("adminPay.liveBtn")}</button>)}
          </div>
        </div>
        {orders && (
          <>
            <div className="grid grid-cols-3 gap-3">
              <Card className="p-4"><p className="text-xs text-muted">{t("adminPay.revenue")}</p><p className="font-display text-2xl font-extrabold">{rupees(orders.summary.revenue_paise)}</p></Card>
              <Card className="p-4"><p className="text-xs text-muted">{t("adminPay.paid")}</p><p className="font-display text-2xl font-extrabold">{orders.summary.paid}</p></Card>
              <Card className="p-4"><p className="text-xs text-muted">{t("adminPay.failed")}</p><p className="font-display text-2xl font-extrabold">{orders.summary.failed}</p></Card>
            </div>
            <Card className="overflow-x-auto p-0">
              <table className="w-full min-w-[36rem] text-sm">
                <thead className="text-left text-xs text-muted"><tr><th className="px-4 py-2">{t("adminPay.th.when")}</th><th>{t("adminPay.th.learner")}</th><th>{t("adminPay.th.plan")}</th><th>{t("adminPay.th.amount")}</th><th>{t("adminPay.th.status")}</th><th>{t("adminPay.th.paymentId")}</th></tr></thead>
                <tbody>
                  {orders.orders.length === 0 && <tr><td colSpan={6} className="px-4 py-6 text-center text-muted">{mode === "test" ? t("adminPay.noTest") : t("adminPay.noLive")}</td></tr>}
                  {orders.orders.map((o) => (
                    <tr key={o.id} className="border-t border-line" title={o.error || o.order_id}>
                      <td className="px-4 py-2 whitespace-nowrap">{new Date(o.created_at).toLocaleString()}</td>
                      <td>{o.email}</td><td>{o.plan}</td><td className="tabular-nums">{rupees(o.amount_paise)}</td>
                      <td><span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", o.status === "paid" ? "bg-good/15 text-good" : o.status === "failed" ? "bg-bad/15 text-bad" : "bg-surface-2 text-muted")}>{o.status}</span></td>
                      <td className="font-mono text-xs">{o.payment_id || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </>
        )}
      </section>
    </div>
  );
}
