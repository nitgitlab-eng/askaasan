import { CheckCircle2, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/cn";
import type { AnswerValue, TestResult } from "@/lib/orgs";

const show = (v: AnswerValue | string[] | null | undefined): string =>
  v == null || v === "" ? "" : Array.isArray(v) ? v.join(", ") : typeof v === "object" ? Object.entries(v).map(([k, x]) => `${k}: ${x}`).join("; ") : String(v);

/** Score, pass/fail and — only when the manager allowed it — the per-question review with the correct answers. */
export function TestResultView({ r }: { r: TestResult }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-3">
      <div className={cn("flex flex-wrap items-center gap-3 rounded-xl p-3", r.passed ? "bg-good/10" : "bg-amber-500/10")}>
        {r.passed ? <CheckCircle2 className="h-6 w-6 text-good" /> : <XCircle className="h-6 w-6 text-amber-600" />}
        <div>
          <p className="font-display text-lg font-bold">{r.passed ? t("credSurvey.run.passed") : t("credSurvey.run.failed", { mark: r.pass_mark })}</p>
          <p className="text-sm">{t("credSurvey.run.score", { score: r.score, max: r.max_score, pct: r.pct })}</p>
        </div>
      </div>
      {r.review && (
        <div className="space-y-1.5">
          <p className="font-semibold">{t("credSurvey.run.review")}</p>
          {!r.answers_revealed && <p className="text-xs text-muted">{t("credSurvey2.answersLater")}</p>}
          {r.review.map((x) => (
            <div key={x.id} className={cn("rounded-lg border-l-4 bg-surface-2 px-3 py-2 text-sm", x.correct ? "border-good" : "border-bad")}>
              <p className="font-medium">{x.text} <span className="text-xs text-muted">({x.earned}/{x.points})</span></p>
              <p className="text-muted">{t("credSurvey.run.yourAnswer")}: {show(x.your) || t("credSurvey.run.noAnswer")}</p>
              {!x.correct && x.answer !== undefined && <p>{t("credSurvey.run.rightAnswer")}: <b>{show(x.answer)}</b></p>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
