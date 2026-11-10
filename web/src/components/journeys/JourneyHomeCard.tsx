import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Compass } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Card } from "@/components/ui";
import { dayLabel, journeys } from "@/lib/journeys";

/** Home: "Day X of N" for each onboarding journey, with today's items. Hidden when the learner has none. */
export function JourneyHomeCard() {
  const { t, i18n } = useTranslation();
  const { data } = useQuery({ queryKey: ["my-journeys"], queryFn: journeys.mine });
  const live = (data ?? []).filter((a) => !a.status.finished && !a.status.ended);
  if (!live.length) return null;
  return (
    <div className="space-y-3">
      {live.slice(0, 2).map((a) => (
        <Link key={a.id} to={`/journey?a=${a.id}`} className="group block">
          <Card className="flex items-start gap-4 border-2 border-accent/40 transition group-hover:border-accent">
            <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-accent/15 text-accent"><Compass className="h-6 w-6" /></span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-accent">{dayLabel(t, a, i18n.language)}</p>
              <p className="truncate font-display text-lg font-bold">{a.journey.name}</p>
              {a.status.started && (
                <p className="text-sm text-muted">
                  {a.today?.length ? t("jr.homeToday", { n: a.today.filter((i) => !i.done).length }) : t("jr.nothingToday")}
                  {a.status.overdue > 0 && <span className="ml-2 font-semibold text-bad">{t("jr.overdueN", { n: a.status.overdue })}</span>}
                </p>
              )}
              {!!a.today?.length && (
                <ul className="mt-1 space-y-0.5 text-sm">
                  {a.today.slice(0, 3).map((i) => <li key={i.id} className={i.done ? "text-muted line-through" : ""}>• {i.title}</li>)}
                </ul>
              )}
            </div>
            <ArrowRight className="h-6 w-6 text-accent transition group-hover:translate-x-1" aria-label={t("jr.homeOpen")} />
          </Card>
        </Link>
      ))}
    </div>
  );
}
