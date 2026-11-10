import { Bot, Keyboard, Mic, MoreVertical, Send, Square, Volume2, WifiOff, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { currentStage, hasAgentStage, paceOf, stageProgress, type Chip, type FinalResult, type Session, type useWorkshopSocket } from "@/lib/workshops";
import { Kili } from "@/mascot/Kili";
import { useMascot } from "@/mascot/store";
import type { useVoiceMode } from "@/voice/useVoiceMode";

import { ActivityCard } from "./ActivityCard";
import { AgentBuilder } from "./AgentBuilder";
import { Caption } from "./Caption";
import { LiveMenu } from "./LiveMenu";
import { PaceBanner } from "./PaceBanner";
import { ProgressBar } from "./StageRail";
import { StaffNudges } from "./StaffNudge";
import { SuggestionChips } from "./SuggestionChips";
import { useDialogFocus } from "./useDialogFocus";

export type Sock = ReturnType<typeof useWorkshopSocket>;
export type Voice = ReturnType<typeof useVoiceMode>;

/** "Your agent" in the stages after the agent builder: the same builder in a side drawer (full screen on a phone). */
function AgentDrawer({ sessionId }: { sessionId: number }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="outline" className="min-h-11 py-2" onClick={() => setOpen(true)} aria-haspopup="dialog"><Bot className="h-5 w-5" aria-hidden /> {t("workshop.agent.drawer")}</Button>
      {open && <AgentDrawerPanel sessionId={sessionId} onClose={() => setOpen(false)} />}
    </>
  );
}

function AgentDrawerPanel({ sessionId, onClose }: { sessionId: number; onClose: () => void }) {
  const { t } = useTranslation();
  const panel = useRef<HTMLDivElement>(null);
  useDialogFocus(panel, onClose);
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={onClose}>
      <div ref={panel} role="dialog" aria-modal="true" aria-label={t("workshop.agent.drawer")} className="h-full w-full max-w-2xl overflow-y-auto bg-bg p-3 shadow-xl md:p-5" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between gap-2">
          <p className="font-display text-xl font-bold">{t("workshop.agent.drawer")}</p>
          <Button variant="ghost" className="min-h-11 px-2.5" onClick={onClose} aria-label={t("workshop.agent.close")}><X className="h-5 w-5" aria-hidden /></Button>
        </div>
        <AgentBuilder sessionId={sessionId} />
      </div>
    </div>
  );
}

/** One big mic (tap to talk / tap to send / Stop), with typing one tap away. */
function TalkBar({ sock, voice, handsFree, onTalk, onStop, onType }: { sock: Sock; voice: Voice; handsFree: boolean; onTalk: () => void; onStop: () => void; onType: (text: string) => boolean }) {
  const { t } = useTranslation();
  const [typing, setTyping] = useState(false);
  const [typed, setTyped] = useState("");
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (typing) input.current?.focus();
  }, [typing]);
  const last = sock.messages.at(-1);
  const streaming = last?.role === "assistant" && !!last.streaming;
  const hostTalking = voice.state === "speaking" || streaming || (sock.busy && !voice.listening);
  const listening = voice.listening;
  const status =
    voice.state === "transcribing" ? t("workshop.states.transcribing")
      : voice.state === "hearing" ? t("workshop.states.hearing")
        : listening ? (handsFree ? t("workshop.states.handsfree") : t("workshop.states.listening"))
          : voice.state === "starting" ? t("workshop.states.starting")
            : voice.state === "speaking" || (streaming && !!last?.content) ? t("workshop.states.talking")
              : sock.busy ? t("workshop.states.thinking")
                : t("workshop.states.tap");

  function submit(e: FormEvent) {
    e.preventDefault();
    const text = typed.trim();
    if (text && onType(text)) setTyped("");
  }

  const offline = sock.status !== "ready";
  return (
    <div className="w-full space-y-3">
      <p role="status" aria-live="polite" className="text-center text-base font-medium text-muted" data-testid="voice-status">{status}</p>
      <div className="flex flex-wrap items-center justify-center gap-3">
        {listening ? (
          <button type="button" onClick={() => voice.finish()} className="flex min-h-16 min-w-52 items-center justify-center gap-3 rounded-full bg-bad px-7 text-lg font-bold text-white shadow-lg focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-bad/40">
            <span className="relative flex h-4 w-4"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-white opacity-75" /><span className="relative inline-flex h-4 w-4 rounded-full bg-white" /></span>
            {t("workshop.live.tapToSend")}
          </button>
        ) : hostTalking ? (
          <button type="button" onClick={onStop} className="flex min-h-16 min-w-52 items-center justify-center gap-3 rounded-full border-2 border-ink bg-surface px-7 text-lg font-bold shadow-lg focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/40">
            <Square className="h-5 w-5 fill-current" aria-hidden /> {t("workshop.live.stop")}
          </button>
        ) : (
          <button type="button" onClick={onTalk} disabled={offline || voice.state === "starting" || voice.state === "transcribing"}
            className="flex min-h-16 min-w-52 items-center justify-center gap-3 rounded-full bg-accent px-7 text-lg font-bold text-accent-ink shadow-lg transition hover:brightness-105 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/40 disabled:opacity-50">
            <Mic className="h-6 w-6" aria-hidden /> {t("workshop.live.tapToTalk")}
          </button>
        )}
        <button type="button" onClick={() => setTyping((v) => !v)} aria-expanded={typing}
          className="flex min-h-11 items-center gap-2 rounded-full border-2 border-line bg-surface px-4 font-semibold hover:border-accent focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/40">
          <Keyboard className="h-5 w-5" aria-hidden /> {typing ? t("workshop.live.hideType") : t("workshop.live.type")}
        </button>
      </div>
      {voice.error && <p role="alert" className="text-center text-sm text-bad">{t(`mentor.voice.errors.${voice.error}`, { defaultValue: t("mentor.errors.generic") })}</p>}
      {typing && (
        <form onSubmit={submit} className="mx-auto flex w-full max-w-xl gap-2">
          <input ref={input} value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={t("workshop.typePh")} aria-label={t("workshop.typePh")} maxLength={2000}
            className="min-h-11 min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2.5 text-base outline-none focus:border-accent" />
          <button className="min-h-11 min-w-11 rounded-xl bg-accent p-3 text-accent-ink disabled:opacity-50" disabled={!typed.trim() || offline} aria-label={t("mentor.send")}><Send className="h-5 w-5" aria-hidden /></button>
        </form>
      )}
    </div>
  );
}

export interface LiveStageProps {
  session: Session;
  sock: Sock;
  voice: Voice;
  handsFree: boolean;
  onHandsFree: (v: boolean) => void;
  onSession: (s: Session) => void;
  onResult: (r: FinalResult) => void;
}

/**
 * The live workshop, one column on every screen: a slim header with progress and the ⋮ menu, the big lip-synced
 * companion, its live caption, the activity only when the stage needs one, the replies it suggests, and one mic.
 * The host leads; nothing here moves the learner on without their "yes".
 */
export function LiveStage({ session, sock, voice, handsFree, onHandsFree, onSession, onResult }: LiveStageProps) {
  const { t } = useTranslation();
  const stage = currentStage(session)!;
  const mood = useMascot((s) => s.mood);
  const mouth = useMascot((s) => s.mouth);
  const pace = paceOf(session, sock.pace);
  const pct = stageProgress(session);
  const [menu, setMenu] = useState(false);
  const [hand, setHand] = useState(false);
  // The learner turned reading-aloud off: taps don't switch the voice back on by themselves.
  const [muted, setMuted] = useState(false);
  useEffect(() => {
    if (!hand) return;
    const id = setTimeout(() => setHand(false), 8000);
    return () => clearTimeout(id);
  }, [hand]);
  const agentAt = session.stages.findIndex((x) => x.kind === "agent_build");
  const agentLater = hasAgentStage(session) && session.stage_index > agentAt;
  const language = session.language === "ta" ? "ta" : "en";

  const hostLine = [...sock.messages].reverse().find((m) => m.role === "assistant" && !m.streaming && m.content)?.content ?? "";
  async function hear() {
    await voice.start();
    voice.speakText(hostLine);
  }
  /** Voice on (inside the tap, so audio may play), unless the learner muted it. */
  const wake = () => {
    if (!voice.active && !muted) void voice.start();
  };
  async function talk() {
    setMuted(false);
    if (!voice.active) await voice.start();
    void voice.listen();
  }
  function stop() {
    if (voice.active) voice.interrupt();
    else sock.cancel();
  }
  function chip(c: Chip) {
    voice.hush();
    wake();
    if (c === "done") {
      const at = stage.cursor ?? stage.steps.findIndex((x) => !x.done);
      if (at >= 0) sock.stepDone(at);
      return;
    }
    sock.control(c);
  }
  function type(text: string) {
    voice.hush();
    wake();
    return sock.say(text);
  }
  function mascotTap() {
    if (voice.listening) return voice.finish();
    void talk();
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl min-w-0 flex-col items-center gap-4 px-4 py-3 pb-28 md:pb-8">
      <header className="w-full min-w-0 space-y-2">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <h1 className="break-words font-display text-lg font-bold leading-snug md:text-xl">{session.workshop.title}</h1>
            <p className="text-sm text-muted">
              {t("workshop.live.stepOf", { n: Math.min(session.stage_index + 1, session.stages.length), total: session.stages.length })}
              {" · "}<span className="font-semibold text-ink">{t(`workshop.kind.${stage.kind}`)}</span>
            </p>
          </div>
          {sock.status === "offline" && <span role="status" className="flex shrink-0 items-center gap-1.5 rounded-full bg-surface-2 px-3 py-1 text-sm text-muted"><WifiOff className="h-4 w-4" aria-hidden /> <span className="sr-only md:not-sr-only">{t("workshop.offline")}</span></span>}
          <button type="button" onClick={() => setMenu(true)} aria-haspopup="dialog" aria-label={t("workshop.live.menu")} title={t("workshop.live.menu")}
            className="grid min-h-11 min-w-11 shrink-0 place-items-center rounded-xl border-2 border-line bg-surface hover:border-accent focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/40">
            <MoreVertical className="h-5 w-5" aria-hidden />
          </button>
        </div>
        <ProgressBar pct={pct} label={t("workshop.rail.progress")} />
        <h2 className="break-words text-base font-semibold">{stage.title}</h2>
        {agentLater && <AgentDrawer sessionId={session.id} />}
      </header>

      <div className="w-full space-y-2">
        <StaffNudges nudges={sock.nudges} onDismiss={sock.dismissNudge} />
        <PaceBanner status={pace?.status ?? null} minutesLeft={pace?.minutesLeft} />
        {sock.paused && <p role="status" className="rounded-2xl bg-surface-2 px-4 py-2.5 text-base">{t(`workshop.paused.${sock.paused}`)}</p>}
        {sock.error && <p role="alert" className="text-center text-sm text-bad">{t(`workshop.err.${sock.error}`, { defaultValue: t("mentor.errors.generic") })}</p>}
      </div>

      <button type="button" onClick={mascotTap} aria-label={t("workshop.live.mascotHint")} title={t("workshop.live.mascotHint")} data-testid="mascot"
        className="rounded-full p-1 transition focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/40">
        <Kili mood={mood} mouth={mouth} size={stage.kind === "assessment" ? 120 : 190} />
      </button>

      {/* Browsers only allow audio after a tap. Coming back to a started session, the host would talk silently, so
          offer one clear tap that turns the voice on and reads the latest line aloud. */}
      {!voice.active && !muted && hostLine && (
        <button type="button" onClick={() => void hear()} className="mx-auto flex min-h-12 items-center gap-2 rounded-full bg-accent px-5 text-base font-bold text-accent-ink shadow focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/40">
          <Volume2 className="h-5 w-5" aria-hidden /> {t("workshop.live.hear")}
        </button>
      )}
      <Caption messages={sock.messages} busy={sock.busy} interim={voice.interim} />

      <ActivityCard session={session} stage={stage} onStepDone={(i) => sock.stepDone(i)} onSession={onSession} onResult={onResult} />

      <SuggestionChips chips={sock.suggest} disabled={sock.sending || sock.status !== "ready"} onChip={chip} />

      {stage.kind !== "assessment" && <TalkBar sock={sock} voice={voice} handsFree={handsFree} onTalk={() => void talk()} onStop={stop} onType={type} />}

      {menu && (
        <LiveMenu
          session={session} messages={sock.messages} language={language} handsFree={handsFree} sound={voice.active} handRaised={hand} online={sock.status === "ready"}
          onClose={() => setMenu(false)}
          onRaiseHand={() => sock.raiseHand() && setHand(true)}
          onLanguage={(l) => {
            voice.hush();
            wake();
            sock.control(l === "ta" ? "tamil" : "english");
          }}
          onHandsFree={(v) => {
            onHandsFree(v);
            if (v) {
              setMuted(false);
              if (!voice.active) void voice.start();
            }
          }}
          onSound={(v) => {
            setMuted(!v);
            if (v) void voice.start();
            else voice.stop();
          }}
        />
      )}
    </div>
  );
}
