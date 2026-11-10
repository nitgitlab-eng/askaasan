import { api } from "./api";

export interface LabActivity {
  id: number;
  type: string;
  kind: string;
  title: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload: Record<string, any>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  source: Record<string, any> | null;
  editable: boolean;
}

export interface LabLesson {
  id: number;
  title: string;
  objective: string;
  lesson_status: "empty" | "generating" | "ready" | "failed";
  error: string;
  explanation_md: string;
  key_points: string[];
  activities: LabActivity[];
  feedback?: { n: number; avg: number; hard: number; easy: number; comments: string[] } | null;
  archived?: boolean;
}

export interface LabCourse {
  id: number;
  title: string;
  goal: string;
  description: string;
  level: string;
  language: string;
  cover_emoji: string;
  status: "generating" | "ready" | "failed";
  error: string;
  visibility: "private" | "link" | "catalog";
  catalog_status: "none" | "pending" | "approved" | "rejected";
  catalog_note: string;
  published_at: string | null;
  share_token: string;
  learners: number;
  template?: { scope: string; org: string | null };
  sections?: {
    id: number;
    title: string;
    summary: string;
    archived?: boolean;
    subsections: { id: number; title: string; objective: string; lesson_status: string; error: string; activities: number; archived?: boolean; rating?: number | null }[];
  }[];
  feedback?: { n: number; avg: number; hard: number; easy: number; right: number; lessons_rated: number } | null;
  history?: { can_undo: boolean; can_redo: boolean; undo_label: string; redo_label: string };
  authoring?: {
    preset: { id: number; name: string; tone: string } | null;
    research: { topic: string; notes: string; sources: { title: string; url: string }[] } | null;
    documents: { id: number; title: string }[];
  };
}

export const lab = {
  courses: () => api<LabCourse[]>("/api/lab/courses/"),
  create: (body: { goal: string; mode: "ai" | "blank"; level: string; language?: string; notes?: string }) =>
    api<LabCourse>("/api/lab/courses/", { method: "POST", json: body }),
  course: (id: number) => api<LabCourse>(`/api/lab/courses/${id}/`),
  patchCourse: (id: number, body: Partial<LabCourse>) => api<LabCourse>(`/api/lab/courses/${id}/`, { method: "PATCH", json: body }),
  deleteCourse: (id: number) => api(`/api/lab/courses/${id}/`, { method: "DELETE" }),
  addSection: (id: number, title: string) => api<LabCourse>(`/api/lab/courses/${id}/sections/`, { method: "POST", json: { title } }),
  patchSection: (id: number, body: { title?: string; summary?: string; archived?: boolean }) => api<LabCourse>(`/api/lab/sections/${id}/`, { method: "PATCH", json: body }),
  deleteSection: (id: number) => api<LabCourse>(`/api/lab/sections/${id}/`, { method: "DELETE" }),
  addLesson: (sectionId: number, title: string) => api<LabCourse>(`/api/lab/sections/${sectionId}/subsections/`, { method: "POST", json: { title } }),
  reorder: (id: number, body: { sections?: number[]; subsections?: Record<string, number[]> }) => api<LabCourse>(`/api/lab/courses/${id}/reorder/`, { method: "POST", json: body }),
  lesson: (id: number) => api<LabLesson>(`/api/lab/subsections/${id}/`),
  patchLesson: (id: number, body: Partial<LabLesson>) => api<LabLesson>(`/api/lab/subsections/${id}/`, { method: "PATCH", json: body }),
  deleteLesson: (id: number) => api(`/api/lab/subsections/${id}/`, { method: "DELETE" }),
  generate: (id: number) => api(`/api/lab/subsections/${id}/generate/`, { method: "POST" }),
  addActivity: (lessonId: number, body: { type: string; instructions?: string; source?: object }) =>
    api<LabActivity>(`/api/lab/subsections/${lessonId}/activities/`, { method: "POST", json: body }),
  saveActivity: (id: number, source: object) => api<LabActivity>(`/api/lab/activities/${id}/`, { method: "PATCH", json: { source } }),
  deleteActivity: (id: number) => api(`/api/lab/activities/${id}/`, { method: "DELETE" }),
  /** New share token: every link shared before stops working. */
  rotateShare: (id: number) => api<{ share_token: string }>(`/api/lab/courses/${id}/share/rotate/`, { method: "POST" }),
  publish: (id: number, visibility: "private" | "link" | "catalog") => api<LabCourse>(`/api/lab/courses/${id}/publish/`, { method: "POST", json: { visibility } }),
};

export const shareUrl = (token: string) => `${location.origin}/s/${token}`;
