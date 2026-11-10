/** Institution workshops (M4): batch runs scheduled from the cockpit, the live faculty dashboard, and the post-run report. */
import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/stores/auth";

import { api, ensureFreshAccess } from "./api";
import { TOKEN_EXPIRED } from "./useMentorSocket";
import { istToIso, REAUTH_MS, type AdminTemplate, type Proctoring, type RunStatus, type StageKind } from "./workshops";

export interface NamedRef { id: number; name: string }
export interface OrgRun {
  id: number;
  workshop: { slug: string; title: string; duration_minutes?: number };
  starts_at: string;
  status: RunStatus | string;
  proctoring: Proctoring | "";
  late_join_minutes: number;
  lobby_opens_minutes: number;
  groups?: NamedRef[];
  cohorts?: NamedRef[];
  enrolled?: number;
  started?: number;
  finished?: number;
  passed?: number;
}
export interface OrgRunIn {
  workshop_slug: string; starts_at: string; groups: number[]; cohorts: number[]; proctoring: Proctoring | ""; late_join_minutes: number; lobby_opens_minutes: number;
}
/** Distinct learners this month; a limit of 0 means the org can't schedule yet. */
export interface SeatQuota { limit: number; used: number; month?: string }

const base = (slug: string) => `/api/orgs/${slug}/workshops`;

/** The runs list may come bare or wrapped with this month's quota. */
function runsOf(r: OrgRun[] | { runs: OrgRun[]; quota?: SeatQuota | null } | null): { runs: OrgRun[]; quota: SeatQuota | null } {
  if (!r) throw new Error("no_runs");
  return Array.isArray(r) ? { runs: r, quota: null } : { runs: r.runs ?? [], quota: r.quota ?? null };
}

export const orgWorkshops = {
  templates: (slug: string) => api<AdminTemplate[]>(`${base(slug)}/templates/`),
  runs: async (slug: string) => runsOf(await api<OrgRun[] | { runs: OrgRun[]; quota?: SeatQuota | null } | null>(`${base(slug)}/runs/`)),
  create: (slug: string, body: OrgRunIn) => api<OrgRun>(`${base(slug)}/runs/`, { method: "POST", json: body }),
  update: (slug: string, id: number, body: Partial<OrgRunIn>) => api<OrgRun>(`${base(slug)}/runs/${id}/`, { method: "PATCH", json: body }),
  cancel: (slug: string, id: number) => api<OrgRun>(`${base(slug)}/runs/${id}/cancel/`, { method: "POST" }),
  learner: (slug: string, runId: number, sessionId: number) => api<LearnerTimeline>(`${base(slug)}/runs/${runId}/learners/${sessionId}/`),
  reportUrl: (slug: string, runId: number, kind: ReportKind) => `${base(slug)}/runs/${runId}/report.${kind}`,
};
/** Admin console: which orgs may run institution workshops, and their monthly seat cap (null = no cap). */
export interface AdminOrgWorkshops { id: number; slug: string; name: string; members?: number; workshops: boolean; /** Distinct learners per month; 0 = can't schedule yet. */
  workshop_seats: number; seats_used?: number }
export const adminOrgWorkshops = {
  list: () => api<AdminOrgWorkshops[]>("/api/admin/workshops/orgs/"),
  save: (id: number, body: Partial<Pick<AdminOrgWorkshops, "workshops" | "workshop_seats">>) => api<AdminOrgWorkshops>(`/api/admin/workshops/orgs/${id}/`, { method: "PATCH", json: body }),
};
export const SEATS_MAX = 100_000;

export type ReportKind = "pdf" | "pptx" | "csv";
export const REPORT_KINDS: ReportKind[] = ["pdf", "pptx", "csv"];
export const runsKey = (slug: string) => ["org-workshop-runs", slug] as const;

// ---- Schedule form ----

export interface OrgRunForm { workshop_slug: string; date: string; time: string; groups: number[]; cohorts: number[]; proctoring: Proctoring | ""; late_join_minutes: string; lobby_opens_minutes: string }
export const blankOrgRunForm = (): OrgRunForm => ({ workshop_slug: "", date: "", time: "", groups: [], cohorts: [], proctoring: "", late_join_minutes: "15", lobby_opens_minutes: "15" });

const whole = (v: string, lo: number, hi: number) => /^\d+$/.test(v.trim()) && Number(v) >= lo && Number(v) <= hi;

/** Client-side checks matching the server's: error keys per field (orgWs.err.*), or the request body. */
export function validateOrgRunForm(f: OrgRunForm, now: number): { errors: Partial<Record<keyof OrgRunForm, string>>; body: OrgRunIn | null } {
  const errors: Partial<Record<keyof OrgRunForm, string>> = {};
  if (!f.workshop_slug) errors.workshop_slug = "template";
  let starts = "";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(f.date) || !/^\d{2}:\d{2}$/.test(f.time)) errors.date = "when";
  else {
    starts = istToIso(f.date, f.time);
    if (Date.parse(starts) <= now) errors.date = "past";
  }
  if (!f.groups.length && !f.cohorts.length) errors.groups = "audience";
  if (!whole(f.late_join_minutes, 0, 60)) errors.late_join_minutes = "late";
  if (!whole(f.lobby_opens_minutes, 5, 60)) errors.lobby_opens_minutes = "lobby";
  if (Object.keys(errors).length) return { errors, body: null };
  return {
    errors,
    body: {
      workshop_slug: f.workshop_slug, starts_at: starts, groups: f.groups, cohorts: f.cohorts, proctoring: f.proctoring,
      late_join_minutes: Number(f.late_join_minutes), lobby_opens_minutes: Number(f.lobby_opens_minutes),
    },
  };
}

/** Server codes that belong beside a form field; the rest show under the form. */
export const ORG_RUN_CODE_FIELD: Record<string, keyof OrgRunForm> = {
  bad_workshop: "workshop_slug", bad_starts_at: "date", starts_in_past: "date",
  bad_groups: "groups", bad_cohorts: "groups", no_learners: "groups", quota_exceeded: "groups",
  bad_proctoring: "proctoring", bad_late_join: "late_join_minutes", bad_lobby_opens: "lobby_opens_minutes",
};

/** Upcoming (not yet over) first, soonest first; past and cancelled after, latest first. */
export function splitRuns(runs: OrgRun[]): { upcoming: OrgRun[]; past: OrgRun[] } {
  const over = (r: OrgRun) => r.status === "ended" || r.status === "cancelled";
  const by = (a: OrgRun, b: OrgRun) => Date.parse(a.starts_at) - Date.parse(b.starts_at);
  return { upcoming: runs.filter((r) => !over(r)).sort(by), past: runs.filter(over).sort((a, b) => by(b, a)) };
}

// ---- Live monitor ----

export const STATUSES = ["needs_help", "stuck", "away", "idle", "overtime", "in_grace", "getting_ready", "engaged", "doing_diy", "finished", "passed"] as const;
export type TileStatus = (typeof STATUSES)[number];
/** Spellings the server might use for the same status. */
const ALIAS: Record<string, TileStatus> = { prereq: "getting_ready", ready: "getting_ready", diy: "doing_diy", over_time: "overtime", grace: "in_grace", help: "needs_help", submitted: "finished" };
export const normStatus = (s: string): TileStatus => ((STATUSES as readonly string[]).includes(s) ? (s as TileStatus) : ALIAS[s] ?? "engaged");

/** Tailwind classes per status: a coloured strip and dot (the label is always written out too, never colour alone). */
export const STATUS_TONE: Record<TileStatus, string> = {
  needs_help: "bg-bad", stuck: "bg-orange-500", away: "bg-violet-500", idle: "bg-amber-400", overtime: "bg-rose-400", in_grace: "bg-sky-400",
  getting_ready: "bg-slate-400", engaged: "bg-good", doing_diy: "bg-teal-500", finished: "bg-slate-500", passed: "bg-emerald-600",
};

export interface Tile {
  session_id: number;
  learner: { id: number; name: string; roll_no?: string | null };
  status: string;
  stage: { index: number; title: string; kind: StageKind | string } | null;
  concept?: string | null;
  diy?: { done: number; total: number } | null;
  score_so_far?: number | null;
  final_score?: number | null;
  passed?: boolean | null;
  /** Only when proctoring is on. */
  attention?: { hidden_s: number; idle_s: number; focus_losses: number } | null;
  /** Up to 3 AI summaries, newest first. */
  help_summaries?: string[];
  raised_hand?: boolean;
  last_activity_at?: string | null;
  pace?: string | null;
}
export type Tiles = Record<number, Tile>;

/** Replaces one tile; every other tile keeps its identity, so memoised tiles skip re-rendering. */
export function applyTiles(prev: Tiles, updates: Tile[]): Tiles {
  if (!updates.length) return prev;
  const next = { ...prev };
  for (const u of updates) next[u.session_id] = u;
  return next;
}

const rank = (s: string) => STATUSES.indexOf(normStatus(s));
/** "Needs attention first": raised hands, then by status urgency, then by name. */
export function sortTiles(list: Tile[]): Tile[] {
  return [...list].sort((a, b) => Number(!!b.raised_hand) - Number(!!a.raised_hand) || rank(a.status) - rank(b.status) || a.learner.name.localeCompare(b.learner.name));
}
export function countByStatus(list: Tile[]): Partial<Record<TileStatus, number>> {
  const out: Partial<Record<TileStatus, number>> = {};
  for (const t of list) out[normStatus(t.status)] = (out[normStatus(t.status)] ?? 0) + 1;
  return out;
}
export const filterTiles = (list: Tile[], only: ReadonlySet<TileStatus>) => (only.size ? list.filter((t) => only.has(normStatus(t.status))) : list);

export const NUDGE_MAX = 300;
/** A 0–1 score as a whole percentage, or a dash when there is none yet. */
export const pctText = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`);

/** The drill-down: everything here except the stage titles came from (or about) the learner — render as text only. */
export interface LearnerTimeline {
  learner: Tile["learner"];
  tile?: Tile | null;
  stages?: { index: number; title: string; kind?: string; status?: string; score?: number | null; minutes?: number | null }[];
  answers?: { stage?: string; question: string; answer: string; score?: number | null; correct?: boolean | null; at?: string }[];
  diy_steps?: { stage?: string; text: string; done: boolean; at?: string | null }[];
  help?: { at?: string; summary: string }[];
  attention?: { at: string; kind: string; seconds?: number | null }[] | null;
  transcript?: { role: string; text: string }[];
  nudges?: { at?: string; text: string; from?: string }[];
}

type MonitorEvent =
  | { type: "snapshot"; tiles: Tile[]; not_joined?: Tile["learner"][]; run?: { proctoring?: Proctoring | "" } }
  | { type: "tile"; tile?: Tile } & Partial<Tile>
  | { type: "ready" }
  | { type: "ack"; action: "nudge" | "ack_hand"; session_id: number; changed?: boolean }
  | { type: "error"; code: string };

export type MonitorStatus = "connecting" | "live" | "offline" | "forbidden" | "not_found";
/** Bursts of tile updates are applied together, at most this often (keeps 100+ tiles smooth). */
export const FLUSH_MS = 120;

/**
 * Faculty side of /ws/workshop-runs/<id>/monitor/. Same rules as the learner socket: a fresh token on connect, an
 * immediate reconnect on 4401, re-auth on the open socket before the token expires; 4403/4404 are final.
 */
export function useMonitorSocket(runId: number) {
  const [tiles, setTiles] = useState<Tiles>({});
  /** Enrolled learners with no session yet; one drops off as soon as their first tile arrives. */
  const [notJoined, setNotJoined] = useState<Tile["learner"][]>([]);
  const [status, setStatus] = useState<MonitorStatus>("connecting");
  const [error, setError] = useState<string | null>(null);
  const ws = useRef<WebSocket | null>(null);
  const pending = useRef<Tile[]>([]);
  const flushTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flush = useCallback(() => {
    flushTimer.current = null;
    const batch = pending.current;
    pending.current = [];
    setTiles((prev) => applyTiles(prev, batch));
    const joined = new Set(batch.map((t) => t.learner.id));
    setNotJoined((prev) => (prev.some((l) => joined.has(l.id)) ? prev.filter((l) => !joined.has(l.id)) : prev));
  }, []);
  const queue = useCallback((t: Tile) => {
    pending.current.push(t);
    flushTimer.current ??= setTimeout(flush, FLUSH_MS);
  }, [flush]);

  useEffect(() => {
    let closed = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout>;
    let reauth: ReturnType<typeof setInterval> | undefined;

    const handle = (ev: MonitorEvent) => {
      switch (ev.type) {
        case "snapshot":
          attempt = 0;
          pending.current = [];
          setTiles(Object.fromEntries((ev.tiles ?? []).map((t) => [t.session_id, t])));
          setNotJoined(Array.isArray(ev.not_joined) ? ev.not_joined : []);
          setStatus("live");
          setError(null);
          break;
        case "tile": {
          const t = (ev.tile ?? ev) as Tile;
          if (typeof t.session_id === "number" && t.learner) queue(t);
          break;
        }
        case "ready":
          setStatus("live");
          break;
        case "ack": // the server confirms a cleared hand; drop it here too in case a queued tile still had it up
          if (ev.action === "ack_hand") {
            pending.current = pending.current.map((t) => (t.session_id === ev.session_id ? { ...t, raised_hand: false } : t));
            setTiles((prev) => (prev[ev.session_id]?.raised_hand ? applyTiles(prev, [{ ...prev[ev.session_id], raised_hand: false }]) : prev));
          }
          break;
        case "error":
          if (ev.code !== "token_expired") setError(ev.code);
          break;
      }
    };

    const connect = async () => {
      setStatus("connecting");
      const token = (await ensureFreshAccess()) ?? useAuth.getState().access;
      if (closed || !token) return;
      const sock = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/workshop-runs/${runId}/monitor/`);
      ws.current = sock;
      sock.onopen = () => sock.send(JSON.stringify({ type: "auth", token }));
      sock.onmessage = (e) => {
        try {
          handle(JSON.parse(e.data) as MonitorEvent);
        } catch {
          /* a malformed frame is ignored */
        }
      };
      clearInterval(reauth);
      reauth = setInterval(async () => {
        const fresh = await ensureFreshAccess();
        if (fresh && sock.readyState === WebSocket.OPEN) sock.send(JSON.stringify({ type: "auth", token: fresh }));
      }, REAUTH_MS);
      sock.onclose = (e) => {
        clearInterval(reauth);
        if (e.code === 4403 || e.code === 4404) {
          setStatus(e.code === 4403 ? "forbidden" : "not_found"); // final: retrying won't help
          return;
        }
        setStatus("offline");
        if (!closed) timer = setTimeout(connect, e.code === TOKEN_EXPIRED ? 0 : Math.min(10_000, 500 * 2 ** attempt++));
      };
    };

    void connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      clearInterval(reauth);
      if (flushTimer.current) clearTimeout(flushTimer.current);
      flushTimer.current = null;
      ws.current?.close();
    };
  }, [runId, queue]);

  const raw = useCallback((obj: object) => {
    if (ws.current?.readyState !== WebSocket.OPEN) return false;
    ws.current.send(JSON.stringify(obj));
    return true;
  }, []);
  const nudge = useCallback((sessionId: number, text: string) => raw({ type: "nudge", session_id: sessionId, text: text.trim().slice(0, NUDGE_MAX) }), [raw]);
  /** Clears the hand straight away here too; the server's next tile confirms it. */
  const ackHand = useCallback((sessionId: number) => {
    const ok = raw({ type: "ack_hand", session_id: sessionId });
    if (ok) setTiles((prev) => (prev[sessionId] ? applyTiles(prev, [{ ...prev[sessionId], raised_hand: false }]) : prev));
    return ok;
  }, [raw]);

  return { tiles, notJoined, status, error, nudge, ackHand };
}
