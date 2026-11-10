import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, AudioLines, Mic, MicOff, Plus, Square, Volume2, X } from "lucide-react";
import { useEffect, useRef, useState, useSyncExternalStore, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { AnswerFeedback } from "@/components/AnswerFeedback";
import { WebSources } from "@/components/WebSources";
import { Md } from "@/components/Md";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useMentorSocket, type ChatMsg } from "@/lib/useMentorSocket";
import { useMe, useUpdatePreferences } from "@/lib/useMe";
import { useFillViewport } from "@/lib/useFillViewport";
import { Kili } from "@/mascot/Kili";
import { useMascot } from "@/mascot/store";
import { VOICE_ERRORS, useVoiceMode, voiceDebug } from "@/voice/useVoiceMode";

import { VoiceConversation } from "./mentor/VoiceConversation";

/** The browser can open a microphone at all (server STT still needs one). Checked without asking for it. */
const canUseMic = () => typeof navigator !== "undefined" && typeof navigator.mediaDevices?.getUserMedia === "function";

/** A small on/off switch with a 44 px target. */
function Toggle({ on, onChange, icon, label, hint }: { on: boolean; onChange: (v: boolean) => void; icon: ReactNode; label: string; hint?: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} onClick={() => onChange(!on)} title={hint}
      className="flex min-h-11 min-w-0 items-center gap-2 rounded-full px-2 text-sm font-semibold text-muted hover:text-ink focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/40">
      <span aria-hidden className={cn("relative inline-flex h-6 w-10 shrink-0 rounded-full transition", on ? "bg-accent" : "bg-line")}>
        <span className={cn("absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all", on ? "left-[1.125rem]" : "left-0.5")} />
      </span>
      {icon}
      <span className="truncate">{label}</span>
      {hint && <span className="sr-only">{hint}</span>}
    </button>
  );
}

/** `?voicedebug=1`: what the mic and the browser recogniser did, to pin down a voice problem. */
function VoiceDebugPanel() {
  const lines = useSyncExternalStore(voiceDebug.subscribe, () => voiceDebug.lines.length);
  if (!voiceDebug.on) return null;
  return (
    <details open className="mx-auto mb-2 w-full max-w-3xl rounded-xl border border-line bg-surface p-2 text-xs" data-testid="voice-debug">
      <summary className="cursor-pointer font-semibold">Voice log ({lines})</summary>
      <pre className="max-h-40 overflow-auto whitespace-pre-wrap">{voiceDebug.lines.join("\n") || "Tap the mic and speak…"}</pre>
    </details>
  );
}

export default function MentorPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const updatePrefs = useUpdatePreferences();
  const [conversationId, setConversationId] = useState<number | null>(id ? Number(id) : null);
  const [text, setText] = useState("");
  const [micOk, setMicOk] = useState(canUseMic);
  const endRef = useRef<HTMLDivElement>(null);
  const pageRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fill = useFillViewport(pageRef); // keep the message box on screen below the top bar and any banner
  const pendingAsk = useRef<string | null>((location.state as { ask?: string } | null)?.ask ?? null);

  const chat = useMentorSocket({
    conversationId,
    onConversation: (cid) => {
      if (cid !== conversationId) {
        setConversationId(cid);
        navigate(`/mentor/${cid}`, { replace: true, state: null });
        void qc.invalidateQueries({ queryKey: ["conversations"] });
      }
    },
  });

  const voicePrefs = me?.preferences.voice;
  // The voice conversation is on (inside the chat, like ChatGPT voice). Outside it, voice only reads typed answers aloud.
  const [voiceOpen, setVoiceOpen] = useState(false);
  const readAloud = voicePrefs?.mentor_read_aloud ?? true;
  // A spoken question is sent once, marked as voice so the reply comes back short and made for listening. If it
  // can't go out (still finishing the last reply), the words land in the text box instead of being lost.
  const sendSpoken = (q: string) => {
    if (chat.send(q, { via: "voice" })) return true;
    setText(q);
    return false;
  };
  const voice = useVoiceMode({
    messages: chat.messages,
    send: sendSpoken,
    cancel: chat.cancel,
    lang: "en", // Ask Aasan's voice is English only: it listens and speaks in English.
    mode: voiceOpen ? "conversation" : "tap",
    speak: voiceOpen || readAloud,
    codeCue: t("mentor.voice.codeCue"),
    busy: chat.busy,
    activity: chat.activity,
  });
  const mouth = useMascot((s) => s.mouth);

  // The URL is the source of truth: /mentor/5 → /mentor (or another id) switches conversation, not just the address bar.
  const routeId = id ? Number(id) : null;
  useEffect(() => {
    if (routeId === conversationId) return;
    setConversationId(routeId);
    chat.setMessages([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeId]);

  const history = useQuery({
    queryKey: ["conversation", id],
    queryFn: () => api<{ messages: ChatMsg[] }>(`/api/assistant/conversations/${id}/`),
    enabled: !!id && chat.messages.length === 0,
  });
  useEffect(() => {
    if (history.data && chat.messages.length === 0) chat.setMessages(history.data.messages);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history.data]);

  // Auto-send a question handed over from Home.
  useEffect(() => {
    if (chat.status === "ready" && pendingAsk.current) {
      chat.send(pendingAsk.current);
      pendingAsk.current = null;
    }
  }, [chat.status, chat]);

  useEffect(() => {
    // Braces matter: newer browsers return a Promise from scrollIntoView, which React would treat as a cleanup fn.
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [chat.messages, voice.interim]);

  // The mic is blocked or this browser can't listen: say so, and fall back to typing.
  const voiceError = voice.error;
  useEffect(() => {
    if (voiceError !== "mic_denied" && voiceError !== "browser_stt_unsupported") return;
    // React to the voice hook's error (an external system) once it lands; the effect only flips local UI.
    void Promise.resolve().then(() => {
      if (voiceError === "browser_stt_unsupported") setMicOk(false);
      inputRef.current?.focus();
    });
  }, [voiceError]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const q = text.trim();
    if (!q) return;
    voice.hush(); // typing over Aasan stops the voice
    if (chat.send(q)) setText("");
  };

  const last = chat.messages.at(-1);
  const streaming = last?.role === "assistant" && !!last.streaming;
  const listening = voice.listening;
  const hostTalking = voice.state === "speaking" || streaming || (chat.busy && !listening);
  const offline = chat.status !== "ready";

  /** Open the voice conversation. Voice starts inside the tap, so Aasan's answers are allowed to play. */
  function openVoice() {
    if (voice.active) voice.stop(); // reading a typed answer aloud: start over as a conversation
    setVoiceOpen(true);
    void voice.start("conversation");
  }
  function closeVoice() {
    voice.stop();
    setVoiceOpen(false);
  }
  function typeInstead() {
    closeVoice();
    requestAnimationFrame(() => inputRef.current?.focus());
  }
  function stopReply() {
    if (voice.active) voice.interrupt();
    else chat.cancel();
  }
  function setReadAloud(v: boolean) {
    updatePrefs.mutate({ voice: { mentor_read_aloud: v } });
    if (v && !voice.active) void voice.start(); // unlock audio now so typed answers are read too
  }

  const status =
    voice.state === "starting" ? t("mentor.voice.states.starting")
      : voice.state === "speaking" ? t("mentor.voice.states.speakingTap")
        : chat.busy ? t(chat.activity === "searching" ? "mentor.web.searching" : "mentor.voice.states.thinking")
          : t("mentor.voice.states.ready");

  const errorText = chat.error ? t(`mentor.errors.${["rate_limited", "provider_not_configured", "plan_limit", "server_error", "guardian_consent_required"].includes(chat.error) ? chat.error : "generic"}`) : null;
  const color = me?.preferences.mascot.color;
  // The words the learner is saying right now, shown as their own message while they talk (voice conversation only).
  const liveWords = voiceOpen ? voice.interim : "";

  return (
    <div ref={pageRef} style={{ height: fill }} className="mx-auto flex h-[calc(100dvh-57px)] w-full min-w-0 max-w-3xl flex-col px-4 md:h-dvh">
      <header className="flex items-center justify-between gap-2 py-4">
        <h1 className="font-display text-2xl font-bold">{t("mentor.title")}</h1>
        <button
          onClick={() => {
            voice.hush();
            setVoiceOpen(false);
            setConversationId(null);
            chat.setMessages([]);
            navigate("/mentor", { replace: true });
          }}
          className="flex min-h-11 items-center gap-1 rounded-xl border-2 border-line px-3 py-1.5 text-sm font-semibold hover:border-accent"
        >
          <Plus className="h-4 w-4" /> {t("mentor.new")}
        </button>
      </header>

      <div className="min-w-0 flex-1 space-y-4 overflow-y-auto overflow-x-hidden pb-4" aria-live="polite">
        {chat.messages.length === 0 && (
          <div className="flex flex-col items-center gap-3 pt-10 text-center text-muted">
            <Kili mood="wave" size={110} color={color} />
            <p>{t("mentor.empty")}</p>
          </div>
        )}
        {chat.messages.map((m) => (
          <div key={m.id} className={cn("flex min-w-0 gap-2", m.role === "user" ? "justify-end" : "justify-start")}>
            {m.role === "assistant" && (
              <div className="mt-1 shrink-0">
                <Kili mood={m.streaming ? "talking" : "idle"} size={36} color={color} mouth={m.streaming || m === chat.messages[chat.messages.length - 1] ? mouth : null} />
              </div>
            )}
            <div
              className={cn(
                "min-w-0 max-w-[85%] break-words rounded-2xl px-4 py-2.5 [overflow-wrap:anywhere]",
                m.role === "user" ? "rounded-br-sm bg-accent text-accent-ink" : "rounded-bl-sm border border-line bg-surface",
              )}
            >
              {m.role === "assistant" ? (
                m.content ? (
                  <>
                    <div className="prose-chat">
                      <Md ai>{m.content}</Md>
                    </div>
                    {!m.streaming && <AnswerFeedback kind="message" id={m.id} initial={m.my_rating} />}
                    {!m.streaming && <WebSources citations={m.citations} />}
                  </>
                ) : (
                  <span className="text-muted">{m.streaming && chat.activity === "searching" ? t("mentor.web.searching") : t("mentor.thinking")}</span>
                )
              ) : (
                <p className="whitespace-pre-wrap">{m.content}</p>
              )}
            </div>
          </div>
        ))}
        {liveWords && (
          <div className="flex min-w-0 justify-end">
            <p aria-live="polite" data-testid="me-caption"
              className="min-w-0 max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-sm bg-accent/60 px-4 py-2.5 text-accent-ink [overflow-wrap:anywhere]">
              <span className="sr-only">{t("mentor.voice.you")}: </span>{liveWords}
              <span aria-hidden className="ml-1 inline-block h-4 w-0.5 translate-y-0.5 animate-pulse bg-accent-ink/70" />
            </p>
          </div>
        )}
        {errorText && (
          <p role="alert" className="flex flex-wrap items-center justify-center gap-2 text-center text-sm text-bad">
            {errorText}
            {chat.error !== "plan_limit" && chat.error !== "provider_not_configured" && (
              <button type="button" onClick={() => chat.retry()} disabled={chat.status !== "ready" || chat.busy} className="min-h-11 rounded-lg border-2 border-bad px-3 font-semibold disabled:opacity-50">
                {t("mentor.retry")}
              </button>
            )}
          </p>
        )}
        {chat.status === "connecting" && <p role="status" className="text-center text-sm text-muted">{t("mentor.connecting")}</p>}
        {chat.status === "offline" && <p role="status" className="text-center text-sm text-muted">{t("mentor.errors.offline")}</p>}
        <div ref={endRef} />
      </div>

      <div role={voiceOpen ? "region" : undefined} aria-label={voiceOpen ? t("mentor.voice.conversation.title") : undefined} data-testid={voiceOpen ? "voice-conversation" : undefined}
        className="mb-28 min-w-0 space-y-2 md:mb-6 md:mr-32">
        {/* Captions while a typed answer is read aloud (in a voice conversation the answer streams into the chat). */}
        {voice.active && !voiceOpen && (voice.saying || voice.state === "speaking") && (
          <div className="min-w-0 rounded-2xl border-2 border-accent/60 bg-accent/10 px-4 py-2 text-center" data-testid="voice-caption">
            <p role="status" aria-live="polite" className="flex items-center justify-center gap-2 text-sm font-medium text-muted" data-testid="voice-status">
              {status}
            </p>
            <p aria-live="polite" aria-atomic="true" className="min-h-6 break-words text-base [overflow-wrap:anywhere]">
              {voice.saying ? (
                <mark className="rounded bg-accent/25 px-1 text-ink" data-testid="saying-caption"><span className="sr-only">{t("mentor.voice.aasanSays")}: </span>{voice.saying}</mark>
              ) : null}
            </p>
          </div>
        )}
        <VoiceDebugPanel />
        {voice.error && !voiceOpen && (
          <p role="alert" className="text-center text-sm text-bad">
            {t(`mentor.voice.errors.${VOICE_ERRORS.includes(voice.error) ? voice.error : "generic"}`)}
            {(voice.error === "mic_denied" || voice.error === "browser_stt_unsupported") && <> {t("mentor.voice.typeInstead")}</>}
          </p>
        )}
        {!micOk && !voice.error && <p className="text-center text-sm text-muted" data-testid="no-mic">{t("mentor.voice.noMic")}</p>}

        {voiceOpen && (
          <VoiceConversation voice={voice} hostTalking={hostTalking}
            onEnd={closeVoice} onType={typeInstead} showMascot={me?.preferences.mascot.enabled ?? true} color={color}
            reducedMotion={!!me?.preferences.appearance.reduced_motion} />
        )}

        {/* The message bar, always there (ChatGPT style): type any time. Empty: the voice button. Text: Send.
            Aasan answering a typed question: Stop. In a voice conversation: Mute and End sit in the bar. */}
        <form onSubmit={submit} data-testid="type-form"
          className="flex min-w-0 items-end gap-1.5 rounded-[1.75rem] border-2 border-line bg-surface p-1.5 pl-3 shadow-sm focus-within:border-accent">
          <textarea
            ref={inputRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            rows={1}
            placeholder={t("mentor.placeholder")}
            aria-label={t("mentor.placeholder")}
            className="max-h-40 min-h-11 min-w-0 flex-1 resize-none bg-transparent px-1 py-2.5 outline-none"
          />
          {voiceOpen ? (
            <>
              {text.trim() && (
                <BarButton label={t("mentor.send")} type="submit" disabled={offline || chat.busy} className="bg-accent text-accent-ink">
                  <ArrowUp className="h-5 w-5" aria-hidden />
                </BarButton>
              )}
              <BarButton label={voice.micMuted ? t("mentor.voice.conversation.unmute") : t("mentor.voice.conversation.mute")} pressed={voice.micMuted}
                onClick={() => void voice.mute(!voice.micMuted)} className={voice.micMuted ? "bg-ink text-bg" : "bg-bg text-ink hover:bg-line/60"}>
                {voice.micMuted ? <MicOff className="h-5 w-5" aria-hidden /> : <Mic className="h-5 w-5" aria-hidden />}
              </BarButton>
              <BarButton label={t("mentor.voice.conversation.end")} onClick={closeVoice} className="bg-accent text-accent-ink" testId="voice-end">
                <X className="h-5 w-5" aria-hidden />
              </BarButton>
            </>
          ) : hostTalking ? (
            <BarButton label={t("mentor.voice.stopTalking")} onClick={stopReply} className="bg-ink text-bg">
              <Square className="h-4 w-4 fill-current" aria-hidden />
            </BarButton>
          ) : text.trim() || !micOk ? (
            <BarButton label={t("mentor.send")} type="submit" disabled={!text.trim() || offline || chat.busy} className="bg-accent text-accent-ink">
              <ArrowUp className="h-5 w-5" aria-hidden />
            </BarButton>
          ) : (
            <BarButton label={t("mentor.voice.conversation.open")} onClick={openVoice} disabled={offline} className="bg-accent text-accent-ink" testId="open-voice">
              <AudioLines className="h-5 w-5" aria-hidden />
            </BarButton>
          )}
        </form>

        {micOk && !voiceOpen && (
          <div className="flex min-w-0 flex-wrap items-center justify-center gap-x-3">
            <Toggle on={readAloud} onChange={setReadAloud} icon={<Volume2 className="h-4 w-4 shrink-0" aria-hidden />} label={t("mentor.voice.readAloud")} />
          </div>
        )}
      </div>
    </div>
  );
}

/** A round button inside the message bar: 44 px target, label for screen readers and as a tooltip. */
function BarButton({ label, onClick, children, className, disabled, pressed, testId, type = "button" }: {
  label: string; onClick?: () => void; children: ReactNode; className?: string; disabled?: boolean; pressed?: boolean; testId?: string;
  type?: "button" | "submit";
}) {
  return (
    <button type={type} onClick={onClick} disabled={disabled} aria-label={label} aria-pressed={pressed} title={label} data-testid={testId}
      className={cn("grid h-11 w-11 shrink-0 place-items-center rounded-full transition hover:brightness-105 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/40 disabled:opacity-40", className)}>
      {children}
    </button>
  );
}
