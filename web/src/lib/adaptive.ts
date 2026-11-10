/** Adaptive learning: the goal interview (topic → real-life scenarios → constraints), the learner's own path through a
 * course, and the skill map. */
import { useQuery } from "@tanstack/react-query";

import { api } from "./api";
import { badId } from "./ids";

export interface Scenario {
  title: string;
  deliverable: string;
  level: "beginner" | "intermediate" | "advanced";
  weeks: number;
  foundations: boolean;
  custom?: boolean;
}

export interface LearningGoal {
  id: number;
  topic: string;
  about: string;
  status: "suggested" | "chosen" | "ready" | "used";
  suggestions: Scenario[];
  scenario: Scenario | Record<string, never>;
  prior: string[];
  constraints: { no_code?: boolean; hours_week?: number; deadline_weeks?: number | null };
  level: string;
  curriculum_id: number | null;
  ai_left: number;
}

export type ChooseResult = LearningGoal & { verdict: "chosen" | "accept" | "split" | "decline"; reason?: string };

export interface Constraints {
  prior: string[];
  no_code: boolean;
  hours_week: number;
  deadline_weeks?: number | null;
  level?: string;
}

export const adaptive = {
  startGoal: (topic: string, about: string) => api<LearningGoal>("/api/adaptive/goals/", { method: "POST", json: { topic, about } }),
  choose: (id: number, pick: { index: number } | { custom: string }) =>
    api<ChooseResult>(`/api/adaptive/goals/${id}/choose/`, { method: "POST", json: pick }),
  constraints: (id: number, c: Constraints) => api<LearningGoal>(`/api/adaptive/goals/${id}/constraints/`, { method: "POST", json: c }),
};

export type PathKind = "lesson" | "skip_check" | "remediation" | "final";

export interface PathItem {
  id: number;
  kind: PathKind;
  status: "pending" | "done";
  current: boolean;
  reason: "" | "known" | "weak" | "retry";
  subsection: { id: number; title: string; objective: string } | null;
  concept: { key: string; title: string } | null;
}

export interface LearnerPath {
  curriculum_id: number;
  version: number;
  changes: { practice?: number; skip?: number; unskip?: number };
  replanned_at: string | null;
  items: PathItem[];
  remaining: number;
  done: number;
}

export interface SkillMap {
  concepts: {
    key: string;
    title: string;
    description: string;
    critical: boolean;
    p_known: number;
    observations: number;
    state: "mastered" | "learning" | "weak" | "new";
    lessons: number[];
  }[];
  edges: { prereq: string; concept: string }[];
  mastered: number;
  total: number;
  critical_mastered: number;
  critical_total: number;
}

export function usePath(courseId: number, enabled = true) {
  return useQuery({
    queryKey: ["adaptive-path", courseId],
    queryFn: () => api<LearnerPath>(`/api/adaptive/courses/${courseId}/path/`),
    enabled: enabled && !badId(courseId),
    retry: false,
  });
}

export function useSkillMap(courseId: number, enabled = true) {
  return useQuery({
    queryKey: ["skill-map", courseId],
    queryFn: () => api<SkillMap>(`/api/adaptive/courses/${courseId}/skill-map/`),
    enabled: enabled && !badId(courseId),
    retry: false,
  });
}

/** The path version the learner last saw for a course, to say "your path was updated" once per change. */
export const seenVersion = {
  get(courseId: number): number {
    try {
      return Number(localStorage.getItem(`aasan-path-v-${courseId}`) || 0);
    } catch {
      return 0;
    }
  },
  set(courseId: number, v: number) {
    try {
      localStorage.setItem(`aasan-path-v-${courseId}`, String(v));
    } catch {
      /* private mode */
    }
  },
};

/** Where a path step takes the learner. Skip-checks open the lesson (its fast-track is on the lesson page). */
export function stepLink(courseId: number, it: PathItem): string | null {
  if (!it.subsection) return null;
  const lesson = `/learn/${courseId}/lesson/${it.subsection.id}`;
  return it.kind === "remediation" ? `${lesson}/practice` : it.kind === "skip_check" ? `${lesson}?fast=1` : lesson;
}
