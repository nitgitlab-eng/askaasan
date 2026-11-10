import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarPlus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { localeOf } from "@/i18n/languages";
import { Button, Card } from "@/components/ui";
import { cn } from "@/lib/cn";
import { pushKey, pushStatus } from "@/lib/push";
import { useMe, useUpdatePreferences } from "@/lib/useMe";
import { useAuth } from "@/stores/auth";

import { BuddiesCard, PausesCard } from "@/components/study/PausesAndBuddies";
import { WeekPlanner } from "@/components/study/WeekPlanner";

import { CalendarSubscribe } from "./CalendarSubscribe";


/** Rhythm: pick study days + time, see the week, add it to your calendar. */
export default function PlanPage() {
  const { t, i18n } = useTranslation();
  const { data: me } = useMe();
  const update = useUpdatePreferences();
  const qc = useQueryClient();
  const { data: push } = useQuery({ queryKey: pushKey, queryFn: pushStatus });
  const learned = push?.reminders && !push.reminders.time_chosen ? push.reminders.learned_time : null;
  const l = me?.preferences.learning;
  const names = Array.from({ length: 7 }, (_, d) => new Date(2024, 0, 1 + d).toLocaleDateString(localeOf(i18n.language), { weekday: "short" }));

  async function downloadIcs() {
    const res = await fetch("/api/game/plan.ics", { headers: { Authorization: `Bearer ${useAuth.getState().access}` } });
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: "aasan-study-plan.ics" });
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("plan.title")}</h1>
        <p className="text-muted">{t("plan.sub")}</p>
      </header>
      <WeekPlanner />
      <PausesCard />
      <BuddiesCard />
      {l && (
        <Card className="space-y-4">
          <h2 className="font-display text-xl font-bold">{t("plan.when")}</h2>
          <div className="flex flex-wrap gap-2">
            {names.map((n, d) => (
              <button key={d} aria-pressed={l.study_days.includes(d)}
                onClick={() => update.mutate({ learning: { study_days: l.study_days.includes(d) ? l.study_days.filter((x) => x !== d) : [...l.study_days, d].sort() } })}
                className={cn("rounded-full border-2 px-3 py-1.5 text-sm font-semibold", l.study_days.includes(d) ? "border-accent bg-accent text-accent-ink" : "border-line")}>
                {n}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-3">
            <span className="text-sm font-medium">{t("plan.time")}</span>
            <input type="time" value={l.reminder_times[0] ?? "19:00"} onChange={(e) => update.mutate({ learning: { reminder_times: [e.target.value] } }, { onSuccess: () => void qc.invalidateQueries({ queryKey: pushKey }) })} className="rounded-xl border-2 border-line bg-surface px-3 py-2" />
          </label>
          {learned && <p className="text-sm text-muted">{t("plan.learnedTime", { time: learned })}</p>}
          <p className="text-sm text-muted">{t("plan.goal", { count: l.daily_goal_minutes })}</p>
          <Button variant="outline" onClick={downloadIcs}><CalendarPlus className="h-4 w-4" /> {t("plan.addCalendar")}</Button>
          <p className="text-xs text-muted">{t("plan.icsHint")}</p>
          <CalendarSubscribe />
        </Card>
      )}
    </div>
  );
}
