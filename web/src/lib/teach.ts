import { api } from "./api";
import type { RolePlayResult, Scenario } from "./roleplay";

const b = (slug: string) => `/api/orgs/${slug}/teach`;

export type RpStatus = "not_started" | "in_progress" | "done";
export interface RpRow { user_id: number; name: string; latest: number | null; best: number | null; attempts: number; last_duration: number | null; last_attempt: string | null; status: RpStatus }
export interface RpInsights { headline: string; strengths: string[]; struggles: string[]; teaching_tips: string[]; attempts: number; updated_at: string }
export interface RpReport {
  assignment: { id: number; scenario: { id: number; title: string; emoji: string }; group: string | null; due_at: string | null; mandatory: boolean };
  summary: { learners: number; done: number; in_progress: number; not_started: number; avg_best: number | null; avg_latest: number | null };
  rows: RpRow[];
  insights: RpInsights | null;
  no_class?: boolean;
  competency?: RpCompetency;
}
export type RpStuckReason = "stalled" | "many_attempts" | "no_improvement";
export interface RpConcept { key: string; kind: "objective" | "competency"; name: string; max: number; pass: number; attempted: number; passed: number; rate: number | null; of_all?: number | null }
export interface RpCell { level: number | null; passed: boolean }
export interface RpCompetency {
  concepts: RpConcept[];
  matrix: { user_id: number; name: string; cells: Record<string, RpCell>; passed: boolean; flags: RpStuckReason[] }[];
  funnel: { stage: "assigned" | "started" | "completed" | "passed"; count: number; pct: number | null }[];
  stuck: { user_id: number; name: string; reasons: RpStuckReason[]; attempts: number; best: number | null; scores: number[]; last_attempt: string; days_since: number }[];
  pass_score: number;
  stuck_days: number;
}
export interface RpConceptInsight { summary: string; got_right: string[]; got_wrong: string[]; reteach_tips: string[]; concept: string; updated_at: string }
export interface RpConceptDrill {
  concept: RpConcept;
  right: { text: string; learners: number }[];
  wrong: { text: string; learners: number }[];
  final: { met: number; not_met: number } | null;
  learners: { user_id: number; name: string; level: number | null; passed: boolean; attempts: number }[];
  insight: RpConceptInsight | null;
}
export interface RpAttempt { id: number; status: string; started_at: string; ended_at: string | null; duration: number | null; score: number | null; result: RolePlayResult | null }

export interface LessonStat { id: number; title: string; section: string; questions: number; completed: number; answers: number; correct_rate: number | null }
export interface LearnerAnswer { user_id: number; name: string; answered: boolean; answer: string | null; correct: boolean | null; score: number | null; attempts: number; at: string | null }
export interface QuestionDrill { id: number; type: string; title: string; prompt: string; key: { answer: string; rationale: string } | null; answered: number; correct: number; learners: LearnerAnswer[] }
export interface Misconceptions { summary: string; misconceptions: { topic: string; questions: string[]; learners: number; explanation: string; reteach_tip: string }[]; updated_at: string }

export interface PilotKpi { value: number | null; n: number; of: number }
export interface Pilot {
  org: string; from: string; to: string; no_class?: boolean;
  kpis: {
    learners: number; joined_in_range: number; activation: PilotKpi; sustained: PilotKpi; completion: PilotKpi;
    gain: { pairs: number; avg_pre: number | null; avg_post: number | null; avg_gain: number | null };
    recommend: { value: number | null; source: "nps" | "ratings" | null; nps: number | null; nps_responses: number; promoters: number | null; ratings: number; rating_4plus: number | null };
  };
  weekly: { week: string; active: number; lessons: number }[];
  courses: { title: string; learners: number; completed: number; rate: number | null }[];
  highlights: string[];
}

const range = (from: string, to: string) => `?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`;

export const teach = {
  scenarios: (slug: string) => api<Scenario[]>(`${b(slug)}/scenarios/`),
  roleplay: (slug: string, id: number, stuckDays?: number) => api<RpReport>(`${b(slug)}/assignments/${id}/roleplay/${stuckDays ? `?stuck_days=${stuckDays}` : ""}`),
  roleplayConcept: (slug: string, id: number, key: string) => api<RpConceptDrill>(`${b(slug)}/assignments/${id}/roleplay/concepts/${encodeURIComponent(key)}/`),
  roleplayConceptInsight: (slug: string, id: number, key: string) =>
    api<{ insight: RpConceptInsight }>(`${b(slug)}/assignments/${id}/roleplay/concepts/${encodeURIComponent(key)}/`, { method: "POST" }),
  roleplayLearner: (slug: string, id: number, uid: number) => api<{ user_id: number; name: string; attempts: RpAttempt[] }>(`${b(slug)}/assignments/${id}/roleplay/learners/${uid}/`),
  roleplayInsights: (slug: string, id: number) => api<{ insights: RpInsights }>(`${b(slug)}/assignments/${id}/roleplay/insights/`, { method: "POST" }),
  lessons: (slug: string, id: number) => api<{ course: { id: number; title: string; emoji: string }; learners: number; lessons: LessonStat[]; no_class?: boolean }>(`${b(slug)}/assignments/${id}/lessons/`),
  lesson: (slug: string, id: number, sid: number) =>
    api<{ lesson: { id: number; title: string; objective: string }; questions: QuestionDrill[]; keys: boolean; misconceptions: Misconceptions | null }>(`${b(slug)}/assignments/${id}/lessons/${sid}/`),
  misconceptions: (slug: string, id: number, sid: number) => api<{ misconceptions: Misconceptions }>(`${b(slug)}/assignments/${id}/lessons/${sid}/misconceptions/`, { method: "POST" }),
  pilot: (slug: string, from: string, to: string) => api<Pilot>(`${b(slug)}/pilot/${range(from, to)}`),
  urls: {
    roleplayCsv: (slug: string, id: number, stuckDays = 7) => `${b(slug)}/assignments/${id}/roleplay/?export=csv&stuck_days=${stuckDays}`,
    roleplayXlsx: (slug: string, id: number, stuckDays = 7) => `${b(slug)}/assignments/${id}/roleplay/?export=xlsx&stuck_days=${stuckDays}`,
    pilotPdf: (slug: string, from: string, to: string) => `${b(slug)}/pilot/report.pdf${range(from, to)}`,
    pilotPptx: (slug: string, from: string, to: string) => `${b(slug)}/pilot/report.pptx${range(from, to)}`,
  },
};

export interface FeedbackSurvey { id: number; title: string; org: string; url: string }
