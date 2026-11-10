import { ArrowUpDown, BookOpen, Loader2, Plus } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";

import { JourneyOrder } from "@/components/course/JourneyOrder";
import { Card } from "@/components/ui";
import { useCourses } from "@/lib/learn";
import { paths } from "@/lib/paths";
import { Kili } from "@/mascot/Kili";

import { TemplatesStrip } from "../lab/studio/HomeExtras";

import { NewCourseForm } from "./NewCourseForm";

export default function LibraryPage() {
  const { t, i18n } = useTranslation();
  const { data: courses, isLoading } = useCourses();
  const [params] = useSearchParams();
  const newSkill = params.get("new"); // from a "start this skill" recommendation
  const { data: skills } = useQuery({ queryKey: ["paths-skills"], queryFn: paths.skills, enabled: !!newSkill });
  const sk = skills?.find((s) => s.slug === newSkill);
  const prefill = sk ? t("paths.learnSkill", { skill: i18n.language === "ta" && sk.name_ta ? sk.name_ta : sk.name }) : "";
  const [open, setOpen] = useState(false);
  const [reordering, setReordering] = useState(false);
  const showForm = open || !!newSkill || (courses && courses.length === 0);

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-extrabold">{t("learn.title")}</h1>
          <p className="text-muted">{t("learn.sub")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {(courses?.length ?? 0) >= 2 && !reordering && (
            <button onClick={() => setReordering(true)} className="flex items-center gap-2 rounded-xl border-2 border-line px-4 py-2 font-semibold hover:border-accent">
              <ArrowUpDown className="h-4 w-4" /> {t("lj.order.reorder")}
            </button>
          )}
          {!showForm && (
            <button onClick={() => setOpen(true)} className="flex items-center gap-2 rounded-xl bg-accent px-4 py-2.5 font-semibold text-accent-ink">
              <Plus className="h-4 w-4" /> {t("learn.new")}
            </button>
          )}
        </div>
      </header>

      {showForm && (
        <Card className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <Kili mood="wave" size={110} />
          <div className="flex-1">
            <h2 className="mb-2 font-display text-xl font-bold">{t("learn.newTitle")}</h2>
            <NewCourseForm key={prefill} defaultGoal={prefill} onDone={() => setOpen(false)} />
          </div>
        </Card>
      )}

      <TemplatesStrip forLearner />
      {isLoading && <p className="text-muted">{t("common.loading")}</p>}
      {reordering && courses ? <JourneyOrder courses={courses} onDone={() => setReordering(false)} /> : (
      <div className="grid gap-4 sm:grid-cols-2">
        {courses?.map((c) => {
          const pct = c.progress.total ? Math.round((100 * c.progress.done) / c.progress.total) : 0;
          return (
            <Link key={c.id} to={`/learn/${c.id}`} className="group">
              <Card className="h-full space-y-3 transition group-hover:-translate-y-0.5 group-hover:border-accent">
                <div className="flex items-start gap-3">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent/15 text-accent">
                    {c.status === "generating" ? <Loader2 className="h-5 w-5 animate-spin" /> : <BookOpen className="h-5 w-5" />}
                  </span>
                  <div className="min-w-0">
                    <h3 className="font-display text-lg font-bold leading-tight">{c.title}</h3>
                    <p className="line-clamp-2 text-sm text-muted">{c.status === "generating" ? t("learn.building") : c.status === "failed" ? t("learn.failed") : c.description}</p>
                  </div>
                </div>
                {c.status === "ready" && (
                  <div>
                    <div className="h-2 overflow-hidden rounded-full bg-surface-2">
                      <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${pct}%` }} />
                    </div>
                    <p className="mt-1 text-xs text-muted">{t("learn.progress", { done: c.progress.done, count: c.progress.total })}</p>
                  </div>
                )}
              </Card>
            </Link>
          );
        })}
      </div>
      )}
    </div>
  );
}
