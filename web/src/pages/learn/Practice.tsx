import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ArrowLeft, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { ActivityCard } from "@/activities/ActivityCard";
import type { ActivityData } from "@/activities/types";
import { Button } from "@/components/ui";
import { usePath } from "@/lib/adaptive";
import { ApiError, api } from "@/lib/api";
import { Kili } from "@/mascot/Kili";

interface PracticeSet {
  status: "empty" | "generating" | "ready" | "failed";
  title: string;
  activities: ActivityData[];
}

export default function PracticePage() {
  const { t } = useTranslation();
  const { courseId, lessonId } = useParams();
  const qc = useQueryClient();
  const url = `/api/learn/subsections/${lessonId}/practice/`;
  const [freshErr, setFreshErr] = useState<unknown>(null);
  const { data, error } = useQuery({
    queryKey: ["practice", lessonId],
    queryFn: async () => {
      const cur = await api<PracticeSet>(url);
      return cur.status === "empty" ? api<PracticeSet>(url, { method: "POST" }) : cur;
    },
    refetchInterval: (q) => (q.state.data?.status === "generating" ? 2000 : false),
  });
  const fresh = async () => {
    setFreshErr(null);
    try {
      qc.setQueryData(["practice", lessonId], await api<PracticeSet>(url, { method: "POST" }));
    } catch (e) {
      setFreshErr(e);
    }
  };
  // Adaptive courses: this practice may be the step that reopens finishing the lesson.
  const { data: path, refetch: refetchPath } = usePath(Number(courseId));
  const step = (path?.items ?? []).find((i) => i.kind === "remediation" && i.subsection?.id === Number(lessonId));
  // 20 new practice sets a day: past that the server answers 429 practice_budget_exceeded.
  const err = freshErr ?? error;
  const errText = err ? (err instanceof ApiError && err.data?.code === "practice_budget_exceeded" ? t("practice.budget") : t("mentor.errors.generic")) : "";

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">
      <Link to={`/learn/${courseId}/lesson/${lessonId}`} className="inline-flex items-center gap-1 text-sm font-medium text-muted hover:text-accent">
        <ArrowLeft className="h-4 w-4" /> {data?.title}
      </Link>
      <h1 className="font-display text-3xl font-extrabold">{t("practice.title")}</h1>
      {step && (
        <p role="status" className={step.status === "done" ? "rounded-xl bg-good/10 px-3 py-2 text-sm" : "rounded-xl bg-accent/10 px-3 py-2 text-sm"}>
          {step.status === "done" ? (
            <>{t("adaptive.gate.practiceDone")} <Link className="font-semibold text-accent" to={`/learn/${courseId}/lesson/${lessonId}`}>{t("adaptive.gate.finishNow")}</Link></>
          ) : t("adaptive.gate.practiceHint")}
        </p>
      )}
      {errText && <p role="alert" className="rounded-xl bg-bad/10 px-3 py-2 text-sm text-bad">{errText}</p>}
      {((!data && !error) || data?.status === "generating") && (
        <div className="flex flex-col items-center gap-3 py-12 text-center">
          <Kili mood="thinking" size={130} />
          <p className="text-muted">{t("practice.making")}</p>
        </div>
      )}
      {data?.status === "failed" && <Button onClick={fresh}>{t("common.retry")}</Button>}
      {data?.status === "ready" && (
        <>
          {data.activities.map((a, i) => <ActivityCard key={a.id} activity={a} index={i} onGraded={step ? () => void refetchPath() : undefined} />)}
          <Button variant="outline" onClick={fresh}><Sparkles className="h-4 w-4" /> {t("practice.more")}</Button>
        </>
      )}
    </div>
  );
}
