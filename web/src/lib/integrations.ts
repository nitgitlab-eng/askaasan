import { api } from "./api";

export type ApiScope = "read:progress" | "read:members" | "write:members";
export type HookEvent = "member.joined" | "assignment.completed" | "course.completed" | "certificate.issued" | "workshop.passed";

export interface ApiKey {
  id: number; name: string; prefix: string; scopes: ApiScope[]; created_at: string; created_by: string | null;
  last_used_at: string | null; revoked_at: string | null;
  /** Only in the create response: shown once, never again. */
  key?: string;
}
export interface Webhook {
  id: number; url: string; events: HookEvent[]; active: boolean; failures: number; disabled_reason: string; created_at: string;
  last_delivery: { status: DeliveryStatus; event: string; at: string } | null;
  /** Only when created or rotated. */
  secret?: string;
}
export type DeliveryStatus = "pending" | "ok" | "failed" | "dead";
export interface Delivery {
  id: number; event: string; status: DeliveryStatus; attempt: number; response_status: number | null; last_error: string;
  next_try_at: string | null; created_at: string; delivered_at: string | null;
}
export interface Page<T> { results: T[]; count: number; page: number; pages: number }

const base = (slug: string) => `/api/orgs/${slug}/integrations`;

export const integrations = {
  keys: (slug: string) => api<{ keys: ApiKey[]; scopes: ApiScope[] }>(`${base(slug)}/keys/`),
  createKey: (slug: string, name: string, scopes: ApiScope[]) => api<ApiKey>(`${base(slug)}/keys/`, { method: "POST", json: { name, scopes } }),
  revokeKey: (slug: string, id: number) => api<null>(`${base(slug)}/keys/${id}/`, { method: "DELETE" }),
  webhooks: (slug: string) => api<{ webhooks: Webhook[]; events: HookEvent[] }>(`${base(slug)}/webhooks/`),
  createWebhook: (slug: string, url: string, events: HookEvent[]) => api<Webhook>(`${base(slug)}/webhooks/`, { method: "POST", json: { url, events } }),
  updateWebhook: (slug: string, id: number, patch: Partial<Pick<Webhook, "url" | "events" | "active">>) =>
    api<Webhook>(`${base(slug)}/webhooks/${id}/`, { method: "PATCH", json: patch }),
  deleteWebhook: (slug: string, id: number) => api<null>(`${base(slug)}/webhooks/${id}/`, { method: "DELETE" }),
  rotateSecret: (slug: string, id: number) => api<Webhook>(`${base(slug)}/webhooks/${id}/rotate-secret/`, { method: "POST" }),
  test: (slug: string, id: number) => api<Delivery>(`${base(slug)}/webhooks/${id}/test/`, { method: "POST" }),
  deliveries: (slug: string, id: number, page = 1) => api<Page<Delivery>>(`${base(slug)}/webhooks/${id}/deliveries/?page=${page}`),
  redeliver: (slug: string, id: number, did: number) => api<Delivery>(`${base(slug)}/webhooks/${id}/deliveries/${did}/redeliver/`, { method: "POST" }),
};
