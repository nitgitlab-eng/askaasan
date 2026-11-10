/** Milestone 8 learner features: explainer videos, pulse checks, about-me, pre/post checkpoints, own-course editing, career profile. */
import { api } from "./api";

export interface Scene { heading: string; points: string[]; visual: string; narration: string }
export interface Explainer { status: "none" | "generating" | "ready" | "failed"; lang?: string; title?: string; scenes?: Scene[]; transcript?: string; outdated?: boolean }
export interface PulseReply { saved: boolean; message: string; tip: string; simpler: string; extra: string }
export interface AboutQ { key: string; choices: string[] }
export interface CheckpointResult { score: number; correct: number; total: number; at: string }
export interface Checkpoint {
  status: "none" | "generating" | "ready" | "failed";
  questions: { id: string; prompt: string; options: string[]; lesson: string }[];
  pre: CheckpointResult | null; post: CheckpointResult | null; gain: number | null;
}
/** The pre-test review leaves out `correct` and `explanation` (so the post-test stays a fair measure); only the post-test sends them. */
export interface CheckpointReview { id: string; picked: number[]; correct?: number[]; ok: boolean; explanation?: string; confidence: number | null }
export interface EditState { can_undo: boolean; can_redo: boolean; undo_label: string; redo_label: string;
  hidden: { id: number; title: string; kind: "section" | "lesson" }[]; sources: { id: number; title: string }[] }
export interface MatchedSkill { slug: string; name: string; name_ta: string }

export const learner = {
  explainer: (lessonId: number, lang: string) => api<Explainer>(`/api/study/lessons/${lessonId}/explainer/?lang=${lang}`),
  makeExplainer: (lessonId: number, lang: string) => api<Explainer>(`/api/study/lessons/${lessonId}/explainer/`, { method: "POST", json: { lang } }),
  pulse: (lessonId: number, body: { pace?: string; difficulty?: string; energy?: string; relevant?: boolean | null; wish?: string; lang?: string }) =>
    api<PulseReply>(`/api/study/lessons/${lessonId}/pulse/`, { method: "POST", json: body }),
  about: () => api<{ data: Record<string, unknown>; next: AboutQ | null }>("/api/study/about/"),
  answerAbout: (body: { key: string; value: string | string[] } | { skip: string }) =>
    api<{ data: Record<string, unknown>; next: AboutQ | null }>("/api/study/about/", { method: "POST", json: body }),
  checkpoint: (courseId: number) => api<Checkpoint>(`/api/study/courses/${courseId}/checkpoint/`),
  prepareCheckpoint: (courseId: number) => api<Checkpoint>(`/api/study/courses/${courseId}/checkpoint/`, { method: "POST" }),
  submitCheckpoint: (courseId: number, kind: "pre" | "post", answers: Record<string, number>, confidence: Record<string, number>) =>
    api<Checkpoint & { review: CheckpointReview[] }>(`/api/study/courses/${courseId}/checkpoint/submit/`, { method: "POST", json: { kind, answers, confidence } }),
  myCheckpoints: () => api<{ course: { id: number; title: string; emoji: string }; pre: CheckpointResult | null; post: CheckpointResult | null; gain: number | null }[]>("/api/study/checkpoints/"),
  editState: (courseId: number) => api<EditState>(`/api/learn/curriculums/${courseId}/edit/`),
  addSection: (courseId: number, request: string) => api<EditState & { section_id: number }>(`/api/learn/curriculums/${courseId}/edit/add-section/`, { method: "POST", json: { request } }),
  setHidden: (courseId: number, kind: "section" | "lesson", id: number, hidden: boolean) =>
    api<EditState>(`/api/learn/curriculums/${courseId}/edit/hidden/`, { method: "POST", json: { kind, id, hidden } }),
  step: (courseId: number, direction: "undo" | "redo") => api<EditState>(`/api/learn/curriculums/${courseId}/edit/${direction}/`, { method: "POST" }),
  addSource: (courseId: number, document_id: number) => api<{ sources: EditState["sources"] }>(`/api/learn/curriculums/${courseId}/edit/sources/`, { method: "POST", json: { document_id } }),
  removeSource: (courseId: number, document_id: number) =>
    api<{ sources: EditState["sources"] }>(`/api/learn/curriculums/${courseId}/edit/sources/?document_id=${document_id}`, { method: "DELETE" }),
  company: (name: string) => api<{ name: string; summary: string; industry: string; sources: { title: string; url: string }[] }>("/api/paths/company/", { method: "POST", json: { name } }),
  roleSummary: (role: string) => api<{ role: string; summary: string; skills: string[]; matched: MatchedSkill[] }>("/api/paths/role-summary/", { method: "POST", json: { role } }),
  cv: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return api<{ current_role: string; years_experience: number; skills: string[]; summary: string; matched: MatchedSkill[] }>("/api/paths/cv/", { method: "POST", body: fd });
  },
  targetRole: (role: string) =>
    api<{ role: string; required: string[]; missing: string[]; missing_matched: MatchedSkill[]; courses: string[] }>("/api/paths/target-role/", { method: "POST", json: { role } }),
};
