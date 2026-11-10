/** Learning experience (lx): AI interactive widgets + "Learn with Kili" tutor sessions. */
import { api } from "@/lib/api";

export interface LessonWidget {
  status: "none" | "generating" | "ready" | "failed";
  can_edit: boolean;
  title?: string;
  /** Same-site URL of the sandboxed widget document (short-lived signed token; the response sets its own strict CSP). */
  frame_url?: string;
  error?: string;
  instructions?: string;
  checkpoint_question?: string;
  has_checkpoint?: boolean;
}

export interface TutorMessage {
  role: "kili" | "me";
  text: string;
  question?: string;
  chunk?: number;
  score?: number;
  moved_on?: boolean;
}

export interface TutorState {
  status: "none" | "active" | "done";
  chunks?: { title: string; mastery: number | null }[];
  current?: number;
  total?: number;
  question?: string;
  messages?: TutorMessage[];
}

const base = (lessonId: number) => `/api/learn/subsections/${lessonId}`;

export const lx = {
  widget: (lessonId: number) => api<LessonWidget>(`${base(lessonId)}/widget/`),
  makeWidget: (lessonId: number, instructions: string) => api<LessonWidget>(`${base(lessonId)}/widget/`, { method: "POST", json: { instructions } }),
  checkWidget: (lessonId: number, answer: number | string) => api<{ correct: boolean }>(`${base(lessonId)}/widget/check/`, { method: "POST", json: { answer } }),
  tutor: (lessonId: number) => api<TutorState>(`${base(lessonId)}/tutor/`),
  startTutor: (lessonId: number, restart = false, lang = "") => api<TutorState>(`${base(lessonId)}/tutor/`, { method: "POST", json: { restart, lang } }),
  replyTutor: (lessonId: number, message: string, lang = "") => api<TutorState>(`${base(lessonId)}/tutor/reply/`, { method: "POST", json: { message, lang } }),
};
