import { useQuery } from "@tanstack/react-query";

import type { ActivityData } from "@/activities/types";

import { api } from "./api";

export interface ReviewOverview {
  due: number;
  total: number;
  next_due_at: string | null;
  reviewed_today: number;
  by_course: { curriculum_id: number; title: string; due: number }[];
}

export interface ReviewCardData {
  card_id: number;
  activity: ActivityData;
  lesson: { id: number; title: string };
}

export interface MasteryGraph {
  curriculum: { id: number; title: string };
  overall: number;
  nodes: { id: number; title: string; section_id: number; section: string; section_order: number; mastery: number; level: "new" | "learning" | "practicing" | "mastered"; state: string; skills: string[]; due: number }[];
  edges: { from: number; to: number }[];
  skills: { name: string; mastery: number }[];
}

export const useReviewOverview = () =>
  useQuery({ queryKey: ["review-overview"], queryFn: () => api<ReviewOverview>("/api/review/overview/"), refetchInterval: 60_000 });

export const fetchSession = (params: Record<string, string>) =>
  api<{ mode: string; cards: ReviewCardData[] }>(`/api/review/session/?${new URLSearchParams(params)}`);

// No course yet (id 0) means nothing to fetch, not a request for /mastery/0/.
export const useMastery = (id: number) => useQuery({ queryKey: ["mastery", id], queryFn: () => api<MasteryGraph>(`/api/review/mastery/${id}/`), enabled: id > 0 });
