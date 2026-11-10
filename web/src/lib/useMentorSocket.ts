import { useCallback, useEffect, useRef, useState } from "react";

import { mascot, type MascotMood } from "@/mascot/store";
import { useAuth } from "@/stores/auth";

import { ensureFreshAccess } from "./api";
import { announcePlanLimit, type PlanLimitError } from "./billing";
import type { Citation } from "./citations";

export type { Citation, DocCitation, WebSource } from "./citations";

export interface ChatMsg {
  id: string | number;
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
  citations?: Citation[];
  my_rating?: number;
}

/** What the reply is doing before its words arrive. */
export type ReplyActivity = "searching" | null;

type Status = "connecting" | "ready" | "offline";

export interface SendOpts {
  via?: "voice";
}

/** Close code the server uses when the access token behind a socket expires. */
export const TOKEN_EXPIRED = 4401;
/** Close code for a refusal that reconnecting can't change (feature switched off, guardian consent pending). */
const FORBIDDEN = 4403;

type ServerEvent =
  | { type: "ready" }
  | { type: "start"; conversation_id: number }
  | { type: "delta"; text: string }
  | { type: "status"; state: "searching" }
  | { type: "done"; message_id?: number; stop_reason?: string; citations?: Citation[] }
  | { type: "nudge"; text: string; link: string }
  | { type: "mascot"; state: MascotMood }
  | { type: "error"; code: string; retryable?: boolean };

/** One WS per mounted chat; reconnects with backoff and re-auths each time. */
export function useMentorSocket(opts: { conversationId: number | null; onConversation: (id: number) => void; documentId?: number }) {
  const [status, setStatus] = useState<Status>("connecting");
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activity, setActivity] = useState<ReplyActivity>(null);
  const ws = useRef<WebSocket | null>(null);
  const onConv = useRef(opts.onConversation);
  useEffect(() => {
    onConv.current = opts.onConversation;
  }, [opts.onConversation]);

  useEffect(() => {
    let closed = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout>;

    const connect = async () => {
      setStatus("connecting");
      const token = (await ensureFreshAccess()) ?? useAuth.getState().access;
      if (closed) return;
      if (!token) {
        // No session yet (e.g. right after sign-up, while the refresh cookie settles): try again, never give up silently.
        setStatus("offline");
        timer = setTimeout(connect, Math.min(10_000, 500 * 2 ** attempt++));
        return;
      }
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const sock = new WebSocket(`${proto}://${location.host}/ws/assistant/`);
      ws.current = sock;
      sock.onopen = () => sock.send(JSON.stringify({ type: "auth", token }));
      sock.onmessage = (e) => handle(JSON.parse(e.data) as ServerEvent);
      sock.onclose = (e) => {
        setBusy(false);
        setActivity(null);
        setMessages((m) => m.map((x) => (x.streaming ? { ...x, streaming: false } : x)));
        // 4403 = refused for good (switched off by the school, or waiting for a guardian): the error says why;
        // reconnecting can't change it, so don't show "connection lost" or retry (a reload tries again).
        if (e.code === FORBIDDEN) return;
        setStatus("offline");
        // 4401 = the token was refused (usually expired): reconnect straight away once, as connect() fetches a fresh
        // one; if it keeps being refused, back off like any other failure instead of looping.
        const now = e.code === TOKEN_EXPIRED && attempt === 0;
        if (!closed) timer = setTimeout(connect, now ? 0 : Math.min(10_000, 500 * 2 ** attempt));
        attempt++;
      };
    };

    const handle = (ev: ServerEvent) => {
      switch (ev.type) {
        case "ready":
          attempt = 0;
          setStatus("ready");
          break;
        case "status":
          setActivity(ev.state === "searching" ? "searching" : null);
          break;
        case "start":
          setActivity(null);
          onConv.current(ev.conversation_id);
          setMessages((m) => [...m, { id: `a-${Date.now()}`, role: "assistant", content: "", streaming: true }]);
          break;
        case "delta":
          setActivity(null);
          setMessages((m) => {
            const last = m[m.length - 1];
            return last?.streaming ? [...m.slice(0, -1), { ...last, content: last.content + ev.text }] : m;
          });
          break;
        case "done":
          setBusy(false);
          setActivity(null);
          setMessages((m) => m.map((x) => (x.streaming ? { ...x, streaming: false, id: ev.message_id ?? x.id, citations: ev.citations } : x)));
          break;
        case "mascot":
          mascot.react(ev.state, ev.state === "thinking" || ev.state === "talking" ? 0 : undefined);
          break;
        case "error":
          setBusy(false);
          setActivity(null);
          if (ev.code === "token_expired") break; // the socket closes next and reconnects with a fresh token
          setError(ev.code);
          if (ev.code === "plan_limit") announcePlanLimit(ev as unknown as PlanLimitError);
          setMessages((m) => m.filter((x) => !(x.streaming && !x.content)));
          break;
      }
    };

    void connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      ws.current?.close();
      mascot.react("idle");
    };
  }, []);

  const lastSent = useRef<string | null>(null);
  const lastVia = useRef<SendOpts["via"]>(undefined);
  /** `via: "voice"`: the learner spoke it, so the server shapes the reply for listening. */
  const send = useCallback(
    (text: string, sendOpts?: SendOpts) => {
      if (!ws.current || ws.current.readyState !== WebSocket.OPEN || busy) return false;
      lastSent.current = text;
      lastVia.current = sendOpts?.via;
      setError(null);
      setBusy(true);
      setMessages((m) => [...m, { id: `u-${Date.now()}`, role: "user", content: text }]);
      ws.current.send(
        JSON.stringify({ type: "message", text, conversation_id: opts.conversationId, document_id: opts.documentId, ...(sendOpts?.via ? { via: sendOpts.via } : {}) }),
      );
      return true;
    },
    [busy, opts.conversationId, opts.documentId],
  );

  const cancel = useCallback(() => ws.current?.send(JSON.stringify({ type: "cancel" })), []);

  /** Ask the last question again after an error (its unanswered copy is replaced, not duplicated). */
  const retry = useCallback(() => {
    const text = lastSent.current;
    if (!text || !ws.current || ws.current.readyState !== WebSocket.OPEN || busy) return false;
    setMessages((m) => (m.at(-1)?.role === "user" && m.at(-1)?.content === text ? m.slice(0, -1) : m));
    return send(text, { via: lastVia.current });
  }, [busy, send]);

  return { status, messages, setMessages, busy, error, send, cancel, retry, activity };
}
