import { api } from "./api";

export interface SkillRow { slug: string; name: string; name_ta: string; category: string; followed: boolean; hidden: boolean; order: number; self_rating: number; assessed_level: number; mastery: number | null }
export interface Rec { kind: "review" | "continue" | "practice" | "next" | "start" | "path"; score: number; title: string; link: string; why: { key: string; params: Record<string, string | number> } }
export interface PathCard { slug: string; title: string; title_ta: string; description: string; emoji: string; level: string; steps_n: number; skills: string[]; joined: boolean; org: string | null;
  steps?: { index: number; title: string; goal: string; skill: string; course: { course_id: number; status: string; done: number; total: number } | null }[] }
export interface Career { slug: string; title: string; title_ta: string; summary: string; emoji: string; salary_band: string; outlook: string; path: string | null;
  requirements?: { skill: string; name: string; name_ta: string; required: number; level: number; gap: number }[]; readiness?: number; last_assessment?: string | null;
  seniority?: Seniority; ladder?: { current: LadderRole; previous: LadderRole[]; next: LadderRole[]; senior: LadderRole[] } }
export type Seniority = "entry" | "mid" | "senior" | "lead";
export interface LadderRole { slug: string; title: string; title_ta: string; emoji: string; seniority: Seniority }
export interface QuizQ { id: number; skill: string; prompt: string; options: string[] }
export interface OnboardProfile { goals: string[]; background: string; interests: string[]; minutes_per_day: number; level_guess: string; first_course_goal: string }

export const paths = {
  skills: () => api<SkillRow[]>("/api/paths/skills/"),
  setSkill: (slug: string, body: { followed?: boolean; hidden?: boolean; self_rating?: number }) => api<SkillRow[]>(`/api/paths/skills/${slug}/`, { method: "POST", json: body }),
  reorder: (slugs: string[]) => api<SkillRow[]>("/api/paths/skills/reorder/", { method: "POST", json: { slugs } }),
  bulk: (skills: { slug: string; self_rating: number }[]) => api<SkillRow[]>("/api/paths/skills/bulk/", { method: "POST", json: { skills } }),
  recs: () => api<Rec[]>("/api/paths/recommendations/"),
  curated: () => api<PathCard[]>("/api/paths/curated/"),
  path: (slug: string) => api<PathCard>(`/api/paths/curated/${slug}/`),
  join: (slug: string) => api<PathCard>(`/api/paths/curated/${slug}/join/`, { method: "POST" }),
  linkStep: (slug: string, index: number, curriculum_id: number) => api<PathCard>(`/api/paths/curated/${slug}/steps/${index}/`, { method: "POST", json: { curriculum_id } }),
  careers: () => api<Career[]>("/api/paths/careers/"),
  career: (slug: string) => api<Career>(`/api/paths/careers/${slug}/`),
  startAssessment: (slug: string) => api<{ id: number; questions: QuizQ[] }>(`/api/paths/careers/${slug}/assessment/`, { method: "POST" }),
  submitAssessment: (id: number, answers: Record<string, number>) => api<{ levels: Record<string, number>; score: number; reveal: { id: number; correct: number; explanation: string }[]; career: Career }>(`/api/paths/assessments/${id}/submit/`, { method: "POST", json: { answers } }),
  placement: (goal: string) => api<{ id: number; questions: QuizQ[] }>("/api/paths/placement/", { method: "POST", json: { goal } }),
  submitPlacement: (id: number, answers: Record<string, number>) => api<{ level: "beginner" | "intermediate" | "advanced"; score: number }>(`/api/paths/placement/${id}/submit/`, { method: "POST", json: { answers } }),
  interview: (messages: { role: "user" | "assistant"; content: string }[]) => api<{ reply: string; done: boolean; profile: OnboardProfile }>("/api/paths/onboarding-chat/", { method: "POST", json: { messages } }),
  applyInterview: (profile: OnboardProfile) => api("/api/paths/onboarding-apply/", { method: "POST", json: { profile } }),
};

export const DOMAIN_SKILLS: Record<string, string[]> = {
  ai: ["ai-basics", "generative-ai", "prompt-engineering"], python: ["python", "programming-basics"], data: ["data-analysis", "sql", "statistics"],
  web: ["web-development", "programming-basics"], prompting: ["prompt-engineering", "ai-tools"], career: ["interviews", "english-communication"],
};
