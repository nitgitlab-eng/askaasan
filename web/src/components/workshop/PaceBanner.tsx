import { Clock, Hourglass, Leaf, Sunrise } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/cn";
import type { PaceStatus } from "@/lib/workshops";

/** Gentle pacing note. Time is a guide, never a cutoff: this banner informs and never blocks anything. */
export function PaceBanner({ status, minutesLeft }: { status: PaceStatus | null; minutesLeft?: number | null }) {
  const { t } = useTranslation();
  if (!status) return null;
  const Icon = { on_track: Leaf, behind: Clock, in_grace: Hourglass, overtime: Sunrise }[status];
  const text = status === "on_track" && minutesLeft != null ? t("workshop.pace.on_trackLeft", { n: Math.max(0, Math.round(minutesLeft)) }) : t(`workshop.pace.${status}`);
  return (
    <p
      role="status"
      data-pace={status}
      className={cn(
        "flex items-start gap-2 rounded-2xl px-4 py-2.5 text-base font-medium",
        status === "on_track" && "bg-good/10 text-good",
        status === "behind" && "bg-accent/10 text-ink",
        status === "in_grace" && "border-2 border-accent/40 bg-accent/15 text-ink",
        status === "overtime" && "bg-surface-2 text-ink",
      )}
    >
      <Icon className={cn("mt-0.5 h-5 w-5 shrink-0", status !== "on_track" && "text-accent")} aria-hidden />
      <span>{text}</span>
    </p>
  );
}
