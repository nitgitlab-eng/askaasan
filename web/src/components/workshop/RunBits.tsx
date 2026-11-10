import { CalendarClock, Clock, Users } from "lucide-react";
import { useTranslation } from "react-i18next";

import { rupees } from "@/lib/billing";
import { cn } from "@/lib/cn";
import { splitDuration, useRunTime, type Run } from "@/lib/workshops";

/** "2 d 4 h", "3 h 12 min" or "4 min 09 s" until `to`. */
export function Countdown({ to, now, className }: { to: string; now: number; className?: string }) {
  const { t } = useTranslation();
  const { d, h, m, s } = splitDuration(Date.parse(to) - now);
  const text = d ? t("workshop.pub.cd.dh", { d, h }) : h ? t("workshop.pub.cd.hm", { h, m }) : t("workshop.pub.cd.ms", { m, s: String(s).padStart(2, "0") });
  return <span className={cn("tabular-nums", className)} role="timer">{text}</span>;
}

export function PriceBadge({ paise, className }: { paise: number; className?: string }) {
  const { t } = useTranslation();
  return (
    <span className={cn("shrink-0 rounded-full px-2.5 py-0.5 text-sm font-semibold", paise ? "bg-accent/15 text-accent" : "bg-good/15 text-good", className)}>
      {paise ? rupees(paise) : t("workshop.list.free")}
    </span>
  );
}

/** Date, time, length and (for capped runs) seats left, as one wrapped line. */
export function RunMeta({ run }: { run: Run }) {
  const { t } = useTranslation();
  const when = useRunTime();
  return (
    <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
      <span className="flex items-center gap-1"><CalendarClock className="h-4 w-4" aria-hidden /> {when.date(run.starts_at)} · {when.time(run.starts_at)}</span>
      <span className="flex items-center gap-1"><Clock className="h-4 w-4" aria-hidden /> {t("workshop.list.minutes", { count: run.workshop.duration_minutes })}</span>
      {typeof run.seats_left === "number" && (
        <span className={cn("flex items-center gap-1", run.seats_left === 0 && "font-semibold text-bad")}>
          <Users className="h-4 w-4" aria-hidden /> {run.seats_left === 0 ? t("workshop.pub.full") : t("workshop.pub.seatsLeft", { count: run.seats_left })}
        </span>
      )}
    </p>
  );
}
