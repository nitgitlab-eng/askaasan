import { useCallback, useEffect, useRef, useState } from "react";

import { mascot } from "@/mascot/store";
import { useAuth } from "@/stores/auth";

import { api, ensureFreshAccess } from "./api";
import { TOKEN_EXPIRED, type ChatMsg } from "./useMentorSocket";

export interface Scenario {
  id: number;
  source: "library" | "custom";
  emoji: string;
  title: string;
  summary: string;
  learner_role: string;
  character: { name: string; persona: string };
  setting: string;
  objectives: string[];
  competencies: { name: string; description: string }[];
  difficulty: "easy" | "medium" | "hard";
  max_turns: number;
}

export interface RolePlayResult {
  overall: number;
  competencies: { name: string; score: number; evidence: string[]; comment: string }[];
  objectives: { text: string; met: boolean }[];
  strengths: string[];
  improvements: string[];
  better_phrasing: { learner_said: string; try_saying: string }[];
  summary: string;
  /** Live coach summary (tracker progression, fact checks, hints used); absent on older reports. */
  coach?: { progression: CoachProgress[]; checks: CoachCheck[]; hints_used: number };
}

export interface CoachItem { text: string; score: number; reason: string }
export interface CoachCheck { fact: string; said: string; note: string; turn_id: number }
export interface CoachProgress { turn_id: number; objectives: number[]; competencies: number[] }
export interface CoachHint { text: string; after_turn: number }
export interface CoachState {
  objectives: CoachItem[];
  competencies: CoachItem[];
  checks: CoachCheck[];
  progression: CoachProgress[];
  hints: CoachHint[];
  hints_used: number;
  hints_left: number;
}

export interface Session {
  id: number;
  language?: string;
  status: "active" | "evaluating" | "completed";
  scenario: Scenario;
  result: RolePlayResult | null;
  learner_turns: number;
  lesson?: { url: string; title: string; activity_id: number } | null;
  turns?: { id: number; role: "learner" | "character"; text: string }[];
  feedback_survey?: import("./teach").FeedbackSurvey | null; // school's survey after an assigned role-play
  coach?: CoachState; // live tracker + hints (session detail only)
}

export const roleplay = {
  scenarios: () => api<Scenario[]>("/api/roleplay/scenarios/"),
  generate: (goal: string, difficulty: string) => api<Scenario>("/api/roleplay/scenarios/generate/", { method: "POST", json: { goal, difficulty } }),
  start: (scenario_id: number, assignment_id?: number) => api<Session>("/api/roleplay/sessions/", { method: "POST", json: { scenario_id, assignment_id } }),
  session: (id: number) => api<Session>(`/api/roleplay/sessions/${id}/`),
  sessions: () => api<Session[]>("/api/roleplay/sessions/"),
  coach: (id: number) => api<CoachState>(`/api/roleplay/sessions/${id}/coach/`),
  /** Scores the latest learner turn (once per turn) and returns the live tracker. */
  track: (id: number) => api<CoachState>(`/api/roleplay/sessions/${id}/coach/`, { method: "POST" }),
  hint: (id: number) => api<{ hint: CoachHint; hints_used: number; hints_left: number }>(`/api/roleplay/sessions/${id}/hint/`, { method: "POST" }),
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  end: (id: number) => api<{ result: RolePlayResult; reward: any; feedback_survey?: import("./teach").FeedbackSurvey | null }>(`/api/roleplay/sessions/${id}/end/`, { method: "POST" }),
};

/** Streams the AI character. Same message shape as the mentor chat so voice mode can drive it. */
export function useRolePlaySocket(sessionId: number, initial: ChatMsg[]) {
  // Initial transcript is read once; the player remounts this hook per session.
  const [messages, setMessages] = useState<ChatMsg[]>(() => initial);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [turnsLeft, setTurnsLeft] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    let closed = false;
    let timer: ReturnType<typeof setTimeout>;
    const connect = async () => {
      const token = (await ensureFreshAccess()) ?? useAuth.getState().access;
      if (closed || !token) return;
      const sock = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/roleplay/`);
      ws.current = sock;
      sock.onopen = () => sock.send(JSON.stringify({ type: "auth", token }));
      sock.onclose = (e) => {
        setReady(false);
        setBusy(false);
        if (!closed) timer = setTimeout(connect, e.code === TOKEN_EXPIRED ? 0 : 1500); // expired token: reconnect now with a fresh one
      };
      sock.onmessage = (e) => {
        const ev = JSON.parse(e.data);
        if (ev.type === "ready") setReady(true);
        else if (ev.type === "start") {
          mascot.react("thinking", 0);
          setMessages((m) => [...m, { id: `c-${Date.now()}`, role: "assistant", content: "", streaming: true }]);
        } else if (ev.type === "delta") {
          setMessages((m) => {
            const last = m[m.length - 1];
            return last?.streaming ? [...m.slice(0, -1), { ...last, content: last.content + ev.text }] : m;
          });
        } else if (ev.type === "status" && ev.state === "searching") {
          mascot.react("thinking", 0); // the character is looking something up on the web
        } else if (ev.type === "done") {
          setBusy(false);
          setTurnsLeft(ev.turns_left);
          mascot.react("idle");
          // Web pages the character's search used (from the server's search results, never the model's text).
          const citations = Array.isArray(ev.sources) && ev.sources.length
            ? ev.sources.map((src: { title: string; url: string }) => ({ kind: "web" as const, title: src.title, url: src.url }))
            : undefined;
          setMessages((m) => m.map((x) => (x.streaming ? { ...x, streaming: false, id: ev.turn_id ?? x.id, citations } : x)));
        } else if (ev.type === "error" && ev.code !== "token_expired") {
          setBusy(false);
          setError(ev.code);
          setMessages((m) => m.filter((x) => !(x.streaming && !x.content)));
        }
      };
    };
    void connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      ws.current?.close();
    };
  }, [sessionId]);

  const send = useCallback(
    (text: string) => {
      if (!ws.current || ws.current.readyState !== WebSocket.OPEN || busy) return false;
      setError(null);
      setBusy(true);
      setMessages((m) => [...m, { id: `l-${Date.now()}`, role: "user", content: text }]);
      ws.current.send(JSON.stringify({ type: "message", session_id: sessionId, text }));
      return true;
    },
    [busy, sessionId],
  );
  const cancel = useCallback(() => ws.current?.send(JSON.stringify({ type: "cancel" })), []);
  return { messages, ready, busy, turnsLeft, error, send, cancel };
}
