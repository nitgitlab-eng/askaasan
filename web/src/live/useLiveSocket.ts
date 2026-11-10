import { useCallback, useEffect, useRef, useState } from "react";

import { ensureFreshAccess } from "@/lib/api";
import { announcePlanLimit, type PlanLimitError } from "@/lib/billing";
import type { ChatMsg, ReplyActivity } from "@/lib/useMentorSocket";
import { mascot, type MascotMood } from "@/mascot/store";
import { useAuth } from "@/stores/auth";

export type LiveMode = "camera" | "screen" | "none";
export interface LiveSummary { title: string; covered: string[]; mistakes: string[]; next_steps: string[] }
export interface LiveMsg extends ChatMsg { proactive?: boolean; saw?: boolean }
type Status = "connecting" | "ready" | "live" | "ended" | "offline";

type ServerEvent =
  | { type: "ready" }
  | { type: "started"; session_id: number; minutes_left: number | null; lesson: { title: string } | null }
  | { type: "start"; proactive: boolean; saw: boolean }
  | { type: "delta"; text: string }
  | { type: "done"; stop_reason?: string; turn_id?: number | null; sources?: { title: string; url: string }[] }
  | { type: "status"; state: "searching" }
  | { type: "silent" }
  | { type: "frame_ok"; accepted: boolean }
  | { type: "mascot"; state: MascotMood }
  | { type: "summary"; session_id: number; summary: LiveSummary | Record<string, never> }
  | { type: "error"; code: string; retryable?: boolean };

const HEARTBEAT_MS = 30_000;
/** Access tokens last 30 minutes and the server closes the socket (4401) when one expires: re-auth well before that. */
export const REAUTH_MS = 20 * 60_000;

/** One Live Class over /ws/live/. No silent reconnect: a dropped socket ends the class (the server closes the session). */
export function useLiveSocket() {
  const [status, setStatus] = useState<Status>("connecting");
  const [messages, setMessages] = useState<LiveMsg[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activity, setActivity] = useState<ReplyActivity>(null);
  const [session, setSession] = useState<{ id: number; minutesLeft: number | null; startedAt: number } | null>(null);
  const [summary, setSummary] = useState<LiveSummary | null | undefined>(undefined);
  const [frames, setFrames] = useState(0);
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    let closed = false;
    let beat: ReturnType<typeof setInterval> | undefined;
    let reauth: ReturnType<typeof setInterval> | undefined;
    const open = async () => {
      const token = (await ensureFreshAccess()) ?? useAuth.getState().access;
      if (closed || !token) return;
      const sock = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/live/`);
      ws.current = sock;
      sock.onopen = () => sock.send(JSON.stringify({ type: "auth", token }));
      sock.onmessage = (e) => handle(JSON.parse(e.data) as ServerEvent);
      // Same-account re-auth on the open socket; the server answers "ready" and the class carries on.
      reauth = setInterval(async () => {
        const fresh = await ensureFreshAccess();
        if (fresh && sock.readyState === WebSocket.OPEN) sock.send(JSON.stringify({ type: "auth", token: fresh }));
      }, REAUTH_MS);
      sock.onclose = () => {
        clearInterval(beat);
        clearInterval(reauth);
        setBusy(false);
        setActivity(null);
        setStatus((s) => (s === "ended" ? s : "offline"));
        setMessages((m) => m.map((x) => (x.streaming ? { ...x, streaming: false } : x)));
      };
    };
    const handle = (ev: ServerEvent) => {
      switch (ev.type) {
        case "ready":
          setStatus((s) => (s === "live" ? s : "ready")); // a re-auth mid-class also answers "ready"
          break;
        case "started":
          setSession({ id: ev.session_id, minutesLeft: ev.minutes_left, startedAt: Date.now() });
          setStatus("live");
          clearInterval(beat);
          beat = setInterval(() => ws.current?.send(JSON.stringify({ type: "heartbeat" })), HEARTBEAT_MS);
          break;
        case "status":
          setActivity(ev.state === "searching" ? "searching" : null);
          break;
        case "start":
          setActivity(null);
          setMessages((m) => [...m, { id: `a-${Date.now()}`, role: "assistant", content: "", streaming: true, proactive: ev.proactive, saw: ev.saw }]);
          break;
        case "delta":
          setMessages((m) => {
            const last = m[m.length - 1];
            return last?.streaming ? [...m.slice(0, -1), { ...last, content: last.content + ev.text }] : m;
          });
          break;
        case "done": {
          setBusy(false);
          setActivity(null);
          const web = (ev.sources ?? []).map((src) => ({ kind: "web" as const, title: src.title, url: src.url }));
          setMessages((m) => m.map((x) => (x.streaming ? { ...x, streaming: false, id: ev.turn_id ?? x.id, ...(web.length ? { citations: web } : {}) } : x)));
          break;
        }
        case "silent":
          break;
        case "frame_ok":
          if (ev.accepted) setFrames((n) => n + 1);
          break;
        case "mascot":
          mascot.react(ev.state, ev.state === "thinking" || ev.state === "talking" ? 0 : undefined);
          break;
        case "summary":
          setSummary("title" in ev.summary ? (ev.summary as LiveSummary) : null);
          setStatus("ended");
          clearInterval(beat);
          ws.current?.close();
          break;
        case "error":
          setBusy(false);
          setActivity(null);
          setError(ev.code);
          if (ev.code === "plan_limit") announcePlanLimit(ev as unknown as PlanLimitError);
          setMessages((m) => m.filter((x) => !(x.streaming && !x.content)));
          break;
      }
    };
    void open();
    return () => {
      closed = true;
      clearInterval(beat);
      clearInterval(reauth);
      ws.current?.close();
      mascot.react("idle");
    };
  }, []);

  const raw = useCallback((obj: object) => {
    if (ws.current?.readyState !== WebSocket.OPEN) return false;
    ws.current.send(JSON.stringify(obj));
    return true;
  }, []);

  const start = useCallback((opts: { mode: LiveMode; topic: string; lesson_id?: number }) => {
    setError(null);
    return raw({ type: "start", ...opts });
  }, [raw]);

  const sendFrame = useCallback((image: string, reason: "change" | "snapshot") => raw({ type: "frame", image, reason }), [raw]);

  /** Same shape as the mentor socket's send, so the hands-free voice layer can drive it. */
  const say = useCallback((text: string) => {
    if (busy || !raw({ type: "say", text })) return false;
    setError(null);
    setBusy(true);
    setMessages((m) => [...m.map((x) => (x.streaming ? { ...x, streaming: false } : x)), { id: `u-${Date.now()}`, role: "user", content: text }]);
    return true;
  }, [busy, raw]);

  const cancel = useCallback(() => void raw({ type: "cancel" }), [raw]);
  const end = useCallback(() => {
    setSummary(undefined);
    if (!raw({ type: "end" })) setStatus("ended");
  }, [raw]);

  return { status, messages, busy, error, session, summary, frames, start, sendFrame, say, cancel, end, activity };
}
