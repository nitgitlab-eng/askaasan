/** Pure helpers for the teacher tools and the learner's assignment badges (unit-tested). */
import { ApiError } from "@/lib/api";

export type DueState = "done" | "overdue" | "soon" | "later" | "none";
const DAY = 86_400_000;

export function dueState(a: { due_at: string | null; done: number; total: number }, now: number): DueState {
  if (a.total > 0 && a.done >= a.total) return "done";
  if (!a.due_at) return "none";
  const due = Date.parse(a.due_at);
  if (Number.isNaN(due)) return "none";
  if (due < now) return "overdue";
  return due - now <= 2 * DAY ? "soon" : "later";
}

/** Learner's list: unfinished first, mandatory before optional, overdue before upcoming, earliest due first. */
export function sortAssignments<T extends { due_at: string | null; done: number; total: number; mandatory: boolean }>(list: T[], now: number): T[] {
  const rank = (s: DueState) => ({ overdue: 0, soon: 1, later: 2, none: 3, done: 4 })[s];
  return [...list].sort((a, b) => {
    const sa = dueState(a, now), sb = dueState(b, now);
    if ((sa === "done") !== (sb === "done")) return sa === "done" ? 1 : -1;
    if (a.mandatory !== b.mandatory) return a.mandatory ? -1 : 1;
    if (rank(sa) !== rank(sb)) return rank(sa) - rank(sb);
    return (a.due_at ? Date.parse(a.due_at) : Infinity) - (b.due_at ? Date.parse(b.due_at) : Infinity);
  });
}

export function fmtDuration(secs: number | null | undefined): string {
  if (secs === null || secs === undefined) return "—";
  const m = Math.floor(secs / 60);
  return `${m}:${String(Math.floor(secs % 60)).padStart(2, "0")}`;
}

export const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`);

/** Signed percentage points from a 0..1 difference: 0.6 → "+60". */
export const points = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${Math.round(v * 100)}`);

/** Local YYYY-MM-DD (for <input type=date> and the report's range). */
export function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function defaultRange(now: Date, days = 90): { from: string; to: string } {
  const from = new Date(now);
  from.setDate(from.getDate() - (days - 1));
  return { from: isoDay(from), to: isoDay(now) };
}

export function validRange(from: string, to: string): boolean {
  const a = Date.parse(from), b = Date.parse(to);
  return !Number.isNaN(a) && !Number.isNaN(b) && a <= b && b - a <= 366 * DAY;
}

/** Friendly message for a failed teacher-tools call (AI allowance, nothing to analyse, other teacher's class). */
export function aiError(t: (k: string) => string, e: unknown): string {
  const code = e instanceof ApiError ? e.data?.code : "";
  if (code === "budget_exceeded") return t("teach.err.budget");
  if (code === "no_attempts") return t("teach.err.noAttempts");
  if (code === "no_wrong_answers") return t("teach.err.noWrong");
  if (e instanceof ApiError && e.status === 403) return t("teach.err.forbidden");
  return t("mentor.errors.generic");
}

export type CellTone = "none" | "low" | "mid" | "pass";

/** Heat-map tone for one learner × concept cell (paired with text — colour is never the only signal). */
export function cellTone(level: number | null | undefined, max: number, pass: number): CellTone {
  if (level === null || level === undefined) return "none";
  if (level >= pass) return "pass";
  return level * 2 >= max ? "mid" : "low";
}

/** Visible cell text: "—" (not tried), "2/3", "3/3 ✓" (reached). */
export function cellText(level: number | null | undefined, max: number, passed: boolean): string {
  if (level === null || level === undefined) return "—";
  return `${level}/${max}${passed ? " ✓" : ""}`;
}
