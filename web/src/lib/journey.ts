/** Milestone 9 learner features: lesson podcasts, listening progress, fast-track, my course order. */
import type { VoiceRole } from "@/voice/engines";

import { api } from "./api";

export interface WarmupQ { prompt: string; options: string[]; answer: number }
export interface PodcastTurn { speaker: "A" | "B"; text: string }
export interface Podcast {
  status: "none" | "generating" | "ready" | "failed"; lang?: string; title?: string; hosts?: { A?: string; B?: string };
  turns?: PodcastTurn[]; warmup: WarmupQ[]; outdated?: boolean;
  /** Server error code when status is "failed" (generation_failed | provider_not_configured). */
  error?: string; updated_at?: string; stuck?: boolean;
}

/** Same as the server's STALE_AFTER_S: a "generating" episode this old lost its job and may be rebuilt. */
export const PODCAST_STALE_MS = 300_000;

/** A "generating" episode that will never finish: the server says so (its clock), else it was last touched over 5 minutes ago. */
export const podcastStuck = (p: Podcast | undefined, now = Date.now()) =>
  p?.status === "generating" && (p.stuck ?? (!!p.updated_at && now - Date.parse(p.updated_at) >= PODCAST_STALE_MS));

const PODCAST_ERRORS: Record<string, string> = {
  podcast_budget: "lj.podcast.budget", lesson_not_ready: "lj.podcast.notReady", bad_lang: "lj.podcast.badLang",
  provider_not_configured: "lj.podcast.notConfigured", generation_failed: "lj.podcast.failed",
};

/** i18n key for a podcast error code from the API (falls back to the generic "couldn't make it" message). */
export const podcastErrorKey = (code: unknown) => (typeof code === "string" && PODCAST_ERRORS[code]) || "lj.podcast.failed";
export interface ListenState { listened: boolean; listen: number; podcast: number }
export interface FastTrackQ { id: number; prompt: string; options: string[] }
export interface FastTrackResult {
  passed: boolean; score: number; results: { id: number; correct: boolean; explanation: string; answer: number[] }[];
  next_subsection_id?: number | null; reward?: unknown;
}
export interface OrderSuggestion { order: number[]; note: string; courses: { id: number; title: string; done: number; total: number; reason: string }[] }

export const journey = {
  podcast: (lessonId: number, lang: string) => api<Podcast>(`/api/study/lessons/${lessonId}/podcast/?lang=${lang}`),
  makePodcast: (lessonId: number, lang: string) => api<Podcast>(`/api/study/lessons/${lessonId}/podcast/`, { method: "POST", json: { lang } }),
  heard: (lessonId: number, kind: "listen" | "podcast", parts: number[], lang: string) =>
    api<ListenState>(`/api/study/lessons/${lessonId}/listened/`, { method: "POST", json: { kind, parts, lang } }),
  courseListened: (courseId: number) => api<{ lessons: number[] }>(`/api/study/courses/${courseId}/listened/`),
  fastTrack: (lessonId: number, lang: string) =>
    api<{ run_id: number; questions: FastTrackQ[] }>(`/api/study/lessons/${lessonId}/fast-track/`, { method: "POST", json: { lang } }),
  submitFastTrack: (runId: number, answers: Record<number, number>) =>
    api<FastTrackResult>(`/api/study/fast-track/${runId}/submit/`, {
      method: "POST", json: { answers: Object.fromEntries(Object.entries(answers).map(([k, v]) => [k, { selected: [v] }])) },
    }),
  order: () => api<{ ids: number[] }>("/api/study/course-order/"),
  saveOrder: (ids: number[]) => api<{ ids: number[] }>("/api/study/course-order/", { method: "PUT", json: { ids } }),
  suggestOrder: () => api<OrderSuggestion>("/api/study/course-order/suggest/", { method: "POST" }),
  reorderLessons: (courseId: number, sectionId: number, lessonIds: number[]) =>
    api(`/api/learn/curriculums/${courseId}/edit/reorder/`, { method: "POST", json: { section_id: sectionId, lesson_ids: lessonIds } }),
};

/** Move one item up (-1) or down (+1); returns a new array (unchanged at the edges). */
export function move<T>(list: T[], index: number, delta: number): T[] {
  const to = index + delta;
  if (index < 0 || index >= list.length || to < 0 || to >= list.length) return list;
  const out = list.slice();
  const [x] = out.splice(index, 1);
  out.splice(to, 0, x);
  return out;
}

/** Move the item at `from` to position `to` (drag and drop). */
export function moveTo<T>(list: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || from >= list.length || to < 0 || to >= list.length) return list;
  const out = list.slice();
  const [x] = out.splice(from, 1);
  out.splice(to, 0, x);
  return out;
}

/** Two hosts → two real voices: the server gives host_a and host_b different speakers (the admin picks them). */
export const hostRoles = (turns: PodcastTurn[]): VoiceRole[] => turns.map((t) => (t.speaker === "A" ? "host_a" : "host_b"));

/** A short breath between podcast turns when the speaker changes. */
export const TURN_GAP_MS = 350;

/** Tracks which parts were heard to the end; reports every 2 new parts and at the last part (server keeps the union). */
export function heardTracker(report: (parts: number[]) => void, total: number) {
  const heard = new Set<number>();
  let sent = 0;
  return (part: number) => {
    if (heard.has(part)) return;
    heard.add(part);
    if (heard.size - sent >= 2 || part >= total - 1 || heard.size >= Math.ceil(total * 0.8)) {
      sent = heard.size;
      report([...heard]);
    }
  };
}
