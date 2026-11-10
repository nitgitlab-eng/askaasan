import { localeOf } from "@/i18n/languages";

import { api } from "./api";

export type ItemKind = "lesson" | "scenario" | "shadow" | "document" | "note";
export const ITEM_KINDS: ItemKind[] = ["lesson", "scenario", "shadow", "document", "note"];

export interface Phase { title: string; start_day: number; end_day: number }
export interface PhaseStatus extends Phase { status: "done" | "upcoming" | "active" | "behind"; done: number; total: number }

export interface JourneyItem {
  id: number; day: number; order: number; kind: ItemKind; title: string; notes: string;
  course: { id: number; title: string; emoji: string } | null;
  lesson: { id: number; title: string } | null;
  scenario: { id: number; title: string; emoji: string } | null;
  document: { id: number; document_id: number | null; title: string } | null;
  colleague_name: string; colleague_role: string;
}
export interface LearnerItem extends JourneyItem { link: string; due_date: string; done: boolean; overdue: boolean; auto: boolean; unavailable?: boolean }

export interface JourneyStatus {
  day: number; length_days: number; started: boolean; ended: boolean; done: number; total: number; overdue: number;
  finished: boolean; stuck: boolean; phase: number | null; phases: PhaseStatus[];
}

export interface MyJourney {
  id: number; org: string; start_date: string; status: JourneyStatus;
  journey: { id: number; name: string; description: string; length_days: number; phases: Phase[] };
  today?: LearnerItem[]; items?: LearnerItem[];
}

export interface Journey {
  id: number; name: string; description: string; length_days: number; phases: Phase[]; items_n: number; assignees_n: number;
  updated_at: string; items?: JourneyItem[];
}

export interface ItemInput {
  kind: ItemKind; day: number; title?: string; notes?: string; curriculum_id?: number | null; lesson_id?: number | null;
  scenario_id?: number | null; document_id?: number | null; colleague_name?: string; colleague_role?: string;
}

export interface Options {
  courses: { id: number; title: string; emoji: string; lessons: { id: number; title: string }[] }[];
  scenarios: { id: number; title: string; emoji: string }[];
  documents: { id: number; title: string }[];
}

export interface ProgressRow extends JourneyStatus {
  assignment_id: number; membership_id: number; user_id: number; name: string; email: string; start_date: string; phase_title: string;
}

export interface DraftItem {
  key: number; day: number; kind: ItemKind; title: string; notes: string; curriculum_id: number | null; scenario_id: number | null;
  document_id: number | null; colleague_role: string; ref_title: string;
}
export interface Draft { name: string; description: string; length_days: number; phases: Phase[]; items: DraftItem[] }

const base = (slug: string) => `/api/journeys/orgs/${slug}`;

export const journeys = {
  mine: () => api<MyJourney[]>("/api/journeys/me/"),
  myOne: (id: number) => api<MyJourney>(`/api/journeys/me/${id}/`),
  tick: (id: number, item: number, done: boolean) => api<MyJourney>(`/api/journeys/me/${id}/items/${item}/`, { method: "POST", json: { done } }),

  list: (slug: string) => api<{ can_edit: boolean; journeys: Journey[] }>(`${base(slug)}/`),
  get: (slug: string, id: number) => api<Journey>(`${base(slug)}/${id}/`),
  create: (slug: string, body: { name: string; description?: string; length_days?: number; phases?: Phase[]; items?: ItemInput[] }) =>
    api<Journey>(`${base(slug)}/`, { method: "POST", json: body }),
  update: (slug: string, id: number, body: Partial<{ name: string; description: string; length_days: number; phases: Phase[] }>) =>
    api<Journey>(`${base(slug)}/${id}/`, { method: "PATCH", json: body }),
  remove: (slug: string, id: number) => api(`${base(slug)}/${id}/`, { method: "DELETE" }),
  duplicate: (slug: string, id: number) => api<Journey & { dropped: { id: number; day: number; kind: ItemKind; title: string; code: string }[] }>(`${base(slug)}/${id}/duplicate/`, { method: "POST", json: {} }),
  addItem: (slug: string, id: number, body: ItemInput) => api<JourneyItem>(`${base(slug)}/${id}/items/`, { method: "POST", json: body }),
  removeItem: (slug: string, id: number, item: number) => api(`${base(slug)}/${id}/items/${item}/`, { method: "DELETE" }),
  options: (slug: string) => api<Options>(`${base(slug)}/options/`),
  people: (slug: string) => api<{ members: { id: number; name: string; email: string; role: string }[]; groups: { id: number; name: string }[] }>(`${base(slug)}/people/`),
  assign: (slug: string, id: number, body: { membership_ids: number[]; group_id: number | null; start_date: string }) =>
    api<{ assigned: number; skipped: number; not_granted: { id: number; title: string }[] }>(`${base(slug)}/${id}/assign/`, { method: "POST", json: body }),
  unassign: (slug: string, id: number, aid: number) => api(`${base(slug)}/${id}/assignees/${aid}/`, { method: "DELETE" }),
  progress: (slug: string, id: number) => api<{ today: string; rows: ProgressRow[] }>(`${base(slug)}/${id}/progress/`),
  csvUrl: (slug: string, id: number) => `${base(slug)}/${id}/progress.csv`,
  draft: (slug: string, body: { role: string; company: string; days: number }) => api<Draft>(`${base(slug)}/ai-draft/`, { method: "POST", json: body }),
};

/** Learner view buckets: today's items, what's coming, and what's behind (past days). Overdue first in "past". */
export function splitItems(items: LearnerItem[], day: number) {
  const today = items.filter((i) => i.day === day);
  const upcoming = items.filter((i) => i.day > day);
  const past = items.filter((i) => i.day < day).sort((a, b) => Number(b.overdue) - Number(a.overdue) || b.day - a.day);
  return { today, upcoming, past };
}

/** Group items by day for the builder / upcoming list. */
export function byDay<T extends { day: number }>(items: T[]): [number, T[]][] {
  const m = new Map<number, T[]>();
  for (const i of [...items].sort((a, b) => a.day - b.day)) m.set(i.day, [...(m.get(i.day) ?? []), i]);
  return [...m.entries()];
}

/** Which phase a day falls in (index), or null. */
export function phaseIndex(phases: Phase[], day: number): number | null {
  const i = phases.findIndex((p) => p.start_day <= day && day <= p.end_day);
  return i < 0 ? null : i;
}

/** A draft proposal → the item payload the create endpoint validates. */
export function draftToInput(d: DraftItem): ItemInput {
  return { kind: d.kind, day: d.day, title: d.title, notes: d.notes, curriculum_id: d.curriculum_id, scenario_id: d.scenario_id,
    document_id: d.document_id, colleague_role: d.colleague_role };
}

export const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

export function shortDate(iso: string, lang: string) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(localeOf(lang), { day: "numeric", month: "short" });
}

/** "Day 3 of 30", "Starts on 20 Oct", or the end states. */
export function dayLabel(t: (k: string, o?: Record<string, unknown>) => string, a: Pick<MyJourney, "status" | "start_date">, lang: string) {
  const s = a.status;
  if (!s.started) return t("jr.startsOn", { date: shortDate(a.start_date, lang) });
  if (s.finished) return t("jr.finished");
  if (s.ended) return t("jr.ended");
  return t("jr.dayOf", { day: s.day, n: s.length_days });
}
