import type { AskAnswerData } from "@/components/study/AskAnswer";

import { api } from "./api";

export type OrgAskResult = AskAnswerData & { days?: number; class?: string | null };

/** Every invite endpoint says whether the emails really went out; if not, the links to share by hand. */
export interface InviteMail { emailed?: boolean; links?: { email: string; link: string }[]; code?: string }

/** A revoked invitation's link no longer works: drop it from the "share these links yourself" notice (null when none are left). */
export function dropInviteLink(mail: InviteMail | null, email: string): InviteMail | null {
  const links = mail?.links?.filter((l) => l.email.toLowerCase() !== email.toLowerCase());
  return mail && links?.length ? { ...mail, links } : null;
}

export type Role = "owner" | "admin" | "manager" | "learner";
export const RANK: Record<Role, number> = { learner: 0, manager: 1, admin: 2, owner: 3 };

export interface Org { id: number; slug: string; name: string; kind: string; role: Role; members: number; groups: number; scoped?: boolean; units?: { id: number; name: string }[];
  /** Platform-admin switches for this org (e.g. `workshops`), when the server sends them. */
  features?: Record<string, boolean> }
export interface PendingInvite { id: number; email: string; role: Role; created_at: string }
export interface Group { id: number; name: string; join_code: string; members: number }
export interface ClassBoard {
  class: { id: number; name: string };
  week_start: string;
  week_end: string;
  enabled: boolean;
  members: number;
  hidden: number;
  rows: { rank: number; user_id: number; name: string; xp: number }[];
}
export interface Member { id: number; user_id: number; name: string; email: string; role: Role; groups: number[]; fields?: Record<string, string>; seat?: boolean }
export interface AssignmentRow { user_id: number; name: string; done: number; total: number; pct: number; avg_score: number | null; overdue: boolean }
export interface AssignTarget { id: number; title: string; emoji: string }
export interface Assignment {
  id: number;
  kind?: "course" | "scenario";
  course: AssignTarget | null;
  scenario?: AssignTarget | null;
  mandatory?: boolean;
  survey?: { id: number; title: string } | null;
  group: { id: number; name: string } | null;
  note: string;
  due_at: string | null;
  learners: number;
  completed: number;
  overdue: number;
  avg_pct: number;
  rating?: number | null;
  rows?: AssignmentRow[];
}
export interface MyAssignment {
  id: number; org: string; kind: "course" | "scenario"; course: AssignTarget | null; scenario: AssignTarget | null; mandatory: boolean;
  due_at: string | null; note: string; done: number; total: number; overdue: boolean; status: "not_started" | "in_progress" | "done";
  best?: number | null; attempts?: number;
}
export type QType = "rating" | "scale" | "nps" | "choice" | "multi" | "text" | "matrix";
export interface Question { id: string; type: QType; text: string; required?: boolean; options?: string[]; rows?: string[]; min?: number; max?: number; min_label?: string; max_label?: string;
  section?: string; correct?: string | string[]; accepted?: string[]; points?: number }
export interface ReviewItem { id: string; text: string; type: QType; points: number; earned: number; correct: boolean; your: AnswerValue | null; answer?: string | string[] }
export interface TestResult { attempt: number; score: number; max_score: number; pct: number; passed: boolean; pass_mark: number; review?: ReviewItem[]; answers_revealed?: boolean }
export interface SubmitResult { ok: boolean; attempt: number; result: TestResult | null; can_retake: boolean; retake_at: string | null; attempts_left: number | null }
export interface AttemptRow { attempt: number; submitted_at: string; pct: number | null; passed: boolean | null }
export type AnswerValue = string | number | string[] | Record<string, string>;
export interface Survey { id: number; title: string; description: string; questions: Question[]; anonymous: boolean; status: "draft" | "open" | "closed"; responses: number;
  group: { id: number; name: string } | null; org?: string; answered?: boolean; public?: boolean; public_url?: string; draw?: { bank?: number; n?: number }; draft?: Record<string, AnswerValue>;
  kind?: "survey" | "test"; pass_mark?: number; show_review?: boolean; max_attempts?: number; cooldown_minutes?: number;
  attempts?: AttemptRow[]; can_retake?: boolean; retake_at?: string | null; attempts_left?: number | null; last_result?: TestResult | null }
export interface SurveyDraftBody { title: string; description: string; kind: "survey" | "test"; questions: Question[] }
export interface ChatChange { id: string; op: "add" | "update" | "remove" | "title" | "description"; summary: string; target?: string; after?: string; question?: Question; text?: string }
export interface TestStats { n: number; avg_pct: number | null; pass_rate: number | null; pass_mark: number; distribution: { label: string; count: number }[] }
export interface Bank { id: number; name: string; questions: Question[] }
export interface Brand { slug: string; name: string; brand_color: string; logo_url: string; features: Record<string, boolean> }
export interface FieldDef { key: string; label: string; type: "text" | "select"; options?: string[]; visibility?: "editable" | "readonly" | "hidden"; self_fill?: boolean }
export interface OrgSettings extends Brand { description?: string; display_name: string; member_fields: FieldDef[]; setup: Record<string, string> }
export interface Campaign { id: number; name: string; quota: number; used: number; expires_at: string | null; active: boolean; group: { id: number; name: string } | null; link: string }
export interface Referral { id: number; code: string; reward: string; reward_paise: number; active: boolean; owner: string | null; link: string; joins: number; owed_paise: number; paid_paise: number }
export interface LedgerRow { id: number; code: string; user: string; status: "pending" | "approved" | "paid" | "rejected"; amount_paise: number; note: string; created_at: string; paid_at: string | null }
export interface Analytics {
  kpis: { learners: number; active_7d: number; lessons_completed_30d: number; avg_score: number | null; assignments: number; completion_rate: number | null };
  daily: { day: string; xp: number; active: number }[];
  skills: { name: string; mastery: number; learners: number }[];
  at_risk: { user_id: number; name: string; reasons: string[]; last_active: string | null }[];
  assignments: Assignment[];
  leaderboard: { name: string; xp: number; streak: number }[];
}

const base = (slug: string) => `/api/orgs/${slug}`;
export interface Competencies {
  career: { slug: string; title: string; emoji: string } | null;
  options: { slug: string; title: string; emoji: string }[];
  skills?: { slug: string; name: string; required: number }[];
  rows?: { user_id: number; name: string; levels: Record<string, number> }[];
  average?: Record<string, number>;
}

export const orgs = {
  competencies: (slug: string) => api<Competencies>(`${base(slug)}/competencies/`),
  setCompetencyCareer: (slug: string, career: string) => api<Competencies>(`${base(slug)}/competencies/`, { method: "PATCH", json: { career } }),
  list: () => api<Org[]>("/api/orgs/"),
  create: (name: string, kind: string) => api<Org>("/api/orgs/", { method: "POST", json: { name, kind } }),
  get: (slug: string) => api<Org>(`${base(slug)}/`),
  join: (code: string) => api<Org & { group: string }>(`/api/orgs/join/${encodeURIComponent(code)}/`, { method: "POST" }),
  acceptInvite: (token: string) => api<Org>(`/api/orgs/invites/${token}/accept/`, { method: "POST" }),
  analytics: (slug: string) => api<Analytics>(`${base(slug)}/analytics/`),
  insights: (slug: string) => api<{ headline: string; insights: string[]; actions: string[] }>(`${base(slug)}/insights/`, { method: "POST" }),
  /** "Ask about my organisation": the server answers from a fixed catalog of metrics (first names only). */
  ask: (slug: string, question: string) => api<OrgAskResult>(`${base(slug)}/ask/`, { method: "POST", json: { question } }),
  groups: (slug: string) => api<Group[]>(`${base(slug)}/groups/`),
  addGroup: (slug: string, name: string) => api<Group[]>(`${base(slug)}/groups/`, { method: "POST", json: { name } }),
  newCode: (slug: string, id: number) => api<{ join_code: string }>(`${base(slug)}/groups/${id}/`, { method: "POST" }),
  classBoard: (slug: string, id: number) => api<ClassBoard>(`${base(slug)}/groups/${id}/board/`),
  members: (slug: string) => api<Member[]>(`${base(slug)}/members/`),
  setRole: (slug: string, id: number, role: Role) => api(`${base(slug)}/members/${id}/`, { method: "PATCH", json: { role } }),
  removeMember: (slug: string, id: number) => api(`${base(slug)}/members/${id}/`, { method: "DELETE" }),
  pendingInvites: (slug: string) => api<PendingInvite[]>(`${base(slug)}/invitations/`),
  revokeInvite: (slug: string, id: number) => api(`${base(slug)}/invitations/${id}/`, { method: "DELETE" }),
  invite: (slug: string, emails: string[], role: Role, group_id?: number) => api<{ invited: string[] } & InviteMail>(`${base(slug)}/invitations/`, { method: "POST", json: { emails, role, group_id } }),
  assignments: (slug: string) => api<Assignment[]>(`${base(slug)}/assignments/`),
  assignment: (slug: string, id: number) => api<Assignment>(`${base(slug)}/assignments/${id}/`),
  assign: (slug: string, body: { curriculum_id?: number | null; scenario_id?: number | null; group_id?: number | null; due_at?: string | null; note?: string; mandatory?: boolean; survey_id?: number | null }) => api<Assignment>(`${base(slug)}/assignments/`, { method: "POST", json: body }),
  nudge: (slug: string, user_ids: number[], message?: string) => api<{ nudged: number }>(`${base(slug)}/nudge/`, { method: "POST", json: { user_ids, message } }),
  surveys: (slug: string) => api<Survey[]>(`${base(slug)}/surveys/`),
  templates: () => api<{ key: string; title: string; description: string; questions: Question[] }[]>("/api/orgs/survey-templates/"),
  createSurvey: (slug: string, body: object) => api<Survey>(`${base(slug)}/surveys/`, { method: "POST", json: body }),
  setSurvey: (slug: string, id: number, body: object) => api<Survey>(`${base(slug)}/surveys/${id}/`, { method: "PATCH", json: body }),
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  results: (slug: string, id: number, all = false) => api<Survey & { results: any[]; test: TestStats | null; scope: "latest" | "all" }>(`${base(slug)}/surveys/${id}/results/${all ? "?attempts=all" : ""}`),
  aiChat: (slug: string, messages: { role: "user" | "assistant"; content: string }[], draft: SurveyDraftBody) =>
    api<{ reply: string; changes: ChatChange[] }>(`${base(slug)}/surveys/ai-chat/`, { method: "POST", json: { messages, draft } }),
  aiDocs: (slug: string) => api<{ id: number; title: string; pages: number }[]>(`${base(slug)}/surveys/ai-doc/`),
  aiFromDoc: (slug: string, document_id: number, kind: "survey" | "test", focus: string) =>
    api<SurveyDraftBody>(`${base(slug)}/surveys/ai-doc/`, { method: "POST", json: { document_id, kind, focus } }),
  summary: (slug: string, id: number) => api<{ themes: string[]; positives: string[]; concerns: string[]; suggested_actions: string[] }>(`${base(slug)}/surveys/${id}/summary/`, { method: "POST" }),
  myAssignments: () => api<MyAssignment[]>("/api/orgs/me/assignments/"),
  mySurveys: () => api<Survey[]>("/api/orgs/me/surveys/"),
  respond: (id: number, answers: Record<string, AnswerValue>) => api<SubmitResult>(`/api/orgs/surveys/${id}/respond/`, { method: "POST", json: { answers } }),
  saveDraft: (id: number, answers: Record<string, AnswerValue>) => api(`/api/orgs/surveys/${id}/draft/`, { method: "PUT", json: { answers } }),
  cloneSurvey: (slug: string, id: number) => api<Survey>(`${base(slug)}/surveys/${id}/clone/`, { method: "POST" }),
  deleteSurvey: (slug: string, id: number) => api(`${base(slug)}/surveys/${id}/`, { method: "DELETE" }),
  aiSurvey: (slug: string, prompt: string) => api<{ title: string; description: string; questions: Question[] }>(`${base(slug)}/surveys/ai-draft/`, { method: "POST", json: { prompt } }),
  banks: (slug: string) => api<Bank[]>(`${base(slug)}/question-banks/`),
  saveBank: (slug: string, b: { id?: number; name: string; questions: Question[] }) =>
    b.id ? api<Bank>(`${base(slug)}/question-banks/${b.id}/`, { method: "PATCH", json: b }) : api<Bank>(`${base(slug)}/question-banks/`, { method: "POST", json: b }),
  deleteBank: (slug: string, id: number) => api(`${base(slug)}/question-banks/${id}/`, { method: "DELETE" }),
  publicSurvey: (token: string, r: string) => api<{ title: string; description: string; questions: Question[]; org: string; brand_color: string; logo_url: string; draft: Record<string, AnswerValue>; answered: boolean;
    kind?: "survey" | "test"; can_retake?: boolean; last_result?: TestResult | null }>(`/api/orgs/public-surveys/${token}/?r=${r}`),
  publicDraft: (token: string, resume: string, answers: Record<string, AnswerValue>) => api(`/api/orgs/public-surveys/${token}/`, { method: "PUT", json: { resume, answers } }),
  publicRespond: (token: string, resume: string, answers: Record<string, AnswerValue>) => api<SubmitResult>(`/api/orgs/public-surveys/${token}/`, { method: "POST", json: { resume, answers } }),
  myBrand: () => api<{ orgs: Brand[]; primary: Brand | null; disabled: string[] }>("/api/orgs/me/brand/"),
  settings: (slug: string) => api<OrgSettings>(`${base(slug)}/settings/`),
  saveSettings: (slug: string, body: Partial<OrgSettings>) => api<OrgSettings>(`${base(slug)}/settings/`, { method: "PATCH", json: body }),
  setup: (slug: string) => api<{ steps: { key: string; done: boolean; skipped: boolean }[]; complete: boolean }>(`${base(slug)}/setup/`),
  skipSetup: (slug: string, skip: string) => api<{ steps: { key: string; done: boolean; skipped: boolean }[]; complete: boolean }>(`${base(slug)}/setup/`, { method: "PATCH", json: { skip } }),
  setFields: (slug: string, id: number, fields: Record<string, string>) => api(`${base(slug)}/members/${id}/fields/`, { method: "PATCH", json: { fields } }),
  campaigns: (slug: string) => api<Campaign[]>(`${base(slug)}/campaigns/`),
  addCampaign: (slug: string, body: { name: string; quota: number; expires_at?: string | null; group_id?: number | null }) => api<Campaign>(`${base(slug)}/campaigns/`, { method: "POST", json: body }),
  setCampaign: (slug: string, id: number, body: Partial<Campaign>) => api<Campaign>(`${base(slug)}/campaigns/${id}/`, { method: "PATCH", json: body }),
  campaignEmails: (slug: string, id: number, csv: string) => api<{ invited: number; skipped: number } & InviteMail>(`${base(slug)}/campaigns/${id}/emails/`, { method: "POST", json: { csv } }),
  campaignInfo: (token: string) => api<{ org: Brand; campaign: string; open: boolean; member: boolean }>(`/api/orgs/campaign/${token}/`),
  joinCampaign: (token: string) => api<{ slug: string }>(`/api/orgs/campaign/${token}/`, { method: "POST" }),
  referrals: (slug: string) => api<Referral[]>(`${base(slug)}/referrals/`),
  addReferral: (slug: string, body: { code?: string; reward: string; reward_paise: number }) => api<Referral>(`${base(slug)}/referrals/`, { method: "POST", json: body }),
  setReferral: (slug: string, id: number, body: Partial<Referral>) => api<Referral>(`${base(slug)}/referrals/${id}/`, { method: "PATCH", json: body }),
  ledger: (slug: string) => api<LedgerRow[]>(`${base(slug)}/referral-ledger/`),
  setLedger: (slug: string, id: number, status: string) => api(`${base(slug)}/referral-ledger/${id}/`, { method: "PATCH", json: { status } }),
  referralInfo: (code: string) => api<{ org: Brand; reward: string; open: boolean }>(`/api/orgs/referral/${encodeURIComponent(code)}/`),
  joinReferral: (code: string) => api<{ slug: string }>(`/api/orgs/referral/${encodeURIComponent(code)}/`, { method: "POST" }),
  documents: (slug: string) => api<{ id: number; document_id: number; title: string; pages: number; shared_by: string }[]>(`${base(slug)}/documents/`),
  shareDocument: (slug: string, document_id: number) => api(`${base(slug)}/documents/`, { method: "POST", json: { document_id } }),
  unshareDocument: (slug: string, id: number) => api(`${base(slug)}/documents/${id}/`, { method: "DELETE" }),
  sharedWithMe: () => api<{ document_id: number; title: string; pages: number; org: string }[]>("/api/orgs/me/documents/"),
};
