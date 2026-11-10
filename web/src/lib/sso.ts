import { api } from "./api";
import type { AuthPayload } from "./types";

export type SsoProvider = "google" | "microsoft";

export interface SsoDomain {
  id: number; domain: string; verified: boolean; verified_at: string | null; last_checked_at: string | null; failing_since: string | null;
  txt_name: string; txt_alt_name: string; txt_value: string;
}
export interface SsoConfig {
  provider: SsoProvider; client_id: string;
  /** Masked (last 4 characters) when one is saved; the secret itself is write-only. */
  client_secret: string | null;
  tenant_id: string; hosted_domains: string[]; default_role: "learner" | "manager"; default_group_id: number | null;
  enabled: boolean; enforced: boolean; redirect_uri: string; domains: SsoDomain[];
}
export type SsoPatch = Partial<Omit<SsoConfig, "client_secret" | "redirect_uri" | "domains">> & { client_secret?: string };

export const sso = {
  lookup: (email: string) => api<{ sso: boolean; provider?: SsoProvider; org?: string; enforced?: boolean }>("/api/users/sso/lookup/", { method: "POST", json: { email } }),
  start: (email: string) => api<{ url: string }>("/api/users/sso/start/", { method: "POST", json: { email } }),
  callback: (code: string, state: string, language?: string) =>
    api<AuthPayload & { created?: boolean; org?: string }>("/api/users/sso/callback/", { method: "POST", json: { code, state, language } }),
  config: (slug: string) => api<SsoConfig>(`/api/orgs/${slug}/sso/`),
  save: (slug: string, patch: SsoPatch) => api<SsoConfig>(`/api/orgs/${slug}/sso/`, { method: "PUT", json: patch }),
  addDomain: (slug: string, domain: string) => api<SsoDomain>(`/api/orgs/${slug}/sso/domains/`, { method: "POST", json: { domain } }),
  removeDomain: (slug: string, id: number) => api<null>(`/api/orgs/${slug}/sso/domains/${id}/`, { method: "DELETE" }),
  verifyDomain: (slug: string, id: number) => api<SsoDomain>(`/api/orgs/${slug}/sso/domains/${id}/verify/`, { method: "POST" }),
};

/** Does any organisation on this server sign in with SSO? (public auth-config; false when it can't be read) */
export async function ssoAvailable(): Promise<boolean> {
  try {
    const r = await api<{ sso?: boolean }>("/api/users/auth-config/");
    return !!r?.sso;
  } catch {
    return false;
  }
}

/** Only provider sign-in pages may receive the browser (the server builds the URL; this is a second guard). */
export function isProviderUrl(url: string): boolean {
  try {
    const u = new URL(url);
    return u.protocol === "https:" && (u.hostname === "accounts.google.com" || u.hostname === "login.microsoftonline.com");
  } catch {
    return false;
  }
}
