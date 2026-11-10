import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CalendarCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { study } from "@/lib/study";

/** Home teaser for today's revision stations. */
export function TodayCard() {
  const { t } = useTranslation();
  const { data } = useQuery({ queryKey: ["today"], queryFn: study.today, staleTime: 60_000 });
  if (!data?.total) return null;
  const all = data.done >= data.total;
  return (
    <Link to="/today" className="flex items-center gap-3 rounded-2xl border-2 border-line bg-surface px-4 py-3 hover:border-accent">
      <CalendarCheck className="h-6 w-6 text-accent" />
      <span className="min-w-0 flex-1">
        <span className="block font-semibold">{t("today.title")}</span>
        <span className="text-sm text-muted">{all ? t("today.allDone") : t("today.sub", { done: data.done, count: data.total })}</span>
      </span>
      <ArrowRight className="h-5 w-5 text-accent" />
    </Link>
  );
}
