import { useQuery } from "@tanstack/react-query";

import type { ActivityData } from "@/activities/types";

import { api } from "./api";
import { badId } from "./ids";

export interface CourseSummary {
  id: number;
  title: string;
  goal: string;
  description: string;
  level: string;
  language: string;
  skills: string[];
  status: "generating" | "ready" | "failed";
  error: string;
  progress: { done: number; total: number };
  kind?: "personal" | "authored";
  is_owner?: boolean;
  options?: { tone?: string; session_minutes?: number; styles?: string[] };
}

export interface CourseDetail extends CourseSummary {
  /** This learner has their own adaptive path through the course. */
  adaptive?: boolean;
  sections: {
    id: number;
    title: string;
    summary: string;
    subsections: {
      id: number; title: string; objective: string; lesson_status: string; state: string; score: number | null; locked: boolean;
      // Card details for the course map; optional so courses saved offline before they existed still open.
      skills?: string[]; activity_count?: number; activity_types?: string[]; minutes?: number | null;
    }[];
  }[];
}

export interface Lesson {
  id: number;
  title: string;
  objective: string;
  lesson_status: "empty" | "generating" | "ready" | "failed";
  error: string;
  explanation_md: string;
  key_points: string[];
  activities: ActivityData[];
  state: string;
  curriculum: { id: number; title: string; language: string };
  section: { id: number; title: string };
  translation?: { lang: string; status: "" | "translating" | "ready" | "failed" | "budget"; available: string[]; source: string };
}

export interface Recap {
  /** false on an adaptive course when the score is below the pass mark: practise first, the lesson stays open. */
  passed?: boolean;
  remediation?: { kind: "remediation"; subsection_id: number; reason: string } | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  reward?: any;
  /** null for a reading-only lesson (nothing to answer), so there is no score to show. */
  score: number | null;
  answered: number;
  total: number;
  correct: number;
  key_points: string[];
  next_subsection_id: number | null;
  feedback_survey?: import("./teach").FeedbackSurvey | null; // school's end-of-training survey (assigned course finished)
}

/** Polls while the server is still generating. */
export function useCourse(id: number) {
  return useQuery({
    queryKey: ["course", id],
    queryFn: () => api<CourseDetail>(`/api/learn/curriculums/${id}/`),
    enabled: !badId(id), // a bad URL (/learn/abc) must not call /curriculums/NaN/
    refetchInterval: (q) => (q.state.data?.status === "generating" ? 2000 : false),
  });
}

export function useCourses() {
  return useQuery({
    queryKey: ["courses"],
    queryFn: () => api<CourseSummary[]>("/api/learn/curriculums/"),
    refetchInterval: (q) => (q.state.data?.some((c) => c.status === "generating") ? 2500 : false),
  });
}

export type CourseOptions = { tone?: "friendly" | "formal" | "playful" | "exam"; session_minutes?: 5 | 10 | 20; styles?: string[] };
/** Either a typed goal, or `goal_id`: an adaptive goal (topic → chosen scenario) the server turns into goal/level/notes. */
export const createCourse = (
  body: ({ goal: string; level: string; domain?: string; notes?: string; document_id?: number } | { goal_id: number }) & CourseOptions,
) =>
  api<CourseSummary>("/api/learn/curriculums/", { method: "POST", json: body });
