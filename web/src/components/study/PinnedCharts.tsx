import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Card } from "@/components/ui";
import { study } from "@/lib/study";
import { useMe } from "@/lib/useMe";
import { ProgressChart, type ChartId } from "@/pages/study/Progress";

/** Charts the learner pinned on /progress, shown on Home. */
export function PinnedCharts() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const pins = (me?.preferences.learning.progress_pins ?? []) as ChartId[];
  const { data: p } = useQuery({ queryKey: ["progress", 30], queryFn: () => study.progress(30), enabled: pins.length > 0 });
  if (!pins.length || !p) return null;
  return (
    <section className="space-y-2">
      <div className="flex items-end justify-between">
        <h2 className="font-display text-xl font-bold">{t("progress.pinned")}</h2>
        <Link to="/progress" className="text-sm font-semibold text-accent">{t("progress.title")} →</Link>
      </div>
      <div className="grid gap-4 md:grid-cols-2">{pins.map((id) => <Card key={id}><ProgressChart id={id} p={p} /></Card>)}</div>
    </section>
  );
}
