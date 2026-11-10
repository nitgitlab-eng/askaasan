import { api } from "./api";

export type CalendarProvider = "google" | "microsoft";
export interface CalendarProviderStatus {
  provider: CalendarProvider; label: string; configured: boolean; connected: boolean;
  connected_at: string | null; last_synced_at: string | null; needs_reconnect: boolean;
}
export interface CalendarStatus { providers: CalendarProviderStatus[]; horizon_days: number; read_only: true }
export interface ReplanResult extends CalendarStatus { moved: number; kept: number; unplaced: number; busy: number; needs_reconnect: CalendarProvider[]; synced_at: string }

export const calendar = {
  status: () => api<CalendarStatus>("/api/calendar/"),
  connect: (p: CalendarProvider) => api<{ url: string }>(`/api/calendar/${p}/connect/`, { method: "POST" }),
  callback: (p: CalendarProvider, code: string, state: string) => api<CalendarStatus>(`/api/calendar/${p}/callback/`, { method: "POST", json: { code, state } }),
  disconnect: (p: CalendarProvider) => api<CalendarStatus>(`/api/calendar/${p}/`, { method: "DELETE" }),
  replan: () => api<ReplanResult>("/api/calendar/replan/", { method: "POST" }),
};

export const isProvider = (p: string | undefined): p is CalendarProvider => p === "google" || p === "microsoft";

/** What the provider sent back to /calendar/callback/:provider. */
export type CallbackParams = { kind: "ok"; code: string; state: string } | { kind: "denied" } | { kind: "invalid" };
export function parseCallback(search: string): CallbackParams {
  const q = new URLSearchParams(search);
  if (q.get("error")) return { kind: "denied" };
  const code = q.get("code") ?? "", state = q.get("state") ?? "";
  if (!code || !state || code.length > 2048 || state.length > 1024) return { kind: "invalid" };
  return { kind: "ok", code, state };
}

/** Which message to show after a re-plan. */
export function replanSummary(r: Pick<ReplanResult, "moved" | "unplaced" | "needs_reconnect">): "reconnect" | "unplaced" | "moved" | "nochange" {
  if (r.needs_reconnect.length) return "reconnect";
  if (r.unplaced) return "unplaced";
  return r.moved ? "moved" : "nochange";
}
