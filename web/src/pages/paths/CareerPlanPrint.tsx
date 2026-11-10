import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Printer } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { PlanWeeks } from "@/components/career/CareerPlan30";
import { Button } from "@/components/ui";
import { careerPlan, planPct } from "@/lib/careerPlan";
import { shortDate } from "@/lib/journeys";
import { paths } from "@/lib/paths";

/** Printable 30-day plan (outside the app shell so the page prints cleanly). */
export default function CareerPlanPrintPage() {
  const { t, i18n } = useTranslation();
  const { slug = "" } = useParams();
  const { data: c } = useQuery({ queryKey: ["career", slug], queryFn: () => paths.career(slug) });
  const { data } = useQuery({ queryKey: ["career-plan", slug], queryFn: () => careerPlan.get(slug) });
  const plan = data?.plan;
  if (!c || !data) return <p className="p-8 text-muted">{t("common.loading")}</p>;
  const role = i18n.language === "ta" && c.title_ta ? c.title_ta : c.title;
  return (
    <div className="mx-auto max-w-3xl space-y-4 bg-surface px-6 py-8 print:max-w-none print:p-0">
      <div className="flex flex-wrap items-center justify-between gap-2 print:hidden">
        <Link to={`/careers/${slug}`} className="flex items-center gap-1 text-sm font-semibold text-accent hover:underline"><ArrowLeft className="h-4 w-4" /> {t("jr.career.backToRole")}</Link>
        {plan && <Button onClick={() => window.print()}><Printer className="h-4 w-4" /> {t("jr.career.print")}</Button>}
      </div>
      <header>
        <h1 className="font-display text-2xl font-extrabold">{t("jr.career.printTitle", { role })}</h1>
        {plan && <p className="text-sm text-muted">{shortDate(plan.start_date, i18n.language)} – {shortDate(plan.end_date, i18n.language)} · {t("jr.career.planProgress", { done: plan.done, count: plan.total })} ({planPct(plan)}%)</p>}
      </header>
      {plan ? <>{plan.summary && <p>{plan.summary}</p>}<PlanWeeks plan={plan} slug={slug} printable /></> : <p className="text-muted">{t("jr.career.noPlan")}</p>}
    </div>
  );
}
