import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/cn";
import { Kili } from "@/mascot/Kili";
import { useMascot } from "@/mascot/store";
import { VOICE_ERRORS, type useVoiceMode } from "@/voice/useVoiceMode";

type Voice = ReturnType<typeof useVoiceMode>;
type Phase = "starting" | "listening" | "hearing" | "thinking" | "speaking" | "muted";

interface Props {
  voice: Voice;
  /** Aasan is answering: the reply is streaming, being spoken, or about to start. */
  hostTalking: boolean;
  onEnd: () => void;
  onType: () => void;
  showMascot: boolean;
  color?: string;
  reducedMotion: boolean;
}

/** The phase the dock shows, from what the voice hook and the chat are doing. */
function phaseOf(voice: Voice, hostTalking: boolean): Phase {
  if (voice.micMuted && !hostTalking) return "muted";
  if (voice.state === "starting" || voice.state === "off") return "starting";
  if (voice.state === "hearing" || voice.state === "transcribing") return "hearing";
  if (voice.state === "speaking" || (hostTalking && voice.saying)) return "speaking";
  if (voice.state === "thinking" || hostTalking) return "thinking";
  return voice.micMuted ? "muted" : "listening";
}

/**
 * Ask Aasan's voice conversation, inside the chat: the conversation stays on screen (what the learner says appears as
 * their message, Aasan's answer streams in as text while it is spoken) and this small dock sits above the message bar
 * with a living orb and one status line. English only. Tap the orb to interrupt. Mute and End live in the bar.
 */
export function VoiceConversation({ voice, hostTalking, onEnd, onType, showMascot, color, reducedMotion }: Props) {
  const { t } = useTranslation();
  const orb = useRef<HTMLDivElement>(null);
  const mouth = useMascot((s) => s.mouth);
  const mood = useMascot((s) => s.mood);
  const phase = phaseOf(voice, hostTalking);

  // The orb swells with whoever is talking: the learner's mic level, or Aasan's voice. Written straight to a CSS
  // variable each frame so the page doesn't re-render 60 times a second.
  const { levels } = voice;
  useEffect(() => {
    if (reducedMotion) return;
    let raf = 0;
    let shown = 0;
    const tick = () => {
      const { mic, voice: out } = levels();
      const target = Math.min(1, Math.max(mic * 6, out * 2.5));
      shown += (target - shown) * 0.25;
      orb.current?.style.setProperty("--level", shown.toFixed(3));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [levels, reducedMotion]);

  // Escape ends the conversation, as the End button does.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onEnd();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onEnd]);

  // While Aasan searches the web its filler ("one moment, let me look that up") may be playing: say what it's doing.
  const status = voice.searching ? t("mentor.web.searching")
    : phase === "speaking" ? (voice.talkOver ? t("mentor.voice.conversation.speaking") : t("mentor.voice.conversation.speakingTap"))
    : t(`mentor.voice.conversation.${phase}`);
  const canInterrupt = phase === "speaking" || phase === "thinking";

  return (
    <div className="flex min-w-0 flex-col items-center gap-1.5 pb-1" data-testid="voice-dock">
      <button type="button" onClick={canInterrupt ? voice.interrupt : undefined} tabIndex={canInterrupt ? 0 : -1}
        aria-label={canInterrupt ? t("mentor.voice.conversation.interrupt") : status} title={canInterrupt ? t("mentor.voice.conversation.interrupt") : undefined}
        data-testid="voice-orb" data-phase={phase}
        className={cn("relative grid h-20 w-20 shrink-0 place-items-center rounded-full focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/40 sm:h-24 sm:w-24",
          canInterrupt ? "cursor-pointer" : "cursor-default")}>
        <div ref={orb} aria-hidden className="absolute inset-0 grid place-items-center" style={{ ["--level" as string]: 0 }}>
          {/* Halo: breathes while listening, follows the voice level while anyone talks. */}
          <span className={cn("absolute inset-0 rounded-full bg-accent/15 transition-transform duration-75",
            !reducedMotion && (phase === "listening" || phase === "starting") && "animate-pulse")}
            style={reducedMotion ? undefined : { transform: "scale(calc(0.84 + var(--level) * 0.3))" }} />
          <span className={cn("absolute inset-[12%] rounded-full shadow-lg transition-colors duration-300",
            phase === "muted" ? "bg-line" : phase === "hearing" ? "bg-accent" : "bg-gradient-to-br from-accent to-accent/70")}
            style={reducedMotion ? undefined : { transform: "scale(calc(0.94 + var(--level) * 0.12))" }} />
          {phase === "thinking" && !reducedMotion && (
            <span className="absolute inset-[12%] animate-spin rounded-full border-4 border-transparent border-t-white/80 [animation-duration:1.2s]" />
          )}
        </div>
        <span className="relative grid place-items-center">
          {showMascot ? (
            <Kili mood={phase === "muted" ? "idle" : mood} mouth={mouth} size={44} color={color} />
          ) : (
            <span className={cn("block h-3 w-3 rounded-full", phase === "muted" ? "bg-ink/50" : "bg-white")} />
          )}
        </span>
      </button>

      <p role="status" aria-live="polite" className="text-sm font-semibold text-muted" data-testid="voice-status">{status}</p>
      {voice.talkOver && phase !== "muted" && <p className="text-xs text-muted">{t("mentor.voice.conversation.headphones")}</p>}
      {voice.error && (
        <p role="alert" className="max-w-xl text-center text-sm text-bad">
          {t(`mentor.voice.errors.${VOICE_ERRORS.includes(voice.error) ? voice.error : "generic"}`)}{" "}
          <button type="button" onClick={onType} className="font-semibold underline">{t("mentor.voice.conversation.typeInstead")}</button>
        </p>
      )}
    </div>
  );
}
