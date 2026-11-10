import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ComponentType } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";
import en from "@/i18n/en";
import { api } from "@/lib/api";
import { useAuth } from "@/stores/auth";
import { apiRoutes, renderPage } from "@/test/render";

import { AdminLayout } from "./AdminLayout";
import AdminCalendarApps from "./CalendarApps";
import AdminCatalog from "./Catalog";
import AdminCertificates from "./Certificates";
import AdminCodes from "./Codes";
import AdminEmail from "./Email";
import AdminFamilyGroups from "./FamilyGroups";
import AdminFeatures from "./Features";
import AdminOrgs from "./Orgs";
import AdminOverview from "./Overview";
import AdminPayments from "./Payments";
import AdminProviders from "./Providers";
import AdminRefunds from "./Refunds";
import SiteLegal from "./SiteLegal";
import AdminStaff from "./Staff";
import AdminSupport from "./Support";
import SystemCheck from "./SystemCheck";
import AdminUsers from "./Users";
import AdminWorkshops from "./Workshops";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));
vi.mock("@/components/tour/tourStore", () => ({ startTour: vi.fn(), useAutoTour: vi.fn() }));
vi.mock("@/components/tour/Tour", () => ({ TourHost: () => null }));
// The layout applies the staff member's saved language; keep the fake language in place instead.
vi.mock("@/lib/useMe", async (orig) => ({ ...(await orig<typeof import("@/lib/useMe")>()), useApplyAppearance: vi.fn() }));

/** Every string in en.ts replaced by "✓": whatever still reads as English on screen is a hardcoded literal. */
function tick(o: unknown): unknown {
  if (typeof o === "string") return "✓";
  if (Array.isArray(o)) return o.map(tick);
  if (o && typeof o === "object") return Object.fromEntries(Object.entries(o).map(([k, v]) => [k, tick(v)]));
  return o;
}
/** Two English words in a row; a product name, email, slug, model id or number never matches this. */
const SENTENCE = /[A-Za-z]{4,} [A-Za-z]{3,}/;
/** Product and provider names stay in English in every language. */
const PRODUCT_NAMES = ["Anthropic Claude", "Google Gemini", "Google Cloud", "Sarvam AI", "Gmail / Google Workspace", "Zoho Mail (India)", "Amazon SES (Mumbai)"];

function offenders(root: HTMLElement): string[] {
  const out = new Set<string>();
  const check = (s: string | null) => {
    const v = (s ?? "").trim();
    if (v && SENTENCE.test(v) && !PRODUCT_NAMES.some((p) => v === p || v.replace(/[()]/g, "").includes(p.replace(/[()]/g, "")))) out.add(v);
  };
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (n.parentElement?.closest("code, pre, script, style")) continue; // commands and JSON are not UI copy
    check(n.textContent);
  }
  for (const el of root.querySelectorAll("[placeholder], [aria-label], [title], img[alt]")) {
    for (const a of ["placeholder", "aria-label", "title", "alt"]) check(el.getAttribute(a));
  }
  return [...out];
}

const me = {
  id: 1, email: "staff@aasan.in", email_verified: true, is_staff: true, staff_roles: ["superadmin"], is_creator: false, can_author: true, has_password: true,
  profile: { display_name: "", language: "en" }, preferences: { appearance: {}, mascot: {}, learning: {} }, consent: { required: false },
};
const user = { id: 9, email: "arun@school.in", name: "Arun", joined: "2026-10-01", last_login: "2026-10-20", active: true, verified: false, staff: true, creator: true, minor: true, orgs: 1, courses: 2 };
const org = { id: 3, name: "Vidya", slug: "vidya", kind: "school", members: 40, seats_paid: 30, seats_used: 35, workshop_seats: 100, suspended: true, created_at: "2026-09-01" };
const series = [{ day: "2026-10-20", value: 3 }, { day: "2026-10-21", value: 5 }];
const overview = {
  days: 30,
  users: { total: 120, new: 8, verified: 100, minors: 4, tamil_ui: 30, creators: 6, series },
  learning: { active_7d: 20, active_window: 50, active_series: series, lessons_completed: 300, lessons_series: series, courses_created: 12, mentor_messages: 900, roleplays: 40, live_classes: 5, live_minutes: 120, orgs: 3 },
  money: { live_all: 500000, live_window: 100000, test_all: 1000, test_window: 500, paying_now: 11, series },
  ai: {
    calls: 1000, input_tokens: 2000, output_tokens: 3000, cost_inr: 123.4, cost_complete: false, series,
    by_model: [{ provider: "fake", model: "fake-1", calls: 10, tin: 20, tout: 30, cost_inr: null }],
    by_task: [{ task: "tutor", calls: 5, tokens: 500 }, { task: "custom_task", calls: 1, tokens: 1 }],
    top_users: [{ email: "arun@school.in", calls: 5, tokens: 500 }],
    voice_minutes: 10, tts_chars: 2000, vision_snapshots: 3, images: 2,
  },
  platform: {
    workshops: { enrolments: 10, enrolments_window: 4, revenue_paise: 10000, refunds_due: 1 },
    certificates: { total: 50, window: 5, by_kind: { course: 40, workshop: 10 } },
    orgs: { by_kind: { school: 2, company: 1 }, suspended: 1, paying: 2, seats_paid: 100, seats_used: 60 },
    subscriptions: { active: 3, mrr_paise: 60000, churned_window: 1 },
    family: { groups: 2, members: 5, mrr_paise: 29900 },
    refunds: { count_window: 2, paise_window: 5000 },
  },
};
const provider = {
  capability: "tts", label: "Narration", provider: "deepgram", model: "aura-2", voices: {}, enabled: true,
  limits: { tts_chars_per_day: 1000, other_limit: 5 }, source: "env", key: { needed: true, set: true, from: "env", masked: "…abcd", env_var: "DEEPGRAM_API_KEY" },
};
const providerSpec = { models: ["aura-2"], default_model: "aura-2", voices: { en: ["asteria"], ta: [] }, host_voices: { en: ["asteria", "orion"] } };
const stt = { ...provider, capability: "stt", label: "Listening", provider: "browser", model: "", limits: { stt_seconds_per_day: 600 }, source: "db", key: { needed: false, set: false, from: null, masked: null, env_var: null } };
const routes = apiRoutes({
  "/api/users/me/": me,
  "/api/admin/users/9/": { ...user, roles: ["support"], age_band: "under18", guardian_email: "amma@x.in", plans: [{ plan: "pro", source: "razorpay", starts_at: "2026-10-01", ends_at: "2026-11-01", active: true, note: "" }], payments: { count: 2, total_paise: 39800 }, orgs: [{ id: 3, name: "Vidya", slug: "vidya", role: "learner" }], courses: { own: 1, enrolled: 1 }, certificates: [{ id: 1, title: "UPI", kind: "course", issued_at: "2026-10-02", revoked: false }], ai_30d: { calls: 3, tokens: 1200 }, devices: { passkeys: 1, extension: 2 } },
  "/api/admin/users/": { results: [user], count: 1, page: 1, pages: 1, totals: { total: 5, active_7d: 2 } },
  "/api/admin/orgs/3/": { ...org, name_legal: "VidyaTrust", description: "", members_by_role: { learner: 38, teacher: 2 }, admins: [{ id: 2, email: "head@vidya.in", role: "admin" }], subscription: { plan: null, seats: 30, starts_at: "2026-09-01", ends_at: "2027-09-01" }, features: { workshops: true, surveys: false }, platform_features: ["workshops"], workshop_seats_used: 12, branding: { brand_color: "", logo_url: "" }, dpa: { version: "1", accepted_at: "2026-09-02" }, suspended_at: "2026-10-10", suspended_reason: "unpaid", certificates: 7, sso: { provider: "google", enabled: true, enforced: true, hosted_domains: ["vidya.in"], domains: [{ domain: "vidya.in", verified: true }] } },
  "/api/admin/orgs/": { results: [org], count: 1, page: 1, pages: 1, by_kind: { school: 1 } },
  "/api/admin/catalog/": [{ id: 7, title: "UPI", description: "", cover_emoji: "📘", owner_email: "t@x.in", lessons: 1, share_token: "s" }],
  "/api/admin/certificates/": { results: [{ id: 1, code: "AB12", kind: "course", title: "UPI", learner: "Arun", email: "arun@school.in", issuer: "Aasan", org_id: null, issued_at: "2026-10-02", revoked: false, hidden: false }], count: 1, page: 1, pages: 1, stats: { total: 1, last_30d: 1, revoked: 0, by_kind: { course: 1 } } },
  "/api/admin/workshops/orgs/": [{ id: 3, slug: "vidya", name: "Vidya", members: 40, workshops: true, workshop_seats: 100, seats_used: 12 }],
  "/api/admin/workshops/runs/": [],
  "/api/admin/workshops/": [],
  "/api/admin/payments/config/": { key_id: "rzp_test_1", mode: "test", enabled: true, allow_live: false, ready: true, business_name: "Aasan", secret: "…ab", webhook_secret: null, source: { key_id: "admin", secret: "admin", webhook_secret: null }, webhook_path: "/api/billing/webhook/", webhook_events: ["payment.captured"] },
  "/api/admin/payments/orders/": { summary: { paid: 1, revenue_paise: 19900, failed: 0, by_plan: [{ plan__name: "Pro", n: 1, revenue: 19900 }] }, orders: [{ id: 4, email: "buyer@x.in", plan: "Pro", amount_paise: 19900, refunded_paise: 0, status: "paid", mode: "test", created_at: "2026-10-10", paid_at: "2026-10-10", payment_id: "pay_1", order_id: "order_1", error: "" }] },
  "/api/admin/payments/subscriptions/": { subscriptions: [{ id: "sub_1", email: "buyer@x.in", plan: "Pro", status: "active", mode: "test", amount_paise: 19900, paid_count: 2, charge_at: "2026-11-10", cancel_at_period_end: false }] },
  "/api/admin/plans/": [{ id: 1, code: "pro", name: "Pro", description: "", price_paise: 19900, period_days: 30, limits: {}, badge: "", active: true, sort: 1, rp_plan_id: "", auto_renew: false, family: true, max_members: 5 }],
  "/api/admin/family-groups/": { results: [{ id: 1, owner: "amma@home.in", plan: "Family", active_until: "2026-11-20", max_members: 5, members_count: 2, members: ["appa@home.in"], pending_invites: 1, created_at: "2026-10-01" }, { id: 2, owner: "solo@home.in", plan: null, active_until: null, max_members: 0, members_count: 1, members: [], pending_invites: 0, created_at: "2026-10-02" }], count: 2, page: 1, pages: 1, groups: 2, members: 3 },
  "/api/admin/gifts/": { results: (["sent", "not_sent", "claimed", "void", "pending", "unpaid"] as const).map((status, i) => ({ id: i + 1, order_id: 9, buyer: "magan@home.in", recipient: "paati@home.in", plan: "Pro", amount_paise: 19900, mode: "test", status, code_last4: "AB12", expires_at: "2027-10-01", created_at: "2026-10-01", sent_at: null, claimed_at: null })), count: 6, page: 1, pages: 1 },
  "/api/admin/refunds/": { results: [{ id: 1, order_id: 4, email: "buyer@x.in", label: "Pro", amount_paise: 5000, reason: "dup", status: "processed", error: "", access_ended: true, by: "staff@aasan.in", created_at: "2026-10-11" }], count: 1, page: 1, pages: 1, total_paise: 5000 },
  "/api/admin/promos/": [{ id: 1, code: "DIWALI50", kind: "percent", value: 50, plans: [], expires_at: null, max_uses: 10, uses: 2, per_user: 1, max_seats: 0, active: true, note: "" }],
  "/api/admin/redeem-codes/": [{ code: "ABCD-1234", plan: "pro", days: 90, batch: "vidya-t1", expires_at: null, redeemed: false, redeemed_by: null }],
  "/api/admin/invoices/": [{ number: "AA/26/1", issued_at: "2026-10-10", buyer: "buyer@x.in", total_paise: 19900, taxable_paise: 16864, gst_paise: 3036, mode: "test" }],
  "/api/admin/reports/": { counts: { new: 1 }, rows: [{ id: 5, category: "bug", text: "...", page: "/learn", status: "new", reply: "", replied_at: null, created_at: "2026-10-10", screenshot: "", ref: "lesson:1", browser: "Chrome/130", email: "arun@school.in", user: null }] },
  "/api/admin/help/": [{ id: 1, slug: "start", category: "start", title: "UPI", title_ta: "", body_md: "", body_ta_md: "", order: 1, published: true }],
  "/api/admin/calendar-apps/": { apps: [{ provider: "google", label: "Google", client_id: "", secret: null, tenant: "", enabled: false, ready: false, redirect_uri: "http://localhost/cb", scopes: ["calendar.readonly"], console: "https://console.example", env_vars: ["GOOGLE_ID"], connections: 0, updated_at: null }] },
  "/api/admin/mail/": { enabled: false, host: "", port: 587, security: "tls", username: "", password: "…ab", from_email: "", from_name: "", ready: false, fallback: "console" },
  "/api/admin/providers/": { catalog: { tts: { label: "Narration", providers: { deepgram: providerSpec, browser: { ...providerSpec, no_key: true } }, default: "browser", recommended: "sarvam" }, stt: { label: "Listening", providers: { browser: { models: [], default_model: "", no_key: true } }, default: "browser" } }, configs: [provider, stt] },
  "/api/admin/system-check/": { items: [{ group: "Email", key: "smtp", label: "SMTP", status: "warn", detail: "—", link: "/admin/email" }], summary: { ok: 1, warn: 1, error: 0, info: 0 } },
  "/api/admin/site/": { brand: "Aasan", legal_name: "", address: "", city: "", support_email: "", phone: "", grievance_officer: "", grievance_email: "", gstin: "", state: "", hsn_sac: "", refund_days: 7, terms_version: "1" },
  "/api/admin/features/": { podcast: false, explainer: true, listen: false, updated_at: "2026-10-10T10:00:00Z", updated_by: "staff@aasan.in" },
  "/api/admin/staff/": [{ id: 1, email: "staff@aasan.in", name: "", roles: ["superadmin"], superuser: false, last_login: null }],
  "/api/admin/audit/": { results: [{ id: 1, at: "2026-10-10T10:00:00Z", actor: "staff@aasan.in", method: "POST", path: "/api/admin/users/9/action/", section: "users", target: "9", data: { action: "deactivate" }, status: 200, ip: "127.0.0.1" }], count: 1, page: 1, pages: 1 },
  "/api/admin/model-prices/": [{ provider: "fake", model: "fake-1", input_per_m: null, output_per_m: null }],
  "/api/admin/overview/": overview,
});

/** Lets every query resolve and React settle. */
const settle = () => act(() => new Promise((r) => setTimeout(r, 30)));

const PAGES: [string, ComponentType, (() => Promise<void>)?][] = [
  ["Overview", AdminOverview],
  ["Users", AdminUsers, async () => { fireEvent.click(await screen.findByText("arun@school.in")); await screen.findByRole("dialog"); }],
  ["Orgs", AdminOrgs, async () => { fireEvent.click(await screen.findByText("Vidya")); await screen.findByRole("dialog"); }],
  ["Catalog", AdminCatalog],
  ["Certificates", AdminCertificates],
  ["Workshops", AdminWorkshops],
  ["Payments", AdminPayments],
  ["FamilyGroups", AdminFamilyGroups],
  ["Refunds", AdminRefunds, async () => {
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "buyer" } });
    fireEvent.submit(screen.getByRole("textbox").closest("form")!);
    fireEvent.click(await screen.findByText(/buyer@x.in/));
  }],
  ["Codes", AdminCodes],
  ["Support", AdminSupport, async () => { fireEvent.click(await screen.findByText("UPI")); }],
  ["SystemCheck", SystemCheck],
  ["Providers", AdminProviders],
  ["Features", AdminFeatures],
  ["CalendarApps", AdminCalendarApps],
  ["Email", AdminEmail],
  ["SiteLegal", SiteLegal],
  ["Staff", AdminStaff],
];

describe("admin console has no hardcoded English (every en.ts string is ✓)", () => {
  beforeAll(async () => {
    i18n.addResourceBundle("zz", "translation", tick(en) as Record<string, unknown>, true, true);
    await i18n.changeLanguage("zz");
  });
  afterAll(async () => {
    await i18n.changeLanguage("en");
  });
  beforeEach(() => {
    vi.mocked(api).mockReset();
    vi.mocked(api).mockImplementation(routes as never);
    useAuth.setState({ access: "token", signedIn: true });
  });
  afterEach(() => {
    useAuth.setState({ access: null, signedIn: false });
  });

  it.each(PAGES)("%s", async (_name, Page, more) => {
    const { container } = renderPage(<Page />);
    await waitFor(() => expect(api).toHaveBeenCalled());
    await settle();
    if (more) {
      await more();
      await settle();
    }
    expect(offenders(container)).toEqual([]);
    expect(container.textContent).toContain("✓"); // the fake language really is in use
  });

  it("layout (sidebar and section names)", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/admin/overview"]}>
          <Routes><Route path="/admin" element={<AdminLayout />}><Route path="overview" element={<p>✓</p>} /></Route></Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await screen.findByRole("navigation");
    expect(offenders(container)).toEqual([]);
    expect(screen.getAllByRole("link")).toHaveLength(19); // 18 sections + back to app
  });
});
