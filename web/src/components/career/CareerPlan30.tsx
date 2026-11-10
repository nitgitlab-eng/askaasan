import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, Printer, RefreshCw, Sparkles, Users } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { confirmDialog } from "@/lib/dialog";
import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { careerPlan, planPct, type CareerPlan, type PlanGoal } from "@/lib/careerPlan";
import { cn } from "@/lib/cn";
import { shortDate } from "@/lib/journeys";
import { createCourse } from "@/lib/learn";

/** A week of goals: ticks, links to existing courses/lessons, or "start this course" for a new-course goal. */
export function PlanWeeks({ plan, slug, printable = false }: { plan: CareerPlan; slug: string; printable?: boolean }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const save = (p: CareerPlan) => qc.setQueryData(["career-plan", slug], { plan: p });

  async function tick(g: PlanGoal, done: boolean) {
    setBusy(g.id);
    try {
      save((await careerPlan.tick(slug, g.id, done)).plan);
    } catch {
      setError(t("jr.tickFailed"));
    } finally {
      setBusy(null);
    }
  }
  async function start(g: PlanGoal) {
    setBusy(g.id);
    setError("");
    try {
      const c = await createCourse({ goal: g.course_goal, level: "beginner" });
      save((await careerPlan.linkCourse(slug, g.id, c.id)).plan);
      void qc.invalidateQueries({ queryKey: ["courses"] });
      navigate(`/learn/${c.id}`);
    } catch (e) {
      const code = e instanceof ApiError ? (e.data?.code as string | undefined) : undefined;
      setError(code === "too_many_generating" ? t("learn.tooMany") : t("learn.createFailed"));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-3">
      {error && <p role="alert" className="text-sm text-bad print:hidden">{error}</p>}
      {plan.weeks.map((w) => (
        <section key={w.week} className="break-inside-avoid rounded-2xl border border-line p-3">
          <h3 className="font-display text-lg font-bold">{t("jr.career.week", { n: w.week })}: {w.theme}</h3>
          <p className="text-xs text-muted">{shortDate(w.start, i18n.language)} – {shortDate(w.end, i18n.language)}</p>
          <ol className="mt-2 space-y-2">
            {w.goals.map((g) => (
              <li key={g.id} className="flex items-start gap-3 text-sm">
                <input type="checkbox" checked={g.done} disabled={busy === g.id || printable} onChange={(e) => void tick(g, e.target.checked)}
                  aria-label={g.title} className="mt-1 h-4 w-4 accent-[var(--accent)]" />
                <div className="min-w-0 flex-1">
                  <p className={cn("font-semibold", g.done && "line-through opacity-70")}>{g.title}</p>
                  <p className="text-xs text-muted">{t("jr.career.dueOn", { date: shortDate(g.due, i18n.language) })}{g.skill_name && <> · {t("jr.career.skill")}: {g.skill_name}</>}</p>
                  {g.course_id ? (
                    <p className="text-xs">{g.link && !printable ? <Link to={g.link} className="font-semibold text-accent hover:underline">{g.course_title}{g.lesson_title && ` · ${g.lesson_title}`}</Link> : <>{g.course_title}{g.lesson_title && ` · ${g.lesson_title}`}</>}</p>
                  ) : g.course_goal && (
                    <p className="text-xs">
                      {t("jr.career.newCourseGoal", { goal: g.course_goal })}
                      {!printable && <button disabled={busy === g.id} onClick={() => void start(g)} className="ml-2 font-semibold text-accent hover:underline disabled:opacity-60">{t("jr.career.startCourse")}</button>}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </section>
      ))}
      {!!plan.people.length && (
        <section className="break-inside-avoid rounded-2xl border border-line p-3">
          <h3 className="flex items-center gap-2 font-display text-lg font-bold"><Users className="h-5 w-5 text-accent print:hidden" /> {t("jr.career.people")}</h3>
          <ul className="mt-2 space-y-2 text-sm">
            {plan.people.map((p) => (
              <li key={p.role}><p className="font-semibold">{p.role}</p><p className="text-muted">{p.why}</p>{p.ask && <p className="italic">{t("jr.career.ask", { q: p.ask })}</p>}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

/** "Plan my next 30 days" on a career page: generate (charged), tick off, regenerate, print. */
export function CareerPlan30({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["career-plan", slug], queryFn: () => careerPlan.get(slug) });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const plan = data?.plan ?? null;

  async function generate() {
    if (plan && !(await confirmDialog(t("jr.career.confirmRegen")))) return;
    setBusy(true);
    setError("");
    try {
      qc.setQueryData(["career-plan", slug], await careerPlan.generate(slug));
    } catch (e) {
      const code = e instanceof ApiError ? (e.data?.code as string | undefined) : undefined;
      setError(code === "ai_budget_exceeded" ? t("jr.career.planBudget") : t("jr.career.planFailed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 font-display text-xl font-bold"><CalendarDays className="h-5 w-5 text-accent" /> {t("jr.career.planTitle")}</h2>
          <p className="text-sm text-muted">{t("jr.career.planSub")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {plan && <Link to={`/careers/${slug}/plan/print`} className="flex items-center gap-1.5 rounded-xl border-2 border-line px-3 py-2 text-sm font-semibold hover:border-accent"><Printer className="h-4 w-4" /> {t("jr.career.print")}</Link>}
          <Button loading={busy} onClick={() => void generate()}>{plan ? <><RefreshCw className="h-4 w-4" /> {t("jr.career.planRegen")}</> : <><Sparkles className="h-4 w-4" /> {t("jr.career.planGo")}</>}</Button>
        </div>
      </div>
      <p className="text-xs text-muted">{t("jr.career.planCost")}</p>
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      {plan && (
        <>
          {plan.summary && <p>{plan.summary}</p>}
          <p className="text-sm font-semibold">{t("jr.career.planProgress", { done: plan.done, count: plan.total })} · {planPct(plan)}%</p>
          <PlanWeeks plan={plan} slug={slug} />
        </>
      )}
    </Card>
  );
}
