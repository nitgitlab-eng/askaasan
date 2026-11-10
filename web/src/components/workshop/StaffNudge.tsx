import { MessageCircleHeart, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { nudgesNewestFirst, useRunTime, type StaffNudge } from "@/lib/workshops";

/**
 * "Message from your teacher": nudges sent from an institution's live dashboard, including ones sent while the learner
 * was away (they arrive with the socket's `ready`). Newest first, each dismissable. Teacher-typed: plain text only.
 */
export function StaffNudges({ nudges, onDismiss }: { nudges: StaffNudge[]; onDismiss: (id: string) => void }) {
  const { t } = useTranslation();
  const when = useRunTime();
  if (!nudges.length) return null;
  return (
    <div role="status" aria-live="polite">
      <ul aria-label={t("workshop.nudge.title")} className="space-y-2">
        {nudgesNewestFirst(nudges).map((n) => (
          <li key={n.id} data-testid="staff-nudge" className="flex items-start gap-3 rounded-2xl border-2 border-accent/40 bg-accent/10 p-3">
            <MessageCircleHeart className="mt-0.5 h-6 w-6 shrink-0 text-accent" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="flex flex-wrap items-baseline gap-x-2 text-sm font-bold">
                <span className="min-w-0 break-words">{n.from ? t("workshop.nudge.fromName", { name: n.from }) : t("workshop.nudge.title")}</span>
                {n.at && <time dateTime={n.at} className="text-xs font-medium text-muted">{t("workshop.nudge.sentAt", { time: when.time(n.at) })}</time>}
              </p>
              <p className="whitespace-pre-wrap break-words text-base">{n.text}</p>
            </div>
            <button type="button" onClick={() => onDismiss(n.id)} aria-label={t("workshop.nudge.dismiss")} className="shrink-0 rounded-lg p-1 text-muted hover:bg-surface-2 hover:text-ink">
              <X className="h-5 w-5" aria-hidden />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
