import { api } from "./api";

export interface PlanGoal {
  id: string; week: number; order: number; title: string; skill: string; skill_name: string; due: string; done: boolean;
  course_id: number | null; course_title: string; lesson_id: number | null; lesson_title: string; course_goal: string; link: string;
}
export interface PlanWeek { week: number; theme: string; start: string; end: string; goals: PlanGoal[] }
export interface CareerPlan {
  career: string; start_date: string; end_date: string; summary: string; weeks: PlanWeek[]; people: { role: string; why: string; ask: string }[];
  generations: number; updated_at: string; done: number; total: number;
}

const url = (slug: string) => `/api/paths/careers/${slug}/plan/`;

export const careerPlan = {
  get: (slug: string) => api<{ plan: CareerPlan | null }>(url(slug)),
  generate: (slug: string) => api<{ plan: CareerPlan }>(url(slug), { method: "POST" }),
  tick: (slug: string, id: string, done: boolean) => api<{ plan: CareerPlan }>(`${url(slug)}goals/${id}/`, { method: "POST", json: { done } }),
  linkCourse: (slug: string, id: string, course_id: number) => api<{ plan: CareerPlan }>(`${url(slug)}goals/${id}/`, { method: "POST", json: { course_id } }),
};

/** Share of goals done, 0..100. */
export const planPct = (p: Pick<CareerPlan, "done" | "total">) => (p.total ? Math.round((p.done / p.total) * 100) : 0);
