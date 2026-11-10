import { api } from "./api";
import { useAuth } from "@/stores/auth";
import type { LabCourse } from "./lab";

export interface HistoryState { can_undo: boolean; can_redo: boolean; undo_label: string; redo_label: string }
export interface Version { id: number; label: string; created_at: string; lessons: number }
export interface Template { id: number; title: string; description: string; cover_emoji: string; level: string; scope: string; org: string | null; mine: boolean; lessons: number; skills: string[]; matches: string[] }
export interface LibraryLesson { id: number; title: string; objective: string; course: string; activities: number }
export interface Preset { id: number; name: string; level: string; language: string; activity_types: string[]; tone: string; lessons_per_section: number; instructions: string }
export interface Change { op: string; section_id: number; lesson_id: number; ref: number; title: string; text: string; key_points: string[]; activity_type: string; instructions: string; why: string }
export interface ChatMsg { role: "user" | "assistant"; content: string; changes?: Change[]; applied?: number[]; rejected?: number[]; errors?: Record<string, string> }
export interface Segment { start: number; end: number; title: string; summary: string; checkpoints: { at: number; question: string; options: string[]; correct: number[] }[] }
export interface Lecture { id: number; kind: "youtube" | "upload"; video_id: string; src: string; duration: number; title: string; status: "transcribing" | "segmenting" | "ready" | "failed"; error: string; segments: Segment[]; transcript: string }
export interface QuarterReview { quarter: string; review: { title: string; overview: string; covered: string[]; mastered: string[]; growth: string[]; next_quarter: string[] } | null;
  facts: { totals: Record<string, number | null>; courses: Record<string, string[]>; skills: { name: string; mastery_pct: number | null }[] } | null }

const b = "/api/studio";
export const studio = {
  history: (id: number) => api<HistoryState & { versions: Version[] }>(`${b}/courses/${id}/history/`),
  undo: (id: number) => api<LabCourse>(`${b}/courses/${id}/undo/`, { method: "POST" }),
  redo: (id: number) => api<LabCourse>(`${b}/courses/${id}/redo/`, { method: "POST" }),
  saveVersion: (id: number, label: string) => api<HistoryState & { versions: Version[] }>(`${b}/courses/${id}/versions/`, { method: "POST", json: { label } }),
  restoreVersion: (id: number, rid: number) => api<LabCourse>(`${b}/courses/${id}/versions/${rid}/`, { method: "POST" }),
  deleteVersion: (id: number, rid: number) => api(`${b}/courses/${id}/versions/${rid}/`, { method: "DELETE" }),
  setTemplate: (id: number, scope: string, org?: string) => api<LabCourse>(`${b}/courses/${id}/template/`, { method: "POST", json: { scope, org } }),
  templates: (q = "", forMe = false) => api<Template[]>(`${b}/templates/?q=${encodeURIComponent(q)}${forMe ? "&for=me" : ""}`),
  useTemplate: (id: number) => api<{ id: number; kind: "authored" | "personal" }>(`${b}/templates/${id}/use/`, { method: "POST" }),
  library: (q: string) => api<LibraryLesson[]>(`${b}/lesson-library/?q=${encodeURIComponent(q)}`),
  importLesson: (sectionId: number, subsection_id: number) => api<LabCourse>(`${b}/sections/${sectionId}/import-lesson/`, { method: "POST", json: { subsection_id } }),
  importCourse: (format: "json" | "yaml" | "outline", text: string, title?: string) =>
    api<LabCourse & { dropped_activities: number }>(`${b}/import/`, { method: "POST", json: { format, text, title } }),
  presets: () => api<Preset[]>(`${b}/presets/`),
  savePreset: (p: Partial<Preset>) => (p.id ? api<Preset>(`${b}/presets/${p.id}/`, { method: "PATCH", json: p }) : api<Preset>(`${b}/presets/`, { method: "POST", json: p })),
  deletePreset: (id: number) => api(`${b}/presets/${id}/`, { method: "DELETE" }),
  usePreset: (id: number, preset_id: number | null) => api<LabCourse>(`${b}/courses/${id}/preset/`, { method: "POST", json: { preset_id } }),
  setDocuments: (id: number, document_ids: number[]) => api<LabCourse>(`${b}/courses/${id}/documents/`, { method: "POST", json: { document_ids } }),
  research: (id: number, topic: string) => api<LabCourse>(`${b}/courses/${id}/research/`, { method: "POST", json: { topic } }),
  clearResearch: (id: number) => api<LabCourse>(`${b}/courses/${id}/research/`, { method: "DELETE" }),
  chat: (id: number) => api<{ messages: ChatMsg[] }>(`${b}/courses/${id}/chat/`),
  say: (id: number, message: string) => api<{ messages: ChatMsg[] }>(`${b}/courses/${id}/chat/`, { method: "POST", json: { message } }),
  apply: (id: number, turn: number, accept: number[], reject: number[]) =>
    api<{ messages: ChatMsg[]; course: LabCourse; results: Record<string, string> }>(`${b}/courses/${id}/chat/apply/`, { method: "POST", json: { turn, accept, reject } }),
  lectures: (lessonId: number) => api<Lecture[]>(`${b}/subsections/${lessonId}/lectures/`),
  lecture: (id: number) => api<Lecture>(`${b}/lectures/${id}/`),
  addYoutube: (lessonId: number, body: { youtube_url: string; transcript: string; duration: number; title?: string }) =>
    api<Lecture>(`${b}/subsections/${lessonId}/lectures/`, { method: "POST", json: body }),
  async uploadLecture(lessonId: number, file: File, duration: number): Promise<Lecture> {
    const form = new FormData();
    form.append("file", file);
    form.append("duration", String(Math.round(duration)));
    form.append("title", file.name);
    const res = await fetch(`${b}/subsections/${lessonId}/lectures/`, { method: "POST", body: form, headers: { Authorization: `Bearer ${useAuth.getState().access}` } });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw Object.assign(new Error("upload_failed"), { data });
    return data as Lecture;
  },
  deleteLecture: (id: number) => api(`${b}/lectures/${id}/`, { method: "DELETE" }),
  buildLecture: (id: number, segments: Segment[]) => api<{ built: number; errors: { segment: number; detail: string }[] }>(`${b}/lectures/${id}/build/`, { method: "POST", json: { segments } }),
  review: () => api<QuarterReview>(`${b}/review/`),
  writeReview: () => api<QuarterReview>(`${b}/review/`, { method: "POST" }),
  urls: {
    exportJson: (id: number) => `${b}/courses/${id}/export/?as=json`,
    exportYaml: (id: number) => `${b}/courses/${id}/export/?as=yaml`,
    pptx: (id: number, lesson?: number) => `${b}/courses/${id}/export.pptx${lesson ? `?lesson=${lesson}` : ""}`,
    orgXlsx: (slug: string) => `${b}/exports/orgs/${slug}/analytics.xlsx`,
    surveyXlsx: (slug: string, id: number) => `${b}/exports/orgs/${slug}/surveys/${id}.xlsx`,
    adminXlsx: () => `${b}/exports/admin/overview.xlsx`,
    progressXlsx: (days: number) => `${b}/exports/progress.xlsx?days=${days}`,
    reviewXlsx: () => `${b}/review.xlsx`,
  },
};

export const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
export const parseMmss = (v: string) => {
  const m = /^(\d+):([0-5]?\d)$/.exec(v.trim());
  return m ? Number(m[1]) * 60 + Number(m[2]) : Number.isFinite(Number(v)) ? Math.max(0, Math.round(Number(v))) : null;
};
