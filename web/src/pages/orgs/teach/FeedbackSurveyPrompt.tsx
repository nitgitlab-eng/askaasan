import { ClipboardList } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Card } from "@/components/ui";
import type { FeedbackSurvey } from "@/lib/teach";

/** Shown on the lesson recap / role-play result when the school linked a feedback survey to the finished assignment. */
export function FeedbackSurveyPrompt({ survey }: { survey: FeedbackSurvey | null | undefined }) {
  const { t } = useTranslation();
  if (!survey) return null;
  return (
    <Card className="flex flex-col gap-3 border-2 border-accent/50 bg-accent/10 text-left sm:flex-row sm:items-center">
      <ClipboardList className="h-8 w-8 shrink-0 text-accent" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-display text-lg font-bold">{t("teach.feedback.title")}</p>
        <p className="text-sm text-muted">{t("teach.feedback.sub", { org: survey.org, title: survey.title })}</p>
      </div>
      <Link to={survey.url} className="rounded-xl bg-accent px-4 py-2.5 text-center font-semibold text-accent-ink hover:brightness-105">{t("teach.feedback.go")}</Link>
    </Card>
  );
}
