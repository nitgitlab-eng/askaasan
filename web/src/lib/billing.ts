import { ApiError, api } from "./api";

export type LimitKey = "ai_courses_per_month" | "mentor_messages_per_day" | "documents" | "voice_minutes_per_day" | "live_minutes_per_day" | "lab_ai_per_day" | "tts_chars_per_day";
export const LIMIT_KEYS: LimitKey[] = ["ai_courses_per_month", "mentor_messages_per_day", "documents", "voice_minutes_per_day", "live_minutes_per_day", "lab_ai_per_day", "tts_chars_per_day"];

export interface PlanInfo { code: string; name: string; description?: string; badge?: string; price_paise: number; period_days: number; limits: Partial<Record<LimitKey, number | null>>; auto_renew?: boolean; family?: boolean; max_members?: number }
export type SubStatus = "created" | "authenticated" | "active" | "pending" | "halted" | "paused" | "cancelled" | "completed" | "expired";
export interface SubscriptionInfo {
  id: string; plan: string; plan_code: string; status: SubStatus; mode: string; amount_paise: number; period_days: number;
  next_charge_at: string | null; current_end: string | null; method: string; cancel_at_period_end: boolean; grace_until: string | null;
  paid_count: number; can_cancel: boolean; can_resume: boolean;
}
export interface SubscriptionState { subscription: SubscriptionInfo | null; access_until: string | null }
interface SubscriptionCheckout { subscription_id: string; key_id: string; name: string; description: string; mode: string; amount: number; prefill: { email: string; name: string } }
export interface FamilyMemberInfo { id: number; name: string; is_owner: boolean; is_me: boolean; joined_at: string; email?: string }
export interface FamilyInviteInfo { id: number; email: string; expires_at: string }
/** GET /api/billing/family/ (also embedded in the billing overview). Members never get other members' emails. */
export interface FamilyState {
  role: "owner" | "member" | null;
  can_create: boolean;
  plan: { code: string; name: string } | null;
  max_members: number;
  active_until?: string | null;
  owner_name?: string;
  members?: FamilyMemberInfo[];
  invites?: FamilyInviteInfo[];
  seats_left?: number;
}
export interface FamilyInvitePreview { owner_name: string; plan: string | null; email_hint: string; for_you: boolean; problem: string | null; expires_at: string }
export interface FamilyInviteResult { invite: FamilyInviteInfo; emailed: boolean; links: { email: string; link: string; code: string }[]; code?: string }
export interface GiftInput { recipient_email: string; message?: string }
export interface GiftInfo { recipient_email: string; sent: boolean; claimed: boolean; code: string | null }
export interface BillingOverview {
  plan: PlanInfo & { source: "payment" | "grant" | "redeem" | "grace" | "family" | "gift" | null };
  paid_until: string | null;
  usage: Record<LimitKey, { used: number; max: number | null }>;
  plans: PlanInfo[];
  checkout: { available: boolean; mode: "test" | "live" | null };
  family?: FamilyState;
}
export interface PlanLimitError { code: "plan_limit"; limit: LimitKey; used: number; max: number; plan: string }
export interface CheckoutOrder { order_id: string; amount: number; currency: string; key_id: string; name: string; description: string; mode: string; prefill: { email: string; name: string } }

export interface CheckoutOpts { promo?: string; org?: string; seats?: number; buyer_name?: string; buyer_gstin?: string; buyer_state?: string; gift?: GiftInput }
export interface Quote { plan: string; seats: number; list_paise: number; discount_paise: number; total_paise: number; promo: string | null; promo_note: string }
export interface OrgBilling {
  subscription: { plan: string; plan_code: string; seats: number; starts_at: string; ends_at: string } | null;
  seats_total: number; seats_used: number; learners: number;
  orders: { id: number; plan: string; seats: number; amount_paise: number; paid_at: string; invoice: string | null }[];
  redeem_codes: { total: number; used: number };
}

export const billing = {
  overview: () => api<BillingOverview>("/api/billing/"),
  history: () => api<{ id: number; plan: string; workshop_run?: number | null; amount_paise: number; status: string; mode: string; created_at: string; payment_id: string; org: string | null; seats: number; discount_paise: number; invoice: string | null; auto_renew?: boolean; gift?: GiftInfo | null }[]>("/api/billing/history/"),
  subscription: () => api<SubscriptionState>("/api/billing/subscription/"),
  subscribe: (plan: string, opts: CheckoutOpts = {}) => api<SubscriptionCheckout>("/api/billing/subscribe/", { method: "POST", json: { plan, ...opts } }),
  subVerify: (body: Record<string, string>) => api<SubscriptionState & { ok: boolean; plan: string }>("/api/billing/subscription/verify/", { method: "POST", json: body }),
  subCancel: () => api<SubscriptionState>("/api/billing/subscription/cancel/", { method: "POST" }),
  subResume: () => api<SubscriptionState>("/api/billing/subscription/resume/", { method: "POST" }),
  quote: (plan: string, opts: CheckoutOpts = {}) => api<Quote>("/api/billing/quote/", { method: "POST", json: { plan, ...opts } }),
  checkout: (plan: string, opts: CheckoutOpts = {}) => api<CheckoutOrder & { free?: boolean; plan?: string; gift?: boolean }>("/api/billing/checkout/", { method: "POST", json: { plan, ...opts } }),
  redeem: (code: string) => api<{ plan: string; ends_at: string; org: string | null }>("/api/billing/redeem/", { method: "POST", json: { code } }),
  org: (slug: string) => api<OrgBilling>(`/api/billing/orgs/${slug}/`),
  setSeat: (slug: string, membership_id: number, seat: boolean) => api<OrgBilling>(`/api/billing/orgs/${slug}/`, { method: "POST", json: { membership_id, seat } }),
  assignSeats: (slug: string) => api<{ assigned: number }>(`/api/billing/orgs/${slug}/assign-seats/`, { method: "POST" }),
  invoiceUrl: (number: string) => `/api/billing/invoices/${number.replace(/\//g, "_")}.pdf`,
  verify: (body: Record<string, string>) => api<{ ok: boolean; plan: string; ends_at: string | null; gift?: boolean }>("/api/billing/verify/", { method: "POST", json: body }),
  failed: (razorpay_order_id: string, reason: string) => api("/api/billing/failed/", { method: "POST", json: { razorpay_order_id, reason } }),
  family: {
    get: () => api<FamilyState>("/api/billing/family/"),
    invite: (email: string) => api<FamilyInviteResult>("/api/billing/family/invite/", { method: "POST", json: { email } }),
    revokeInvite: (id: number) => api(`/api/billing/family/invites/${id}/`, { method: "DELETE" }),
    preview: (token: string) => api<FamilyInvitePreview>(`/api/billing/family/invites/${encodeURIComponent(token)}/`),
    accept: (by: { token: string } | { code: string }) => api<FamilyState>("/api/billing/family/accept/", { method: "POST", json: by }),
    remove: (memberId: number) => api<FamilyState>(`/api/billing/family/members/${memberId}/remove/`, { method: "POST" }),
    leave: () => api<FamilyState>("/api/billing/family/leave/", { method: "POST" }),
  },
};

export const rupees = (paise: number) => `₹${(paise / 100).toLocaleString("en-IN", { minimumFractionDigits: paise % 100 ? 2 : 0, maximumFractionDigits: paise % 100 ? 2 : 0 })}`;

/** Anything that hits a plan limit (REST 402 or mentor socket) announces it; AppShell shows the upgrade sheet. */
export const PLAN_LIMIT_EVENT = "aasan:plan-limit";
export function announcePlanLimit(detail: PlanLimitError) {
  window.dispatchEvent(new CustomEvent(PLAN_LIMIT_EVENT, { detail }));
}

// ── Razorpay Checkout ────────────────────────────────────────────────
interface RazorpayResponse { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string }
interface RazorpayInstance { open(): void; on(ev: "payment.failed", cb: (r: { error: { description?: string; metadata?: { order_id?: string } } }) => void): void }
declare global {
  interface Window { Razorpay?: new (opts: object) => RazorpayInstance }
}

let loader: Promise<void> | null = null;
function loadCheckout(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  loader ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.onload = () => resolve();
    s.onerror = () => { loader = null; reject(new Error("checkout_load_failed")); };
    document.body.appendChild(s);
  });
  return loader;
}

const VERIFY_CODES = ["payment_pending", "payment_not_captured", "promo_used_up"];
/** Reason code for a failed /verify/ call; anything unexpected stays "verify_failed". */
export function verifyError(e: unknown, extra: readonly string[] = []): string {
  const d = e instanceof ApiError ? e.data : null;
  const code = String(d?.code ?? d?.detail ?? "");
  return VERIFY_CODES.includes(code) || extra.includes(code) ? code : "verify_failed";
}

/** Opens Razorpay Checkout. Resolves on verified payment, rejects with a reason code otherwise. */
export async function payForPlan(plan: string, accent: string, opts: CheckoutOpts = {}): Promise<{ plan: string; ends_at?: string | null; free?: boolean; gift?: boolean }> {
  const order = await billing.checkout(plan, opts);
  if (order.free) return { plan: order.plan ?? plan, free: true, gift: order.gift }; // 100% promo: no payment needed
  return payOrder(order, accent);
}

/** Buys `plan` as a gift (always pay-once): on payment the server emails the recipient a one-time code. */
export function giftPlan(plan: string, accent: string, gift: GiftInput, opts: Omit<CheckoutOpts, "gift" | "org" | "seats"> = {}) {
  return payForPlan(plan, accent, { ...opts, gift });
}

/**
 * Pays an order the server already created (a plan, or a workshop seat) in Razorpay Checkout, then confirms it with
 * /verify/. The server grants only on its own verified capture; this callback merely asks it to check.
 */
export async function payOrder<T = { plan: string; ends_at?: string }>(order: CheckoutOrder, accent: string, verifyCodes: readonly string[] = []): Promise<T> {
  await loadCheckout();
  return new Promise((resolve, reject) => {
    const rz = new window.Razorpay!({
      key: order.key_id,
      order_id: order.order_id,
      amount: order.amount,
      currency: order.currency,
      name: order.name,
      description: order.description,
      prefill: order.prefill,
      theme: { color: accent },
      // The server names why it couldn't activate (payment_pending, payment_not_captured, promo_used_up).
      handler: (r: RazorpayResponse) => billing.verify({ ...r }).then((v) => resolve(v as T), (e) => reject(new Error(verifyError(e, verifyCodes)))),
      modal: { ondismiss: () => reject(new Error("dismissed")) },
    });
    rz.on("payment.failed", (r) => {
      void billing.failed(order.order_id, r.error.description ?? "failed");
    });
    rz.open();
  });
}

/** "month" | "year" | null (any other period): which auto-renew label a plan gets. */
export function renewInterval(periodDays: number): "month" | "year" | null {
  if (periodDays >= 28 && periodDays <= 31) return "month";
  if (periodDays >= 360 && periodDays <= 366) return "year";
  return null;
}

/** Statuses where the learner should look at the subscription (a problem or a pending action). */
export const subNeedsAttention = (s: SubStatus) => s === "pending" || s === "halted" || s === "paused";

/** Auto-renew: create the Razorpay subscription, authorise it in Checkout, then confirm with the server. */
export async function subscribeToPlan(plan: string, accent: string, opts: CheckoutOpts = {}): Promise<SubscriptionState & { plan: string }> {
  const sub = await billing.subscribe(plan, opts);
  await loadCheckout();
  return new Promise((resolve, reject) => {
    const rz = new window.Razorpay!({
      key: sub.key_id,
      subscription_id: sub.subscription_id,
      name: sub.name,
      description: sub.description,
      prefill: sub.prefill,
      theme: { color: accent },
      handler: (r: { razorpay_payment_id: string; razorpay_subscription_id: string; razorpay_signature: string }) =>
        billing.subVerify({ ...r }).then(resolve, () => reject(new Error("verify_failed"))),
      modal: { ondismiss: () => reject(new Error("dismissed")) },
    });
    rz.open();
  });
}
