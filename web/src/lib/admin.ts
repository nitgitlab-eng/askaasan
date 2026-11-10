/** Admin console helpers: paged lists, role-based sections, and fetching a PDF preview from a POST. */
import { refreshTokens } from "./api";
import { useAuth } from "@/stores/auth";

export type StaffRole = "superadmin" | "support" | "finance" | "content";

export interface Paged<T> {
  results: T[];
  count: number;
  page: number;
  pages: number;
}

/** Which roles see each console section (superadmin sees everything). Mirrors apps/accounts/staff.py SECTION_ROLES;
 * the server enforces it, this only hides what would answer 403. */
export const SECTION_ROLES: Record<string, StaffRole[]> = {
  overview: ["support", "finance", "content"],
  system: [],
  providers: [],
  features: ["content"],
  users: ["support", "finance"],
  orgs: ["support", "finance"],
  catalog: ["content"],
  certificates: ["content", "support"],
  payments: ["finance"],
  refunds: ["finance"],
  families: ["finance", "support"],
  gifts: ["finance"],
  codes: ["finance"],
  "calendar-apps": [],
  workshops: ["content"],
  support: ["support"],
  email: [],
  site: [],
  staff: [],
};

export function canSee(roles: string[] | undefined, section: string): boolean {
  if (!roles?.length) return false;
  if (roles.includes("superadmin")) return true;
  return (SECTION_ROLES[section] ?? []).some((r) => roles.includes(r));
}

export function query(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

/** POST json → a PDF blob URL (certificate previews). */
export async function postPdf(url: string, json: unknown): Promise<string> {
  const send = () =>
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${useAuth.getState().access ?? ""}` },
      body: JSON.stringify(json),
    });
  let res = await send();
  if (res.status === 401 && (await refreshTokens())) res = await send();
  if (!res.ok) throw new Error(`preview_failed_${res.status}`);
  return URL.createObjectURL(await res.blob());
}

export const date = (d: string | null | undefined) =>
  d ? new Date(d).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "—";
