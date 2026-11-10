import { Hand } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/cn";

import type { useVoiceMode } from "./useVoiceMode";

type Voice = ReturnType<typeof useVoiceMode>;

/**
 * "Interrupt" while the AI is answering by voice. On the browser recogniser the mic rests while the AI talks (so its
 * own voice can't come back as the learner's words), so a tap is how to cut in; with streamed listening, talking works
 * too and this is the quiet way.
 */
export function InterruptButton({ voice, busy, className }: { voice: Voice; busy: boolean; className?: string }) {
  const { t } = useTranslation();
  if (!voice.active || !(voice.state === "speaking" || voice.state === "thinking" || busy)) return null;
  const label = t("mentor.voice.conversation.interrupt");
  return (
    <button type="button" onClick={voice.interrupt} aria-label={label} title={label} data-testid="voice-interrupt"
      className={cn("flex items-center gap-1.5 rounded-xl border-2 border-line bg-surface px-3 font-semibold hover:border-accent focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/40", className)}>
      <Hand className="h-4 w-4 shrink-0" aria-hidden /> <span className="sr-only sm:not-sr-only">{label}</span>
    </button>
  );
}
