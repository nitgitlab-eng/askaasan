import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { localeOf } from "@/i18n/languages";
import { mascot } from "@/mascot/store";
import { useAuth } from "@/stores/auth";

import { ApiError, api, ensureFreshAccess } from "./api";
import { payOrder, type CheckoutOrder } from "./billing";
import { TOKEN_EXPIRED, type ChatMsg } from "./useMentorSocket";

export type Proctoring = "off" | "activity" | "strict";
export type SessionStatus = "prereq" | "active" | "in_grace" | "overtime" | "submitted";
export type StageKind = "teach" | "diy" | "check" | "build" | "agent_build" | "assessment";
export type PaceStatus = "on_track" | "behind" | "in_grace" | "overtime";
/** The server's clock may also say "submitted"; the banner ignores that one. */
type PaceTick = { status: PaceStatus | "submitted"; minutes_left: number | null };
export type Control = "slower" | "again" | "example" | "tamil" | "english" | "yes_next" | "not_yet" | "not_sure" | "stuck" | "continue";
/** Suggested replies the server offers after each host turn (a fixed allow-list, never model text). */
export const CHIPS = ["yes_next", "not_yet", "not_sure", "example", "tamil", "english", "done", "stuck", "continue"] as const;
export type Chip = (typeof CHIPS)[number];
/** Keeps only known chip ids, without repeats, at most 3. */
export function cleanChips(v: unknown): Chip[] {
  if (!Array.isArray(v)) return [];
  const out: Chip[] = [];
  for (const c of v) if ((CHIPS as readonly unknown[]).includes(c) && !out.includes(c as Chip)) out.push(c as Chip);
  return out.slice(0, 3);
}
export type StopReason = "end_turn" | "cancelled" | "max_tokens";
/** A workshop chat line: `stop` marks a reply the learner interrupted ("cancelled") or one cut at the length limit. */
export type WorkshopMsg = ChatMsg & { stop?: "cancelled" | "max_tokens" };
export type AttentionKind = "hidden" | "visible" | "blur" | "focus" | "idle" | "active" | "fs_exit";

export interface WorkshopSummary { slug: string; title: string; summary: string; level: string; duration_minutes: number }
export type RunStatus = "draft" | "scheduled" | "live" | "ended" | "cancelled";
/** `paid_pending`: paid, and the server is still confirming the capture with Razorpay. */
export type MyStatus = "none" | "enrolled" | "paid_pending";
export interface Run {
  id: number; workshop: WorkshopSummary; starts_at: string; status: RunStatus | string; price_paise: number; enrolled: boolean; session_id: number | null;
  audience?: "public" | "test" | "org"; join_opens_at?: string | null; join_closes_at?: string | null; proctoring?: Proctoring;
  my_status?: MyStatus; seats_left?: number | null; lobby_opens_at?: string | null; ends_at?: string | null;
}
export interface AgendaItem { title: string; minutes: number; kind?: StageKind }
/** GET runs/<id>/: the run plus what the learner sees before enrolling. */
/** What a run records about a learner (never the camera). */
export type TrackedItem = "answers" | "steps_done" | "help_requests" | "tab_visibility" | "window_focus" | "idle_time" | "fullscreen_exit";
export interface RunDetail extends Run {
  prerequisites?: { key: string; label: string; how_to_md?: string }[];
  agenda?: AgendaItem[];
  tracked?: (TrackedItem | string)[];
  /** Passing issues an Aasan certificate. */
  certificate?: boolean;
}

export interface Prerequisite { key: string; label: string; how_to_md: string; done: boolean }
/** A concept or step; `explained` once the companion has gone through it at least once. */
export interface Tick { text: string; done: boolean; explained?: boolean }
/** The final form as the learner sees it: MCQs without their keys, and the practical task's prompt. */
export interface FinalPublic {
  mcqs: { q: string; options: string[] }[];
  practical: { prompt: string };
  /** Agentic workshops: how many hidden questions the saved agent is tested on (the questions themselves never come here). */
  agent_tests?: number;
}
export interface Stage {
  key: string;
  kind: StageKind;
  title: string;
  minutes: number;
  concepts: Tick[];
  steps: Tick[];
  /** Index of the current concept / step within this stage. */
  cursor?: number;
  /** The current item may be left: the host has asked "Shall we move on?". */
  ready_to_move?: boolean;
  /** `build` stages: the task to build and hand in (an activity body: code, open_input or artifact_check). */
  task?: BuildTask | null;
}
export type BuildTaskType = "code" | "open_input" | "artifact_check";
export const BUILD_TASK_TYPES: readonly BuildTaskType[] = ["code", "open_input", "artifact_check"];
/** A build stage's task as the learner sees it: never the grading rubric or expected answers beyond what the body shows. */
export interface BuildTask {
  type: BuildTaskType | string;
  title?: string;
  /** The activity payload the body renders (prompt, starter_code, steps, checklist …). */
  payload: Record<string, unknown>;
  /** The learner's last graded attempt on this task, if any. */
  attempt?: (BuildResult & { answer?: Record<string, unknown> }) | null;
  /** Graded hand-ins left on this task, and the best score so far (0–1; the best one counts). */
  attempts_left?: number;
  best_score?: number | null;
}
/** A build task this app can render (one of the three activity bodies, with a payload). */
export const isBuildTask = (task: BuildTask | null | undefined): task is BuildTask & { type: BuildTaskType } =>
  !!task && (BUILD_TASK_TYPES as readonly string[]).includes(task.type) && typeof task.payload === "object" && task.payload !== null;
/** POST sessions/<id>/build/. `reveal` (artifact checks: live / missing / …) and `session` are optional. */
export interface BuildResult {
  score: number; passed: boolean; feedback: string; reveal?: Record<string, unknown>;
  best_score?: number | null; attempts_left?: number; session?: Session;
}
/** `url` is the public verify link; `id` / `pdf_url` (when sent) point at the existing credentials PDF endpoint. */
export interface Certificate { code: string; url: string; id?: number; pdf_url?: string }
export interface Session {
  id: number;
  status: SessionStatus;
  workshop: { slug: string; title: string; duration_minutes: number; grace_minutes: number; proctoring: Proctoring; pass_mark: number };
  prerequisites: Prerequisite[];
  ready: boolean;
  started_at: string | null;
  planned_end: string | null;
  grace_end: string | null;
  stage_index: number;
  stages: Stage[];
  scores: Record<string, number>;
  final_score: number | null;
  passed: boolean | null;
  certificate: Certificate | null;
  proctoring: Proctoring;
  proctor_notice_seen: boolean;
  /** Sent once the session has started (null before). */
  final?: FinalPublic | null;
  attempts_left?: number;
  final_attempts?: number;
  stage_kind?: StageKind | null;
  language?: string;
  pace?: PaceTick | null;
  paused?: "budget" | "cap" | null;
  /** Agentic workshops, once the final has been taken. */
  agent_score?: number | null;
  agent_tests?: AgentTestSummary[];
  /** Institution runs ("org"): the institution sees progress, answers, scores and help summaries, so the notice says so. */
  audience?: "public" | "test" | "org";
  /** Org runs: the server's notice (null otherwise) and what the institution sees, e.g. ["progress", …, "attention"]. */
  institution_notice?: string | null;
  institution_sees?: string[];
}
/** A message from a teacher watching an institution run's dashboard. Teacher-typed text: render as plain text. */
export interface StaffNudge {
  id: string; text: string; from?: string | null; /** ISO time it was sent. */ at?: string | null;
  /** The server's id for this nudge (the same one comes live and, if missed, in `ready.nudges`). */
  sid?: string | null;
}
/** A nudge as the server sends it, live (`staff_nudge`) or, for ones sent while the learner was away, in `ready.nudges`. */
export interface NudgeIn { id?: unknown; text?: unknown; from?: unknown; at?: unknown }
export const NUDGE_TEXT_MAX = 300;
/** At most this many banners at once (the oldest go first). */
export const NUDGES_SHOWN_MAX = 20;

/**
 * Adds incoming nudges to what is shown: plain strings only, trimmed to NUDGE_TEXT_MAX, blanks dropped, and the same
 * nudge never twice (by the server's id when sent, else text + time), so a reconnect that repeats one doesn't stack copies.
 */
export function mergeNudges(prev: StaffNudge[], incoming: NudgeIn[], now = Date.now()): StaffNudge[] {
  const out = [...prev];
  const keyOf = (sid: string | null | undefined, at: string | null | undefined, text: string) => (sid ? `id:${sid}` : `t:${at ?? ""}|${text}`);
  const seen = new Set(prev.map((n) => keyOf(n.sid, n.at, n.text)));
  incoming.forEach((n, i) => {
    if (typeof n?.text !== "string" || !n.text.trim()) return;
    const text = n.text.slice(0, NUDGE_TEXT_MAX);
    const at = typeof n.at === "string" && !Number.isNaN(Date.parse(n.at)) ? n.at : new Date(now).toISOString();
    const sid = typeof n.id === "number" || (typeof n.id === "string" && n.id) ? String(n.id) : null;
    const key = keyOf(sid, at, text);
    if (seen.has(key)) return;
    seen.add(key);
    out.push({ id: `n-${now}-${out.length}-${i}`, text, from: typeof n.from === "string" && n.from.trim() ? n.from.slice(0, 80) : null, at, sid });
  });
  return out.slice(-NUDGES_SHOWN_MAX);
}

/** Newest first, by send time (arrival order breaks ties). */
export function nudgesNewestFirst(list: StaffNudge[]): StaffNudge[] {
  return list.map((n, i) => ({ n, i, t: n.at ? Date.parse(n.at) : 0 })).sort((a, b) => b.t - a.t || b.i - a.i).map((x) => x.n);
}
export interface HelpReply { reply_md: string; summary: string }
/** One hidden agent test as the result page shows it: never the expected answer. */
export interface AgentTestSummary { index?: number; label?: string; score: number; passed: boolean; tools_used?: string[]; feedback?: string }
export interface FinalResult {
  score: number; passed: boolean; feedback: string; certificate: Certificate | null; attempts_left?: number;
  agent_score?: number | null; agent_tests?: AgentTestSummary[];
}
export interface Turn { role: string; text: string; cancelled?: boolean }
export interface AdminTemplate { slug: string; title: string; summary?: string; level?: string; duration_minutes: number; proctoring?: Proctoring }
export interface AdminRunIn {
  workshop_slug: string; starts_at: string; capacity: number; price_paise: number; proctoring: "" | Proctoring; late_join_minutes: number; lobby_opens_minutes: number;
}
export interface AdminRun extends Omit<AdminRunIn, "workshop_slug"> {
  id: number; status: RunStatus; announced_at: string | null; audience?: string;
  workshop: { slug: string; title: string; duration_minutes?: number };
  enrolled: number; paid_enrolled?: number; seats_left?: number | null; sessions_started?: number; sessions_passed?: number;
}
/** Aggregate only: public runs never show per-learner data. */
export interface RunStats {
  id?: number; status?: RunStatus;
  enrolled: number; joined: number; started?: number; finished: number; passed: number;
  /** 0–1. */
  avg_score: number | null; avg_minutes: number | null; help_requests: number;
}

const b = "/api/workshops";
export const workshops = {
  runs: () => api<Run[]>(`${b}/runs/`),
  enroll: (runId: number) => api<{ enrolled: boolean }>(`${b}/runs/${runId}/enroll/`, { method: "POST" }),
  openSession: (runId: number) => api<Session>(`${b}/runs/${runId}/session/`, { method: "POST" }),
  session: (id: number) => api<Session>(`${b}/sessions/${id}/`),
  prereq: (id: number, key: string, done: boolean) => api<Session>(`${b}/sessions/${id}/prereq/`, { method: "POST", json: { key, done } }),
  start: (id: number) => api<Session>(`${b}/sessions/${id}/start/`, { method: "POST", json: { proctor_notice: true } }),
  /** Multipart: the screenshot goes to the server for this one AI call and is never stored. */
  help: (id: number, input: { image?: File | null; error_text?: string; note?: string }) => {
    const form = new FormData();
    if (input.image) form.append("image", input.image);
    if (input.error_text) form.append("error_text", input.error_text);
    if (input.note) form.append("note", input.note);
    return api<HelpReply>(`${b}/sessions/${id}/help/`, { method: "POST", body: form });
  },
  /** Hands in the build stage's task; graded on the server with the same graders as lesson activities. */
  build: (id: number, answer: Record<string, unknown>) => api<BuildResult>(`${b}/sessions/${id}/build/`, { method: "POST", json: { answer } }),
  final: (id: number, answers: Record<number, number>, practical: string) => api<FinalResult>(`${b}/sessions/${id}/final/`, { method: "POST", json: { answers, practical } }),
  transcript: (id: number) => api<Turn[]>(`${b}/sessions/${id}/transcript/`),
  agent: (id: number) => api<AgentConfig>(`${b}/sessions/${id}/agent/`),
  saveAgent: (id: number, body: AgentSave) => api<AgentConfig | null>(`${b}/sessions/${id}/agent/`, { method: "PUT", json: body }),
  /** The token goes to the server once; it is never sent back (the config only says `has_token`). */
  addServer: (id: number, body: { url: string; label?: string; token?: string }) => api<AgentServer | null>(`${b}/sessions/${id}/agent/servers/`, { method: "POST", json: body }),
  refreshServer: (id: number, sid: string | number) => api<AgentServer | null>(`${b}/sessions/${id}/agent/servers/${encodeURIComponent(String(sid))}/refresh/`, { method: "POST" }),
  removeServer: (id: number, sid: string | number) => api<unknown>(`${b}/sessions/${id}/agent/servers/${encodeURIComponent(String(sid))}/`, { method: "DELETE" }),
  runAgent: (id: number, message: string) => api<AgentRun>(`${b}/sessions/${id}/agent/run/`, { method: "POST", json: { message } }),
  approve: (id: number, call_id: string, decision: ApprovalDecision) => api<AgentRun>(`${b}/sessions/${id}/agent/approve/`, { method: "POST", json: { call_id, decision } }),
  resetAgent: (id: number) => api<unknown>(`${b}/sessions/${id}/agent/reset/`, { method: "POST" }),
  adminTemplates: () => api<AdminTemplate[]>("/api/admin/workshops/"),
  run: (runId: number) => api<RunDetail>(`${b}/runs/${runId}/`),
  /** A Razorpay order for a paid seat; the price comes from the server, never from here. */
  checkout: (runId: number) => api<CheckoutOrder>(`${b}/runs/${runId}/checkout/`, { method: "POST" }),
  adminRuns: (status = "") => api<AdminRun[]>(`/api/admin/workshops/runs/${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  adminCreateRun: (body: AdminRunIn) => api<AdminRun>("/api/admin/workshops/runs/", { method: "POST", json: body }),
  adminUpdateRun: (id: number, body: Partial<AdminRunIn>) => api<AdminRun>(`/api/admin/workshops/runs/${id}/`, { method: "PATCH", json: body }),
  adminPublish: (id: number) => api<AdminRun>(`/api/admin/workshops/runs/${id}/publish/`, { method: "POST" }),
  adminAnnounce: (id: number) => api<AdminRun>(`/api/admin/workshops/runs/${id}/announce/`, { method: "POST" }),
  adminCancel: (id: number) => api<AdminRun>(`/api/admin/workshops/runs/${id}/cancel/`, { method: "POST" }),
  adminStats: (id: number) => api<RunStats>(`/api/admin/workshops/runs/${id}/stats/`),
  adminTestRun: (slug: string) => api<{ run_id: number; session_id?: number }>(`/api/admin/workshops/${encodeURIComponent(slug)}/test-run/`, { method: "POST" }),
};

// ---- Agent builder (M2) ----

export interface AgentTool { name: string; description: string; enabled: boolean }
export interface AgentServer {
  id: string | number; label: string; url: string;
  /** True once a token is stored (encrypted on the server); the token itself never comes back. */
  has_token: boolean;
  status: string; tools: AgentTool[]; error?: string;
}
export interface AgentConfig {
  name: string; role: string; starter: string;
  aasan_tools: AgentTool[];
  servers: AgentServer[];
  auto_approve: Record<string, string[]>;
  runs_left: number;
  /** Aasan Tools as an MCP server for the learner's own client; null when not available. */
  mcp: { url: string; token: string; expires_at: string } | null;
  /** The saved test conversation and a run waiting for approval, when the server sends them. */
  chat?: { role: string; text: string }[];
  pending?: PendingCall | null;
}
export interface AgentSave { name: string; role: string; starter: string; aasan_tools: string[]; enabled: Record<string, string[]> }
export type TraceType = "thought" | "tool_call" | "tool_result" | "approval_needed" | "answer" | "error";
/** One step of an agent run. Everything in it may come from the model or from a learner's server: render as text only. */
export interface TraceStep {
  type: TraceType;
  text?: string;
  /** Tool name (tool_call / tool_result); `tool` on approval_needed. */
  name?: string; tool?: string;
  /** The server's label for external tools; absent or "aasan" for Aasan Tools. */
  server?: string | null;
  arguments?: unknown;
  result?: unknown;
  truncated?: boolean;
  call_id?: string;
  code?: string;
}
export interface PendingCall { call_id: string; server: string; tool: string; arguments: unknown }
export interface AgentRun { trace: TraceStep[]; done: boolean; pending?: PendingCall | null; runs_left?: number }
export type ApprovalDecision = "approve" | "deny" | "always";

export const AGENT_NAME_MAX = 40;
export const AGENT_ROLE_MAX = 2000;
export const AGENT_STARTER_MAX = 500;
export const AGENT_MESSAGE_MAX = 2000;
export const AGENT_MAX_SERVERS = 3;
export const AGENT_MAX_TOOLS = 8;

/** Tools switched on across Aasan Tools and every connected server. */
export function enabledToolCount(aasan: string[], enabled: Record<string, string[]>): number {
  return aasan.length + Object.values(enabled).reduce((n, list) => n + list.length, 0);
}

/** Whether this session's workshop has an agent builder stage (so a "Your agent" drawer makes sense later on). */
export const hasAgentStage = (s: Session) => s.stages.some((x) => x.kind === "agent_build");

/** Tool output or arguments as display text: strings as they are, anything else as pretty JSON. Never HTML. */
export function asText(v: unknown): string {
  if (v === undefined || v === null) return "";
  if (typeof v === "string") return v;
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

/**
 * Joins a continued run (after an approval) onto what is already shown. The server may send the whole trace again or
 * only the new steps: a trace that starts with everything shown so far replaces it, anything else is appended.
 */
export function mergeTrace(prev: TraceStep[], next: TraceStep[]): TraceStep[] {
  const same = (a: TraceStep, b: TraceStep) => JSON.stringify(a) === JSON.stringify(b);
  if (next.length >= prev.length && prev.every((s, i) => same(s, next[i]))) return next;
  return [...prev, ...next];
}

export const HELP_IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"];
export const HELP_IMAGE_MAX = 4 * 1024 * 1024;
export const HELP_ERROR_MAX = 4000;
export const HELP_NOTE_MAX = 500;

export const currentStage = (s: Session): Stage | undefined => s.stages[s.stage_index];

/** The current concept / step of the stage, if any. */
export function currentItem(stage: Stage | undefined): Tick | undefined {
  if (!stage) return undefined;
  const items = isDiy(stage.kind) ? stage.steps : stage.concepts;
  return items[stage.cursor ?? items.findIndex((x) => !x.done)];
}

/** The server's error code from a failed REST call ("" when there is none). */
export const errorCode = (e: unknown): string => (e instanceof ApiError ? String(e.data?.code ?? "") : "");
/** Hands-on stages (the server's DIY kinds): the learner works in other tabs, so proctoring is paused. */
export const isDiy = (kind: StageKind | undefined) => kind === "diy" || kind === "build" || kind === "agent_build";

/** The pace to show: the latest server tick, else the one in the session object, else what its status says. */
export function paceOf(s: Session, tick: { status: PaceStatus; minutesLeft: number | null } | null): { status: PaceStatus; minutesLeft: number | null } | null {
  if (s.status === "prereq" || s.status === "submitted") return null;
  if (tick) return tick;
  if (s.pace && s.pace.status !== "submitted") return { status: s.pace.status, minutesLeft: s.pace.minutes_left };
  return s.status === "in_grace" || s.status === "overtime" ? { status: s.status, minutesLeft: null } : null;
}

type ServerEvent =
  | { type: "ready"; session: Session; turns?: Turn[]; nudges?: NudgeIn[]; suggest?: unknown }
  | { type: "start" }
  | { type: "delta"; text: string }
  | { type: "done"; stop_reason?: StopReason; sources?: { title: string; url: string }[] }
  | { type: "status"; state: "searching" }
  | { type: "suggest"; chips?: unknown }
  | { type: "progress"; session: Session }
  | ({ type: "pace" } & PaceTick)
  | { type: "paused"; reason: "budget" | "cap" }
  | { type: "staff_nudge"; id?: number | string; text: string; from?: string | null; at?: string | null }
  | { type: "error"; code: string };

type Status = "connecting" | "ready" | "offline";
export const REAUTH_MS = 20 * 60_000;

const toMsg = (t: Turn, i: number): WorkshopMsg => ({
  id: `h-${i}`, role: t.role === "user" || t.role === "learner" ? "user" : "assistant", content: t.text, ...(t.cancelled ? { stop: "cancelled" as const } : {}),
});

/** Index of the newest / oldest message still streaming (-1 when none). */
const lastStreaming = (m: WorkshopMsg[]) => m.findLastIndex((x) => x.streaming);
const firstStreaming = (m: WorkshopMsg[]) => m.findIndex((x) => x.streaming);
/** Ends a streaming reply: an interrupted one keeps its partial text (shown as stopped), or goes if nothing came yet. */
function finish(m: WorkshopMsg[], at: number, reason: StopReason | undefined, sources?: { title: string; url: string }[]): WorkshopMsg[] {
  if (at < 0) return m;
  const x = m[at];
  if (reason === "cancelled" && !x.content.trim()) return [...m.slice(0, at), ...m.slice(at + 1)];
  const stop = reason === "cancelled" || reason === "max_tokens" ? reason : undefined;
  const citations = sources?.length ? sources.map((src) => ({ kind: "web" as const, ...src })) : undefined; // pages the host's search used
  return [...m.slice(0, at), { ...x, streaming: false, ...(stop ? { stop } : {}), ...(citations ? { citations } : {}) }, ...m.slice(at + 1)];
}

/**
 * One learner's workshop over /ws/workshop/<id>/. A dropped socket never ends the session: it reconnects with backoff
 * (straight away on 4401, with a fresh token) and the server's "ready" restores the full state.
 */
export function useWorkshopSocket(sessionId: number, onSession: (s: Session) => void) {
  const [status, setStatus] = useState<Status>("connecting");
  const [messages, setMessages] = useState<WorkshopMsg[]>([]);
  const [busy, setBusy] = useState(false);
  const [suggest, setSuggest] = useState<Chip[]>([]);
  /** A chip or message is on its way and the server hasn't answered yet. */
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pace, setPace] = useState<{ status: PaceStatus; minutesLeft: number | null } | null>(null);
  const [paused, setPaused] = useState<"budget" | "cap" | null>(null);
  const [nudges, setNudges] = useState<StaffNudge[]>([]);
  const ws = useRef<WebSocket | null>(null);
  const onSess = useRef(onSession);
  useEffect(() => {
    onSess.current = onSession;
  }, [onSession]);

  useEffect(() => {
    let closed = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout>;
    let reauth: ReturnType<typeof setInterval> | undefined;

    const connect = async () => {
      setStatus("connecting");
      const token = (await ensureFreshAccess()) ?? useAuth.getState().access;
      if (closed || !token) return;
      const sock = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/workshop/${sessionId}/`);
      ws.current = sock;
      sock.onopen = () => sock.send(JSON.stringify({ type: "auth", token }));
      sock.onmessage = (e) => handle(JSON.parse(e.data) as ServerEvent);
      clearInterval(reauth);
      reauth = setInterval(async () => {
        const fresh = await ensureFreshAccess();
        if (fresh && sock.readyState === WebSocket.OPEN) sock.send(JSON.stringify({ type: "auth", token: fresh }));
      }, REAUTH_MS);
      sock.onclose = (e) => {
        clearInterval(reauth);
        setStatus("offline");
        setBusy(false);
        setSending(false);
        setMessages((m) => m.map((x) => (x.streaming ? { ...x, streaming: false } : x)));
        if (e.code === 4403 || e.code === 4404) {
          setError(e.code === 4403 ? "feature_off" : "not_found"); // final: retrying won't help
          return;
        }
        if (!closed) timer = setTimeout(connect, e.code === TOKEN_EXPIRED ? 0 : Math.min(10_000, 500 * 2 ** attempt++));
      };
    };

    const handle = (ev: ServerEvent) => {
      switch (ev.type) {
        case "ready":
          attempt = 0;
          setStatus("ready");
          onSess.current(ev.session);
          setPaused(ev.session.paused ?? null);
          if (ev.turns?.length) setMessages((m) => (m.length ? m : ev.turns!.map(toMsg)));
          setSuggest(cleanChips(ev.suggest));
          // Nudges a teacher sent while this learner wasn't connected (the server marks them delivered).
          if (Array.isArray(ev.nudges) && ev.nudges.length) setNudges((n) => mergeNudges(n, ev.nudges!));
          break;
        case "progress":
          onSess.current(ev.session);
          break;
        case "start":
          setBusy(true);
          setSending(false);
          setMessages((m) => [...m, { id: `a-${Date.now()}-${m.length}`, role: "assistant", content: "", streaming: true }]);
          mascot.react("talking", 0);
          break;
        case "delta":
          // The newest streaming reply, even when the learner has spoken since (their line sits after it).
          setMessages((m) => {
            const at = lastStreaming(m);
            return at < 0 ? m : [...m.slice(0, at), { ...m[at], content: m[at].content + ev.text }, ...m.slice(at + 1)];
          });
          break;
        case "done":
          setMessages((m) => {
            const out = finish(m, firstStreaming(m), ev.stop_reason, ev.sources);
            setBusy(lastStreaming(out) >= 0);
            return out;
          });
          mascot.react("idle");
          break;
        case "status":
          mascot.react("thinking", 0); // looking something up on the web
          break;
        case "suggest":
          setSuggest(cleanChips(ev.chips));
          setSending(false);
          break;
        case "pace":
          if (ev.status !== "submitted") setPace({ status: ev.status, minutesLeft: ev.minutes_left });
          break;
        case "paused":
          setBusy(false);
          setSending(false);
          setPaused(ev.reason);
          break;
        case "staff_nudge":
          setNudges((n) => mergeNudges(n, [ev]));
          break;
        case "error":
          setBusy(false);
          setSending(false);
          if (ev.code === "token_expired") break; // the socket closes next and reconnects with a fresh token
          setError(ev.code);
          setMessages((m) => m.filter((x) => !(x.streaming && !x.content)));
          break;
      }
    };

    void connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      clearInterval(reauth);
      ws.current?.close();
      mascot.react("idle");
    };
  }, [sessionId]);

  const raw = useCallback((obj: object) => {
    if (ws.current?.readyState !== WebSocket.OPEN) return false;
    ws.current.send(JSON.stringify(obj));
    return true;
  }, []);

  // A sent chip or message that never gets an answer (old server, dropped frame) must not leave the chips disabled.
  useEffect(() => {
    if (!sending) return;
    const id = setTimeout(() => setSending(false), 6000);
    return () => clearTimeout(id);
  }, [sending]);

  /**
   * Same shape as the mentor socket's send, so useVoiceMode can drive it. Allowed mid-reply: the server stops the
   * current reply (it comes back as "cancelled") and answers this instead, so a streaming reply is never ended here.
   */
  const say = useCallback(
    (text: string) => {
      if (!raw({ type: "say", text })) return false;
      setError(null);
      setBusy(true);
      setSending(true);
      setSuggest([]); // the old chips belong to the old moment; the reply brings new ones
      mascot.react("thinking", 0);
      setMessages((m) => [...m, { id: `u-${Date.now()}-${m.length}`, role: "user", content: text }]);
      return true;
    },
    [raw],
  );
  const next = useCallback(() => raw({ type: "next" }), [raw]);
  const control = useCallback((action: Control) => {
    if (!raw({ type: "control", action })) return false;
    setError(null);
    setSending(true);
    setSuggest([]); // never leave a stale chip (e.g. "Yes, next") tappable while the host answers
    return true;
  }, [raw]);
  const stepDone = useCallback((step: number) => {
    const ok = raw({ type: "step_done", step });
    if (ok) setSuggest([]);
    return ok;
  }, [raw]);
  const attention = useCallback((kind: AttentionKind) => raw({ type: "attention", kind }), [raw]);
  const raiseHand = useCallback(() => raw({ type: "raise_hand" }), [raw]);
  const cancel = useCallback(() => void raw({ type: "cancel" }), [raw]);
  /** Re-send auth on the open socket: the server replies with the full state and, right after Start, begins teaching. */
  const sync = useCallback(async () => {
    const token = (await ensureFreshAccess()) ?? useAuth.getState().access;
    if (token) raw({ type: "auth", token });
  }, [raw]);

  const dismissNudge = useCallback((id: string) => setNudges((n) => n.filter((x) => x.id !== id)), []);

  return { status, messages, busy, sending, suggest, error, pace, paused, nudges, dismissNudge, say, next, control, stepDone, attention, raiseHand, cancel, sync };
}

export const IDLE_MS = 60_000;

/**
 * Activity-only proctoring: tab visibility, window focus, 60 s without input and (strict) leaving full screen.
 * Sends nothing at all unless the workshop has proctoring on, the session has started and the stage isn't hands-on.
 */
export function useProctoring(opts: { mode: Proctoring; enabled: boolean; send: (kind: AttentionKind) => void }) {
  const send = useRef(opts.send);
  useEffect(() => {
    send.current = opts.send;
  }, [opts.send]);
  const on = opts.mode !== "off" && opts.enabled;
  const strict = opts.mode === "strict";

  useEffect(() => {
    if (!on) return;
    let idle = false;
    let timer: ReturnType<typeof setTimeout>;
    const arm = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        idle = true;
        send.current("idle");
      }, IDLE_MS);
    };
    const activity = () => {
      if (idle) {
        idle = false;
        send.current("active");
      }
      arm();
    };
    const vis = () => send.current(document.visibilityState === "hidden" ? "hidden" : "visible");
    const blur = () => send.current("blur");
    const focus = () => send.current("focus");
    const fs = () => {
      if (strict && !document.fullscreenElement) send.current("fs_exit");
    };
    const inputs = ["pointerdown", "keydown", "mousemove", "touchstart", "scroll"] as const;
    document.addEventListener("visibilitychange", vis);
    window.addEventListener("blur", blur);
    window.addEventListener("focus", focus);
    document.addEventListener("fullscreenchange", fs);
    inputs.forEach((n) => window.addEventListener(n, activity, { passive: true }));
    arm();
    return () => {
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", vis);
      window.removeEventListener("blur", blur);
      window.removeEventListener("focus", focus);
      document.removeEventListener("fullscreenchange", fs);
      inputs.forEach((n) => window.removeEventListener(n, activity));
    };
  }, [on, strict]);
}

// ---- Public workshops (M3) ----

export const runKey = (id: number) => ["workshop-run", id] as const;
export const isEnrolled = (r: Run) => r.enrolled || r.my_status === "enrolled";

/**
 * Where a run's doors are: before the lobby opens, in the lobby (prep allowed, not started yet), open (started, late
 * join still allowed), closed, or cancelled. Runs without a join window (staff test runs) are open any time.
 */
export type JoinPhase = "before_lobby" | "lobby" | "open" | "closed" | "cancelled" | "anytime";
export function joinPhase(r: Run, now: number): JoinPhase {
  if (r.status === "cancelled") return "cancelled";
  if (r.status === "ended") return "closed";
  if (!r.join_opens_at && !r.join_closes_at && !r.lobby_opens_at) return "anytime";
  const start = Date.parse(r.starts_at);
  const lobby = Date.parse(r.lobby_opens_at ?? r.join_opens_at ?? r.starts_at);
  const closes = r.join_closes_at ? Date.parse(r.join_closes_at) : Infinity;
  if (now > closes) return "closed";
  if (now >= start) return "open";
  return now >= lobby ? "lobby" : "before_lobby";
}

/** Which list a run goes in. A started session can always be continued, so it stays under "My workshops". */
export function runSection(r: Run, now: number): "mine" | "upcoming" | "past" {
  if (r.session_id) return "mine";
  const phase = joinPhase(r, now);
  if (phase === "closed" || phase === "cancelled") return "past";
  return isEnrolled(r) || r.my_status === "paid_pending" ? "mine" : "upcoming";
}

/** A run can be enrolled in until its join window closes, while seats are left. */
export function canEnrol(r: Run, now: number): "ok" | "full" | "closed" | "cancelled" {
  const phase = joinPhase(r, now);
  if (phase === "cancelled") return "cancelled";
  if (phase === "closed" || r.status === "draft") return "closed";
  return r.seats_left === 0 ? "full" : "ok";
}

export function splitDuration(ms: number): { d: number; h: number; m: number; s: number } {
  const t = Math.max(0, Math.floor(ms / 1000));
  return { d: Math.floor(t / 86400), h: Math.floor((t % 86400) / 3600), m: Math.floor((t % 3600) / 60), s: t % 60 };
}

/** Re-renders every `ms` with the current time (for countdowns). */
export function useNow(ms = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

/**
 * Verify failures for a seat order: the payment was captured but the server could not grant the seat (the run filled
 * up or closed meanwhile, or the learner was already in). Staff refund these; the learner is told so.
 */
export const PAID_NO_SEAT = ["run_full", "run_closed", "run_cancelled", "too_late", "already_enrolled"] as const;

/** Pays for a seat in Razorpay Checkout. The enrolment is granted by the server on its verified capture. */
export async function payForWorkshop(runId: number, accent: string): Promise<void> {
  const order = await workshops.checkout(runId);
  try {
    await payOrder(order, accent, PAID_NO_SEAT);
  } catch (e) {
    const code = (e as Error).message;
    throw new Error((PAID_NO_SEAT as readonly string[]).includes(code) ? "paid_no_seat" : code);
  }
}

// iCalendar text: escape \ ; , and newlines, and fold lines at 75 characters (RFC 5545).
const icsText = (v: string) => v.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
const icsTime = (d: Date) => d.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
function fold(line: string): string {
  const out: string[] = [];
  for (let i = 0; i < line.length; i += i ? 74 : 75) out.push((i ? " " : "") + line.slice(i, i ? i + 74 : 75));
  return out.join("\r\n");
}

/** An .ics event for a run, built in the browser: start, end, a link back, and a 15-minute reminder. */
export function runIcs(r: Run, url: string, stamp = new Date()): string {
  const start = new Date(r.starts_at);
  const end = r.ends_at ? new Date(r.ends_at) : new Date(start.getTime() + r.workshop.duration_minutes * 60_000);
  return [
    "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Aasan//Workshops//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
    "BEGIN:VEVENT",
    `UID:workshop-run-${r.id}@aasan`,
    `DTSTAMP:${icsTime(stamp)}`, `DTSTART:${icsTime(start)}`, `DTEND:${icsTime(end)}`,
    `SUMMARY:${icsText(r.workshop.title)}`,
    `DESCRIPTION:${icsText(`${r.workshop.summary}\n${url}`)}`,
    `URL:${url}`,
    "BEGIN:VALARM", "ACTION:DISPLAY", `DESCRIPTION:${icsText(r.workshop.title)}`, "TRIGGER:-PT15M", "END:VALARM",
    "END:VEVENT", "END:VCALENDAR",
  ].map(fold).join("\r\n") + "\r\n";
}

export function downloadIcs(r: Run, url: string) {
  const href = URL.createObjectURL(new Blob([runIcs(r, url)], { type: "text/calendar;charset=utf-8" }));
  const a = Object.assign(document.createElement("a"), { href, download: `workshop-${r.id}.ics` });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 2000);
}

// ---- Admin scheduling: times are entered and shown in India time (IST, UTC+05:30) ----

export function istParts(iso: string): { date: string; time: string } {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
      .formatToParts(new Date(iso)).map((x) => [x.type, x.value]),
  );
  return { date: `${p.year}-${p.month}-${p.day}`, time: `${p.hour}:${p.minute}` };
}
export const istToIso = (date: string, time: string) => new Date(`${date}T${time}:00+05:30`).toISOString();

export interface RunForm {
  workshop_slug: string; date: string; time: string; capacity: string; paid: boolean; price: string;
  proctoring: "" | Proctoring; late_join_minutes: string; lobby_opens_minutes: string;
}
export const PRICE_MIN_PAISE = 100;
export const PRICE_MAX_PAISE = 1_000_000;
export const CAPACITY_MAX = 5000;

export const blankRunForm = (): RunForm => ({ workshop_slug: "", date: "", time: "", capacity: "0", paid: false, price: "", proctoring: "", late_join_minutes: "15", lobby_opens_minutes: "15" });
export function runFormOf(r: AdminRun): RunForm {
  const { date, time } = istParts(r.starts_at);
  return {
    workshop_slug: r.workshop.slug, date, time, capacity: String(r.capacity), paid: r.price_paise > 0, price: r.price_paise ? String(r.price_paise / 100) : "",
    proctoring: r.proctoring ?? "", late_join_minutes: String(r.late_join_minutes), lobby_opens_minutes: String(r.lobby_opens_minutes),
  };
}

const whole = (v: string, lo: number, hi: number) => /^\d+$/.test(v.trim()) && Number(v) >= lo && Number(v) <= hi;

/** Client-side checks matching the server's: → error keys per field (adminWs.runs.err.*), or the request body. */
export function validateRunForm(f: RunForm, now: number): { errors: Partial<Record<keyof RunForm, string>>; body: AdminRunIn | null } {
  const errors: Partial<Record<keyof RunForm, string>> = {};
  if (!f.workshop_slug) errors.workshop_slug = "template";
  let starts = "";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(f.date) || !/^\d{2}:\d{2}$/.test(f.time)) errors.date = "when";
  else {
    starts = istToIso(f.date, f.time);
    if (Date.parse(starts) <= now) errors.date = "past";
  }
  if (!whole(f.capacity, 0, CAPACITY_MAX)) errors.capacity = "capacity";
  let price = 0;
  if (f.paid) {
    price = /^\d+(\.\d{1,2})?$/.test(f.price.trim()) ? Math.round(Number(f.price) * 100) : NaN;
    if (!(price >= PRICE_MIN_PAISE && price <= PRICE_MAX_PAISE)) errors.price = "price";
  }
  if (!whole(f.late_join_minutes, 0, 60)) errors.late_join_minutes = "late";
  if (!whole(f.lobby_opens_minutes, 5, 60)) errors.lobby_opens_minutes = "lobby";
  if (Object.keys(errors).length) return { errors, body: null };
  return {
    errors,
    body: {
      workshop_slug: f.workshop_slug, starts_at: starts, capacity: Number(f.capacity), price_paise: price, proctoring: f.proctoring,
      late_join_minutes: Number(f.late_join_minutes), lobby_opens_minutes: Number(f.lobby_opens_minutes),
    },
  };
}

/** How far through the workshop the learner is, 0–100: finished stages plus the done share of the current one. */
export function stageProgress(s: Pick<Session, "stages" | "stage_index">): number {
  const total = s.stages.length;
  if (!total) return 0;
  const cur = s.stages[s.stage_index];
  const items = cur ? (isDiy(cur.kind) ? cur.steps : cur.concepts) : [];
  const part = items.length ? items.filter((x) => x.done).length / items.length : 0;
  return Math.min(100, Math.round(((Math.min(s.stage_index, total) + (cur ? part : 0)) / total) * 100));
}

/** Dates and times for runs in the learner's language (the time carries its zone, e.g. "IST"). */
export function useRunTime() {
  const { i18n } = useTranslation();
  const loc = localeOf(i18n.language);
  return {
    date: (iso: string) => new Date(iso).toLocaleDateString(loc, { weekday: "short", day: "numeric", month: "short", year: "numeric" }),
    time: (iso: string) => new Date(iso).toLocaleTimeString(loc, { hour: "numeric", minute: "2-digit", timeZoneName: "short" }),
    full: (iso: string) => new Date(iso).toLocaleString(loc, { dateStyle: "medium", timeStyle: "short" }),
  };
}

/** The admin API answers {code}; these codes belong beside a form field, the rest are shown under the form. */
export const RUN_CODE_FIELD: Record<string, keyof RunForm> = {
  bad_workshop: "workshop_slug", workshop_locked: "workshop_slug",
  bad_starts_at: "date", starts_in_past: "date",
  bad_capacity: "capacity", capacity_below_enrolled: "capacity",
  bad_price: "price", price_locked: "price",
  bad_proctoring: "proctoring",
  bad_late_join: "late_join_minutes",
  bad_lobby_opens: "lobby_opens_minutes",
};

/** pass_mark arrives as a fraction (0.6); older data may hold a percentage (60). Either way → 60. */
export const asPercent = (x: number) => Math.round(x <= 1 ? x * 100 : x);
