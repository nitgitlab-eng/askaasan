import { api } from "./api";

export const LESSON_LANGS = ["en", "ta", "hi", "te", "kn", "ml", "bn", "mr", "gu"] as const;
export const LANG_NAMES: Record<string, string> = {
  en: "English", ta: "தமிழ்", hi: "हिन्दी", te: "తెలుగు", kn: "ಕನ್ನಡ", ml: "മലയാളം", bn: "বাংলা", mr: "मराठी", gu: "ગુજરાતી", tanglish: "Tanglish",
};

export type StationKind = "review" | "weak" | "quiz" | "roleplay" | "lesson" | "exam";
/** key is the station kind, plus "@2", "@3"… for extra circuits. */
export interface Station { key: string; kind: string; title: string; link: string; minutes: number; done: boolean; round?: number;
  n?: number; pct?: number; course?: string; emoji?: string; alts?: number }
export interface Tier { points: number; level: number; key: string; next: string | null; next_at: number | null; tiers: { key: string; at: number }[] }
export interface Today { day: string; focus: string; stations: Station[]; done: number; total: number; swaps_left: number;
  circuits: number; can_add_circuit: boolean; tier: Tier;
  themes: { slug: string; name: string; name_ta: string }[]; reward?: unknown }
export const baseKey = (key: string) => key.split("@")[0] as StationKind;
export interface BoardRow { rank: number; name: string; score: number; reviews: number; stations: number; me: boolean }
export interface Block { id: number; date: string; start: string; minutes: number; kind: string; title: string; link: string;
  status: "planned" | "done" | "skipped"; state: "planned" | "done" | "skipped" | "missed"; moved_from: string | null; auto: boolean }
export interface Pause { id: number; start: string; end: string; reason: string; active?: boolean }
export interface Week { start: string; days: { day: string; paused: boolean; studied: boolean }[]; blocks: Block[]; pauses: Pause[]; moved_to?: string | null }
export interface Buddy { id: number; name: string; streak: number; last_active: string | null; planned: number; done: number; studied_days: string[]; paused: boolean }
export interface Point { label: string; value: number }
export interface Progress {
  days: number;
  totals: { minutes: number; xp: number; sessions: number; active_days: number; streak: number; best_streak: number; lessons: number; first_try_accuracy: number | null };
  minutes: Point[]; xp: Point[]; by_weekday: Point[];
  efficiency: { type: string; attempts: number; accuracy: number }[];
  skills: { slug: string; name: string; name_ta: string; mastery: number | null; usage: number; followed: boolean }[];
  graph: { nodes: { id: string; label: string; type: "skill" | "lesson"; mastery: number | null; link?: string }[]; edges: { from: string; to: string }[] };
}
export interface Insights { headline: string; strengths: string[]; focus: string[]; summary: string; week: string; cached: boolean }
export type AskResult = { supported: false; note: string } | { supported: true; title: string; metric: string; group_by: string; days: number; chart: "bar" | "line" | "hbar"; data: Point[]; unit: string; note: string };

export const study = {
  hint: (activityId: number, level: number, lang?: string) =>
    api<{ level: number; text: string; cost: number; coins: number; next_cost: number | null }>(`/api/study/activities/${activityId}/hint/`, { method: "POST", json: { level, lang } }),
  hintsUsed: (activityId: number) => api<{ used: number[]; costs: Record<string, number> }>(`/api/study/activities/${activityId}/hints/`),
  explain: (text: string, subsection_id: number, lang?: string) => api<{ text: string }>("/api/study/explain/", { method: "POST", json: { text, subsection_id, lang } }),
  today: () => api<Today>("/api/study/today/"),
  focus: (focus: string) => api<Today>("/api/study/today/focus/", { method: "POST", json: { focus } }),
  swap: (key: string) => api<Today>("/api/study/today/swap/", { method: "POST", json: { key } }),
  done: (key: string) => api<Today>("/api/study/today/done/", { method: "POST", json: { key } }),
  circuit: () => api<Today>("/api/study/today/circuit/", { method: "POST" }),
  board: () => api<{ rows: BoardRow[]; me: BoardRow | null; visible: boolean }>("/api/study/revision-board/"),
  week: (week?: string) => api<Week>(`/api/study/blocks/${week ? `?week=${week}` : ""}`),
  addBlock: (b: { date: string; start: string; minutes: number; title: string }) => api<Week>("/api/study/blocks/", { method: "POST", json: b }),
  blockAction: (id: number, action: "skip" | "done" | "undo" | "move" | "delete", extra: { date?: string; start?: string } = {}) =>
    api<Week>(`/api/study/blocks/${id}/`, { method: "POST", json: { action, ...extra } }),
  pauses: () => api<Pause[]>("/api/study/pauses/"),
  addPause: (p: { start: string; end: string; reason: string }) => api<Pause[]>("/api/study/pauses/", { method: "POST", json: p }),
  removePause: (id: number) => api(`/api/study/pauses/${id}/`, { method: "DELETE" }),
  buddies: () => api<{ buddies: Buddy[]; pending: { id: number; link: string; created_at: string }[] }>("/api/study/buddies/"),
  invite: () => api<{ buddies: Buddy[]; pending: { id: number; link: string; created_at: string }[] }>("/api/study/buddies/", { method: "POST" }),
  removeBuddy: (id: number) => api(`/api/study/buddies/${id}/`, { method: "DELETE" }),
  invitation: (token: string) => api<{ inviter: string; accepted: boolean; self: boolean }>(`/api/study/buddy/${token}/`),
  acceptBuddy: (token: string) => api<{ ok: boolean }>(`/api/study/buddy/${token}/`, { method: "POST" }),
  progress: (days: number) => api<Progress>(`/api/study/progress/?days=${days}`),
  insights: () => api<Insights>("/api/study/progress/insights/", { method: "POST" }),
  ask: (question: string) => api<AskResult>("/api/study/progress/ask/", { method: "POST", json: { question } }),
};

/** Local date as YYYY-MM-DD (not UTC). */
export const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export const addDays = (iso: string, n: number) => {
  const [y, m, d] = iso.split("-").map(Number);
  return isoDay(new Date(y, m - 1, d + n));
};
