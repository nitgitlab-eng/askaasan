import { api } from "./api";
import { refreshTokens } from "./api";
import { useAuth } from "@/stores/auth";

export type LinkState = "ok" | "inactive" | "expired" | "full" | "no_target";

export interface GuestLink {
  id: number;
  label: string;
  slug: string;
  url: string;
  target_kind: "course" | "roleplay";
  course: { id: number; title: string } | null;
  scenario: { id: number; title: string } | null;
  max_uses: number | null;
  expires_at: string | null;
  active: boolean;
  collect_email: boolean;
  org: string | null;
  state: LinkState;
  uses: number;
  opens: number;
  created_at: string;
}

export interface LinkStats {
  opens: number;
  starts: number;
  completions: number;
  emails: number;
  signups: number;
  conversion: number | null;
  daily: { day: string; starts: number }[];
}

export interface Targets {
  courses: { id: number; title: string }[];
  scenarios: { id: number; title: string; emoji: string }[];
  orgs: { slug: string; name: string }[];
}

export interface LinkInput {
  label: string;
  slug?: string;
  target_kind: "course" | "roleplay";
  course_id?: number | null;
  scenario_id?: number | null;
  max_uses?: number | null;
  expires_at?: string | null;
  active?: boolean;
  collect_email?: boolean;
  org?: string | null;
}

export interface Prospect {
  id: number;
  company: string;
  email: string;
  industry: string;
  status: "pending" | "generating" | "ready" | "failed" | "sent";
  error: string;
  subject: string;
  body: string;
  sent_at: string | null;
  course_id: number | null;
  link: { id: number; slug: string; url: string; uses: number; signups: number } | null;
  send_subject?: string;
  send_body?: string;
}

export interface Campaign {
  id: number;
  name: string;
  topic: string;
  language: string;
  created_at: string;
  prospects_count: number;
  sent: number;
  prospects?: Prospect[];
  sends_today?: number;
  sends_per_day?: number;
  errors?: string[];
}

export const guests = {
  links: (q: { org?: string; course?: number } = {}) => {
    const p = new URLSearchParams();
    if (q.org) p.set("org", q.org);
    if (q.course) p.set("course", String(q.course));
    return api<GuestLink[]>(`/api/guests/links/?${p}`);
  },
  create: (d: LinkInput) => api<GuestLink>("/api/guests/links/", { method: "POST", json: d }),
  update: (id: number, d: Partial<LinkInput>) => api<GuestLink>(`/api/guests/links/${id}/`, { method: "PATCH", json: d }),
  remove: (id: number) => api(`/api/guests/links/${id}/`, { method: "DELETE" }),
  stats: (id: number) => api<LinkStats>(`/api/guests/links/${id}/stats/`),
  targets: () => api<Targets>("/api/guests/targets/"),
  qrUrl: (id: number, as: "svg" | "png") => `/api/guests/links/${id}/qr/?as=${as}`,
  csvUrl: (id: number) => `/api/guests/links/${id}/export.csv`,
  campaigns: (org: string) => api<Campaign[]>(`/api/guests/orgs/${org}/campaigns/`),
  createCampaign: (org: string, d: { name: string; topic: string; language: string; prospects: string }) =>
    api<Campaign>(`/api/guests/orgs/${org}/campaigns/`, { method: "POST", json: d }),
  campaign: (id: number) => api<Campaign>(`/api/guests/campaigns/${id}/`),
  removeCampaign: (id: number) => api(`/api/guests/campaigns/${id}/`, { method: "DELETE" }),
  editProspect: (id: number, d: { subject?: string; body?: string }) => api<Prospect>(`/api/guests/prospects/${id}/`, { method: "PATCH", json: d }),
  removeProspect: (id: number) => api(`/api/guests/prospects/${id}/`, { method: "DELETE" }),
  regenerate: (id: number) => api<Prospect>(`/api/guests/prospects/${id}/regenerate/`, { method: "POST" }),
  send: (id: number) => api<Prospect>(`/api/guests/prospects/${id}/send/`, { method: "POST" }),
  sendAll: (id: number) => api<{ sent: number[]; skipped: Record<string, string>; campaign: Campaign }>(`/api/guests/campaigns/${id}/send-all/`, { method: "POST", json: { confirm: true } }),
};

/** Fetch a permission-checked file (e.g. the QR SVG) as an object URL for previews. Caller revokes it. */
export async function authBlobUrl(url: string): Promise<string> {
  const get = () => fetch(url, { headers: { Authorization: `Bearer ${useAuth.getState().access ?? ""}` } });
  let res = await get();
  if (res.status === 401 && (await refreshTokens())) res = await get();
  if (!res.ok) throw new Error(`fetch_failed_${res.status}`);
  return URL.createObjectURL(await res.blob());
}

// ── Public guest side ────────────────────────────────────────────────

export interface GuestMe {
  name: string;
  has_email: boolean;
  lessons_done: number[];
  completed: boolean;
  claimed: boolean;
}

export interface GuestLanding {
  slug: string;
  label: string;
  state: LinkState;
  collect_email: boolean;
  brand: { name: string; color: string; logo_url: string } | null;
  target: {
    kind: "course" | "roleplay";
    title: string;
    description: string;
    cover_emoji: string;
    lessons?: { id: number; title: string }[];
    learner_role?: string;
    character?: string;
    objectives?: string[];
  } | null;
  me: GuestMe | null;
}

export interface GuestRolePlay {
  id: number;
  status: "active" | "completed";
  turns: { role: "learner" | "character"; text: string }[];
  turns_left: number;
  result: { overall: number; summary: string; strengths: string[]; improvements: string[] } | null;
  scenario: { title: string; emoji: string; summary: string; learner_role: string; setting: string; character: { name: string; persona: string }; objectives: string[] };
}

const KEY = "aasan-guest-tokens";

/** Guest tokens live in this browser only, one per link slug. Storage may be blocked: then the visit lasts this tab. */
const memory: Record<string, string> = {};

function readAll(): Record<string, string> {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "{}");
    return v && typeof v === "object" ? v : {};
  } catch {
    return { ...memory };
  }
}

/** Forget every guest visit in this browser (sign-out / account deletion: the next person on this device starts fresh). */
export function clearGuestTokens() {
  for (const k of Object.keys(memory)) delete memory[k];
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* storage blocked */
  }
}

export const guestToken = {
  get(slug: string): string | null {
    return readAll()[slug] ?? memory[slug] ?? null;
  },
  set(slug: string, token: string) {
    memory[slug] = token;
    try {
      localStorage.setItem(KEY, JSON.stringify({ ...readAll(), [slug]: token }));
    } catch {
      /* private mode: memory only */
    }
  },
  clear(slug: string) {
    delete memory[slug];
    try {
      const all = readAll();
      delete all[slug];
      localStorage.setItem(KEY, JSON.stringify(all));
    } catch {
      /* ignore */
    }
  },
};

export function guestHeaders(slug: string): Record<string, string> {
  const t = guestToken.get(slug);
  return t ? { "X-Guest-Token": t } : {};
}

export const pub = {
  landing: (slug: string) => api<GuestLanding>(`/api/guests/public/${slug}/`, { headers: guestHeaders(slug) }),
  start: (slug: string, d: { name?: string; email?: string }) =>
    api<{ token?: string; me: GuestMe; code?: string }>(`/api/guests/public/${slug}/start/`, { method: "POST", json: d, headers: guestHeaders(slug) }),
  resume: (slug: string, magic: string) => api<{ token: string; me: GuestMe }>(`/api/guests/public/${slug}/resume/`, { method: "POST", json: { magic } }),
  emailLink: (slug: string) => api(`/api/guests/public/${slug}/email-link/`, { method: "POST", headers: guestHeaders(slug) }),
  lesson: (slug: string, id: number) => api<{
    id: number; title: string; objective: string; explanation_md: string; key_points: string[]; next_id: number | null; position: number; total: number;
    activities: { id: number; type: string; title: string; payload: Record<string, unknown>; attempt: unknown; locked: boolean }[];
  }>(`/api/guests/public/${slug}/lesson/${id}/`, { headers: guestHeaders(slug) }),
  lessonDone: (slug: string, id: number) => api(`/api/guests/public/${slug}/lesson/${id}/done/`, { method: "POST", headers: guestHeaders(slug) }),
  finish: (slug: string) => api(`/api/guests/public/${slug}/finish/`, { method: "POST", headers: guestHeaders(slug) }),
  summary: (slug: string) => api<{ me: GuestMe; target: GuestLanding["target"]; brand: GuestLanding["brand"]; answers: number; correct: number; avg_score: number | null; roleplay: { overall: number; summary: string } | null }>(
    `/api/guests/public/${slug}/summary/`, { headers: guestHeaders(slug) }),
  roleplay: (slug: string) => api<GuestRolePlay | null>(`/api/guests/public/${slug}/role-play/`, { headers: guestHeaders(slug) }),
  startRoleplay: (slug: string, again = false) => api<GuestRolePlay>(`/api/guests/public/${slug}/role-play/`, { method: "POST", json: { again }, headers: guestHeaders(slug) }),
  say: (slug: string, text: string) => api<GuestRolePlay>(`/api/guests/public/${slug}/role-play/say/`, { method: "POST", json: { text }, headers: guestHeaders(slug) }),
  endRoleplay: (slug: string) => api<GuestRolePlay>(`/api/guests/public/${slug}/role-play/end/`, { method: "POST", headers: guestHeaders(slug) }),
  claim: (slug: string) => api<{ course_id: number | null; attempts: number; lessons: number; roleplays: number }>(
    "/api/guests/claim/", { method: "POST", json: { slug }, headers: guestHeaders(slug) }),
};

// ── Pure helpers (unit-tested) ───────────────────────────────────────

const EMAIL = /^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+$/;

/** Client-side preview of pasted prospects: "company, email[, industry]" per line; header line and duplicates skipped. */
export function parseProspects(text: string): { rows: { company: string; email: string; industry: string }[]; bad: number } {
  const rows: { company: string; email: string; industry: string }[] = [];
  const seen = new Set<string>();
  let bad = 0;
  text.split(/\r?\n/).forEach((line, i) => {
    const cells = splitCsvLine(line).map((c) => c.trim());
    if (!cells.some(Boolean)) return;
    if (i === 0 && /^(e-?mail|contact( email)?)$/i.test(cells[1] ?? "")) return;
    const [company = "", email = "", industry = ""] = cells;
    const e = email.toLowerCase();
    if (!company || !EMAIL.test(e)) {
      bad++;
      return;
    }
    if (seen.has(e)) return;
    seen.add(e);
    rows.push({ company, email: e, industry });
  });
  return { rows, bad };
}

/** Minimal CSV field splitter: commas, double-quoted fields with "" escapes. */
export function splitCsvLine(line: string): string[] {
  const out: string[] = [];
  let cur = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (quoted) {
      if (ch === '"' && line[i + 1] === '"') {
        cur += '"';
        i++;
      } else if (ch === '"') quoted = false;
      else cur += ch;
    } else if (ch === '"' && cur === "") quoted = true;
    else if (ch === ",") {
      out.push(cur);
      cur = "";
    } else cur += ch;
  }
  out.push(cur);
  return out;
}

/** Days-from-now → ISO timestamp for the expiry picker (null = never). */
export function expiryFromDays(days: number | null, now = new Date()): string | null {
  if (!days || days <= 0) return null;
  return new Date(now.getTime() + days * 86400000).toISOString();
}

/** A slug the server will accept: lowercase letters, digits, inner hyphens, 4-48 chars. */
export function validSlug(s: string): boolean {
  return /^[a-z0-9](?:[a-z0-9-]{2,46}[a-z0-9])$/.test(s);
}

export function copyText(text: string) {
  void navigator.clipboard?.writeText(text).catch(() => undefined);
}
