import { useAuth } from "@/stores/auth";

export class ApiError extends Error {
  status: number;
  data: Record<string, unknown> | null;

  constructor(status: number, data: Record<string, unknown> | null) {
    super((data?.detail as string) || `HTTP ${status}`);
    this.status = status;
    this.data = data;
  }
}

/**
 * New access token from the HttpOnly refresh cookie (the browser sends it; JS never sees it).
 * Refresh tokens rotate and are single-use, so concurrent refreshes would race and log the user
 * out: calls share one in-flight request per tab, and a Web Lock serialises them across tabs
 * (the cookie is shared, so a waiting tab sends the already-rotated token).
 */
export async function refreshTokens(): Promise<boolean> {
  return (await refreshOutcome()) === "ok";
}

export const SESSION_ENDED = "aasan:session-ended";

type RefreshOutcome = "ok" | "rejected" | "unavailable";
let refreshingOutcome: Promise<RefreshOutcome> | null = null;

function refreshOutcome(): Promise<RefreshOutcome> {
  refreshingOutcome ??= (navigator.locks ? navigator.locks.request("aasan-refresh", doRefresh) : doRefresh()).finally(() => (refreshingOutcome = null));
  return refreshingOutcome;
}

/**
 * Only a definite "no" from the server (401/403/400) ends the session. A network error or 5xx
 * (deploy, flaky mobile data) keeps the learner signed in so the next try can succeed.
 */
async function doRefresh(): Promise<RefreshOutcome> {
  const { legacyRefresh, setAccess, clear } = useAuth.getState();
  let res: Response;
  try {
    res = await fetch("/api/users/refresh-token/", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      // One-time migration for browsers that stored the refresh token before it moved into a cookie.
      body: legacyRefresh ? JSON.stringify({ refresh: legacyRefresh }) : undefined,
    });
  } catch {
    return "unavailable";
  }
  if (res.status === 401 || res.status === 403 || res.status === 400) {
    clear();
    window.dispatchEvent(new Event(SESSION_ENDED)); // offline copies belong to that session — drop them too
    return "rejected";
  }
  if (!res.ok) return "unavailable";
  const data = await res.json().catch(() => null);
  if (!data?.access) return "unavailable";
  setAccess(data.access);
  return "ok";
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** On page load: restore the session silently if this browser was signed in (retrying brief outages). */
export async function bootAuth(retryDelays = [800, 1500, 3000, 5000]) {
  const s = useAuth.getState();
  if (!s.access && s.signedIn) {
    for (let i = 0; ; i++) {
      const r = await refreshOutcome();
      if (r !== "unavailable" || i >= retryDelays.length) break;
      await sleep(retryDelays[i]);
    }
  }
  useAuth.getState().markReady();
}

/** fetch wrapper: JSON in/out, bearer auth, one transparent refresh on 401. */
export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}, retry = true): Promise<T> {
  const { access } = useAuth.getState();
  const headers = new Headers(init.headers);
  if (init.json !== undefined) headers.set("Content-Type", "application/json");
  if (access) headers.set("Authorization", `Bearer ${access}`);
  const res = await fetch(path, {
    ...init,
    headers,
    body: init.json !== undefined ? JSON.stringify(init.json) : init.body,
  });
  if (res.status === 401 && retry && (access || useAuth.getState().signedIn)) {
    if (await refreshTokens()) return api<T>(path, init, false);
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  // Admin changes need a recent sign-in: prove it once in the re-auth dialog, then send the change again.
  if (res.status === 403 && data?.code === "reauth_required" && retry && path.startsWith("/api/admin/")) {
    const { reauthenticate } = await import("./auth");
    if (await reauthenticate((data.methods as string[]) ?? [])) return api<T>(path, init, false);
  }
  if (res.status === 402 && data?.code === "plan_limit") {
    const { announcePlanLimit } = await import("./billing");
    announcePlanLimit(data as never);
  }
  if (!res.ok) throw new ApiError(res.status, data);
  return data as T;
}

export async function ensureFreshAccess(): Promise<string | null> {
  // Probe cheaply; api() refreshes on 401 for us.
  try {
    await api("/api/users/me/");
  } catch {
    /* handled by caller via auth state */
  }
  return useAuth.getState().access;
}
