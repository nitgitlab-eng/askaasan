import { api } from "./api";

/** Connect Claude: org admins connect an AI assistant (remote MCP server + OAuth) to one organisation. */

export interface ConnectOrg {
  slug: string;
  name: string;
  role: "admin" | "owner";
}

export interface ConnectMe {
  server_url: string;
  orgs: ConnectOrg[];
  tools: { name: string; title: string }[];
}

export interface ConnectedClient {
  id: number;
  client_name: string;
  redirect_hosts: string[];
  approved_by: string;
  mine: boolean;
  created_at: string;
  last_used_at: string | null;
  calls: number;
}

export interface AuditRow {
  id: number;
  /** "tool" for an MCP tool call; otherwise a connection event (approve, deny, code_exchange, revoke, …). */
  event: string;
  client_name: string;
  user: string;
  tool: string;
  args: string;
  ok: boolean;
  error: string;
  created_at: string;
}

export interface AuditPage {
  total: number;
  page: number;
  pages: number;
  rows: AuditRow[];
}

export interface ConsentInfo {
  /** name_mismatch: the app says it is Claude (or similar) but redirects to a host that isn't. */
  client: { name: string; redirect_host: string; redirect_uri: string; registered_at: string; new: boolean; name_mismatch?: boolean };
  scope: string;
  orgs: ConnectOrg[];
}

/** The OAuth query parameters the consent screen passes through to the API (nothing else). */
export const AUTH_PARAMS = ["response_type", "client_id", "redirect_uri", "code_challenge", "code_challenge_method", "scope", "state", "resource"] as const;

export function authParams(search: string): Record<string, string> {
  const q = new URLSearchParams(search);
  const out: Record<string, string> = {};
  for (const k of AUTH_PARAMS) {
    const v = q.get(k);
    if (v !== null) out[k] = v;
  }
  return out;
}

/** Only follow redirects to the kinds of URIs the server accepts at registration (https or loopback http). */
export function safeRedirect(url: unknown): string | null {
  if (typeof url !== "string") return null;
  let u: URL;
  try {
    u = new URL(url);
  } catch {
    return null;
  }
  if (u.username || u.password) return null;
  if (u.protocol === "https:") return u.toString();
  if (u.protocol === "http:" && (u.hostname === "localhost" || u.hostname === "127.0.0.1")) return u.toString();
  return null;
}

/** "3 hours ago" / "2 days ago" in the reader's language. */
export function relativeAge(iso: string, locale: string, now: number = Date.now()): string {
  const secs = Math.round((new Date(iso).getTime() - now) / 1000);
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [["year", 31536000], ["month", 2592000], ["day", 86400], ["hour", 3600], ["minute", 60]];
  for (const [unit, size] of steps) if (Math.abs(secs) >= size) return rtf.format(Math.round(secs / size), unit);
  return rtf.format(secs, "second");
}

export const connect = {
  me: () => api<ConnectMe>("/api/connect/me/"),
  clients: (slug: string) => api<ConnectedClient[]>(`/api/connect/orgs/${encodeURIComponent(slug)}/clients/`),
  revoke: (slug: string, id: number) => api<void>(`/api/connect/orgs/${encodeURIComponent(slug)}/clients/${id}/`, { method: "DELETE" }),
  audit: (slug: string, page: number) => api<AuditPage>(`/api/connect/orgs/${encodeURIComponent(slug)}/audit/?page=${page}`),
  consentInfo: (params: Record<string, string>) => api<ConsentInfo>(`/api/connect/authorize/?${new URLSearchParams(params).toString()}`),
  decide: (params: Record<string, string>, decision: "approve" | "deny", org?: string) =>
    api<{ redirect: string }>("/api/connect/authorize/", { method: "POST", json: { ...params, decision, org: org ?? "" } }),
};
