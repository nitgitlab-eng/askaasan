import { useTranslation } from "react-i18next";

import { Md } from "@/components/Md";
import { WebSources } from "@/components/WebSources";
import { cn } from "@/lib/cn";
import type { WorkshopMsg } from "@/lib/workshops";

/**
 * Captions, not a chat log: what the host is saying now in large text (read out to screen readers as it settles),
 * and below it, smaller, what the learner last said or is saying right now (voice interim text).
 */
export function Caption({ messages, busy, interim }: { messages: WorkshopMsg[]; busy: boolean; interim?: string }) {
  const { t } = useTranslation();
  const host = messages.findLast((m) => m.role === "assistant");
  const me = messages.findLast((m) => m.role === "user");
  const mine = interim || me?.content;
  return (
    <div className="w-full min-w-0 space-y-3 text-center">
      <div aria-live="polite" aria-atomic="false" data-testid="host-caption"
        className={cn("prose-chat mx-auto min-h-[4.5rem] max-w-2xl break-words text-xl leading-relaxed md:text-2xl [overflow-wrap:anywhere]", host?.stop === "cancelled" && "text-muted")}>
        <p className="sr-only">{t("workshop.companion")}:</p>
        {host?.content ? (
          <>
            <Md ai>{host.content + (host.stop === "max_tokens" ? " …" : "")}</Md>
            {host.stop === "cancelled" && <p className="text-base italic text-muted">{t("workshop.live.stopped")}</p>}
            {!host.streaming && <div className="flex justify-center text-base"><WebSources citations={host.citations} /></div>}
          </>
        ) : (
          <p className="text-muted">{busy ? t("workshop.states.thinking") : t("workshop.waiting")}</p>
        )}
      </div>
      {mine && (
        <p data-testid="me-caption" className={cn("mx-auto max-w-xl whitespace-pre-wrap break-words text-base text-muted [overflow-wrap:anywhere]", interim && "italic")}>
          <span className="font-semibold">{t("workshop.you")}: </span>{mine}
        </p>
      )}
    </div>
  );
}

/** The whole conversation (in the ⋮ menu). Interrupted replies are greyed and marked "(stopped)". */
export function Transcript({ messages }: { messages: WorkshopMsg[] }) {
  const { t } = useTranslation();
  if (!messages.length) return <p className="text-sm text-muted">{t("workshop.live.transcriptEmpty")}</p>;
  return (
    <ul className="space-y-1.5 text-sm" data-testid="transcript">
      {messages.map((m) => (
        <li key={m.id} className={m.role === "user" ? "text-right" : ""}>
          <span className={cn("inline-block max-w-[90%] whitespace-pre-wrap break-words rounded-xl px-2.5 py-1 text-left [overflow-wrap:anywhere]",
            m.role === "user" ? "bg-accent text-accent-ink" : "bg-surface-2", m.stop === "cancelled" && "text-muted")}>
            {m.content}{m.stop === "max_tokens" && " …"}
            {m.stop === "cancelled" && <em className="ml-1">{t("workshop.live.stopped")}</em>}
          </span>
        </li>
      ))}
    </ul>
  );
}
