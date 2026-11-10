/** Milestone 9 — school structure: sub-units, member fields v2 (self-fill), Kili setup chat, knowledge base, cohorts. */
import { api } from "./api";
import type { InviteMail } from "./orgs";

const base = (slug: string) => `/api/orgs/${slug}`;

export interface CourseRef { id: number; title: string; emoji: string }
export interface RoleRef { slug: string; title: string; emoji: string }
export interface Unit {
  id: number; name: string; description: string; parent_id: number | null; target_roles: RoleRef[]; courses: CourseRef[];
  groups: { id: number; name: string; join_code: string; members: number }[]; admins: { id: number; name: string; email: string }[];
  learners: number; pending_admins?: string[]; course_options?: CourseRef[];
}
export interface UnitLearner { id: number; user_id: number; name: string; email: string; fields: Record<string, string>; groups: number[] }

export interface MyField { key: string; label: string; type: "text" | "select"; options: string[]; value: string; editable: boolean; self_fill: boolean; missing: boolean }
export interface MyOrgFields { slug: string; org: string; fields: MyField[] }

export type ProposalOp = "set_description" | "add_group" | "add_unit" | "set_target_roles" | "set_feature" | "course_idea";
export interface Proposal { op: ProposalOp; title: string; text: string; roles: string[]; feature: string; on: boolean; why: string }
export interface SetupMsg { role: "user" | "assistant"; content: string; proposals?: Proposal[]; applied?: number[]; rejected?: number[]; errors?: Record<string, string> }
export interface SetupChat { messages: SetupMsg[]; turns: number; max_turns: number }

export type KbStatus = "queued" | "reading" | "ready" | "failed";
export interface KbDoc { id: number; title: string; filename: string; kind: string; size: number; status: KbStatus; error: string; pages: number; topics: string[]; learners_can_read: boolean; created_at: string }
export interface KbGraph { documents: { id: number; title: string }[]; topics: { key: string; label: string; count: number }[]; links: { doc: number; topic: string }[] }

export interface Cohort {
  id: number; name: string; partner: string; description: string; starts_at: string; ends_at: string; state: "upcoming" | "active" | "ended";
  courses: CourseRef[]; members: { id: number; name: string; email: string }[]; pending: string[];
}
export interface MyCohort { id: number; name: string; partner: string; org: string; state: Cohort["state"]; starts_at: string; ends_at: string; courses: CourseRef[] }

export const school = {
  units: (slug: string) => api<{ scoped: boolean; units: Unit[] }>(`${base(slug)}/units/`),
  addUnit: (slug: string, body: { name: string; parent_id?: number | null }) => api<Unit>(`${base(slug)}/units/`, { method: "POST", json: body }),
  unit: (slug: string, id: number) => api<Unit>(`${base(slug)}/units/${id}/`),
  saveUnit: (slug: string, id: number, body: Partial<{ name: string; description: string; parent_id: number | null; target_roles: string[]; course_ids: number[]; group_ids: number[] }>) =>
    api<Unit>(`${base(slug)}/units/${id}/`, { method: "PATCH", json: body }),
  deleteUnit: (slug: string, id: number) => api(`${base(slug)}/units/${id}/`, { method: "DELETE" }),
  addUnitGroup: (slug: string, id: number, name: string) => api<Unit>(`${base(slug)}/units/${id}/groups/`, { method: "POST", json: { name } }),
  unitLearners: (slug: string, id: number) => api<{ fields: { key: string; label: string }[]; learners: UnitLearner[] }>(`${base(slug)}/units/${id}/learners/`),
  unitAssignments: (slug: string, id: number) => api<{ id: number; course: CourseRef | null; group: { id: number; name: string } | null; due_at: string | null; learners: number; completed: number }[]>(`${base(slug)}/units/${id}/assignments/`),
  unitAssign: (slug: string, id: number, body: { curriculum_id: number; group_id: number; due_at?: string | null }) => api(`${base(slug)}/units/${id}/assignments/`, { method: "POST", json: body }),
  unitUnassign: (slug: string, id: number, aid: number) => api(`${base(slug)}/units/${id}/assignments/${aid}/`, { method: "DELETE" }),
  inviteUnitAdmin: (slug: string, id: number, email: string) => api<Unit & InviteMail>(`${base(slug)}/units/${id}/admins/`, { method: "POST", json: { email } }),
  removeUnitAdmin: (slug: string, id: number, mid: number) => api(`${base(slug)}/units/${id}/admins/${mid}/`, { method: "DELETE" }),
  courseOptions: (slug: string) => api<CourseRef[]>(`${base(slug)}/course-options/`),
  careers: () => api<{ slug: string; title: string; emoji: string }[]>("/api/paths/careers/"),

  myFields: () => api<{ orgs: MyOrgFields[]; missing: number }>("/api/orgs/me/fields/"),
  saveMyFields: (slug: string, fields: Record<string, string>) => api<MyOrgFields>(`/api/orgs/me/fields/${slug}/`, { method: "PATCH", json: { fields } }),

  setupChat: (slug: string) => api<SetupChat>(`${base(slug)}/setup-chat/`),
  setupSay: (slug: string, message: string) => api<SetupChat>(`${base(slug)}/setup-chat/`, { method: "POST", json: { message } }),
  setupReset: (slug: string) => api<SetupChat>(`${base(slug)}/setup-chat/`, { method: "DELETE" }),
  setupApply: (slug: string, turn: number, accept: number[], reject: number[]) =>
    api<SetupChat & { results: Record<string, string> }>(`${base(slug)}/setup-chat/apply/`, { method: "POST", json: { turn, accept, reject } }),

  knowledge: (slug: string) => api<KbDoc[]>(`${base(slug)}/knowledge/`),
  uploadKnowledge: (slug: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api<KbDoc>(`${base(slug)}/knowledge/`, { method: "POST", body: form });
  },
  setKnowledgeAudience: (slug: string, id: number, learners_can_read: boolean) => api<KbDoc>(`${base(slug)}/knowledge/${id}/`, { method: "PATCH", json: { learners_can_read } }),
  deleteKnowledge: (slug: string, id: number) => api(`${base(slug)}/knowledge/${id}/`, { method: "DELETE" }),
  graph: (slug: string) => api<KbGraph>(`${base(slug)}/knowledge/graph/`),

  cohorts: (slug: string) => api<Cohort[]>(`${base(slug)}/cohorts/`),
  addCohort: (slug: string, body: { name: string; partner?: string; starts_at: string; ends_at: string; course_ids: number[] }) => api<Cohort>(`${base(slug)}/cohorts/`, { method: "POST", json: body }),
  saveCohort: (slug: string, id: number, body: Partial<{ name: string; partner: string; starts_at: string; ends_at: string; course_ids: number[] }>) =>
    api<Cohort>(`${base(slug)}/cohorts/${id}/`, { method: "PATCH", json: body }),
  deleteCohort: (slug: string, id: number) => api(`${base(slug)}/cohorts/${id}/`, { method: "DELETE" }),
  addCohortMembers: (slug: string, id: number, body: { group_ids?: number[]; emails?: string[] }) =>
    api<Cohort & { added: number; invited: number } & InviteMail>(`${base(slug)}/cohorts/${id}/members/`, { method: "POST", json: body }),
  removeCohortMember: (slug: string, id: number, mid: number) => api(`${base(slug)}/cohorts/${id}/members/${mid}/`, { method: "DELETE" }),
  myCohorts: () => api<MyCohort[]>("/api/orgs/me/cohorts/"),
};

/** Statuses that are still moving (poll while any document is in one of these). */
export const KB_BUSY: KbStatus[] = ["queued", "reading"];

/** Pull e-mail addresses out of pasted text (commas, spaces, new lines). */
export function parseEmails(text: string): string[] {
  return [...new Set((text.match(/[^\s,;<>"']+@[^\s,;<>"']+\.[a-zA-Z]{2,}/g) ?? []).map((e) => e.toLowerCase()))];
}

export interface GraphNode { id: string; kind: "doc" | "topic"; label: string; x: number; y: number; r: number; ref: number | string }
export interface GraphEdge { from: string; to: string }

/**
 * Radial knowledge-graph layout (deterministic, no deps): topics on an inner ring ordered by how many documents share
 * them, documents on an outer ring placed near the mean angle of their topics, then a few relaxation passes that push
 * overlapping nodes apart. Coordinates are in a size×size box.
 */
export function layoutGraph(g: KbGraph, size = 520): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const c = size / 2;
  const topics = [...g.topics].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
  const rIn = topics.length > 1 ? size * 0.2 : 0;
  const rOut = size * 0.4;
  const angle: Record<string, number> = {};
  const nodes: GraphNode[] = topics.map((t, i) => {
    const a = (2 * Math.PI * i) / Math.max(topics.length, 1) - Math.PI / 2;
    angle[t.key] = a;
    return { id: `t:${t.key}`, kind: "topic", label: t.label, x: c + rIn * Math.cos(a), y: c + rIn * Math.sin(a), r: 7 + Math.min(t.count, 6) * 2, ref: t.key };
  });
  const docs = g.documents.map((d, i) => {
    const mine = g.links.filter((l) => l.doc === d.id && l.topic in angle).map((l) => angle[l.topic]);
    const fallback = (2 * Math.PI * i) / Math.max(g.documents.length, 1);
    const a = mine.length ? Math.atan2(mine.reduce((s, x) => s + Math.sin(x), 0), mine.reduce((s, x) => s + Math.cos(x), 0)) : fallback;
    return { id: `d:${d.id}`, kind: "doc" as const, label: d.title, a, r: 9, ref: d.id };
  });
  // Spread documents around the outer ring so they don't sit on top of each other.
  docs.sort((p, q) => p.a - q.a);
  const minGap = docs.length ? Math.min((2 * Math.PI) / docs.length, 0.5) : 0;
  for (let i = 1; i < docs.length; i++) if (docs[i].a - docs[i - 1].a < minGap) docs[i].a = docs[i - 1].a + minGap;
  for (const d of docs) nodes.push({ id: d.id, kind: d.kind, label: d.label, x: c + rOut * Math.cos(d.a), y: c + rOut * Math.sin(d.a), r: d.r, ref: d.ref });
  // Light repulsion so labels stay readable.
  for (let pass = 0; pass < 30; pass++) {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const p = nodes[i], q = nodes[j];
        const dx = q.x - p.x, dy = q.y - p.y;
        const dist = Math.hypot(dx, dy) || 0.01;
        const want = p.r + q.r + 14;
        if (dist < want) {
          const push = (want - dist) / 2, ux = dx / dist, uy = dy / dist;
          p.x -= ux * push; p.y -= uy * push; q.x += ux * push; q.y += uy * push;
        }
      }
    }
    for (const n of nodes) {
      n.x = Math.min(size - n.r - 2, Math.max(n.r + 2, n.x));
      n.y = Math.min(size - n.r - 2, Math.max(n.r + 2, n.y));
    }
  }
  const edges = g.links.filter((l) => l.topic in angle).map((l) => ({ from: `d:${l.doc}`, to: `t:${l.topic}` }));
  return { nodes, edges };
}
