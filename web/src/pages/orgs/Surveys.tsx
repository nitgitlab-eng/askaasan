import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, RotateCcw } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { SurveyRunner } from "@/components/surveys/SurveyRunner";
import { TestResultView } from "@/components/surveys/TestResult";
import { Button, Card } from "@/components/ui";
import { localeOf } from "@/i18n/languages";
import { orgs, type Survey } from "@/lib/orgs";
import { mascot } from "@/mascot/store";

function SurveyForm({ s, onDone }: { s: Survey; onDone: () => void }) {
  const { t } = useTranslation();
  return (
    <Card id={`survey-${s.id}`} className="space-y-4">
      <div>
        <p className="text-xs text-muted">{s.org} · {s.anonymous ? t("org.anonymousNote") : t("org.namedNote")}{s.kind === "test" ? ` · ${t("credSurvey.run.testBadge")}` : ""}</p>
        <h2 className="font-display text-xl font-bold">{s.title}</h2>
        {s.description && <p className="text-sm text-muted">{s.description}</p>}
      </div>
      <SurveyRunner questions={s.questions} initial={s.draft} saveDraft={(a) => orgs.saveDraft(s.id, a)} submit={(a) => orgs.respond(s.id, a)}
        onDone={(res) => { mascot.react(res?.result && !res.result.passed ? "hmm" : "cheer"); onDone(); }} />
    </Card>
  );
}

/** An answered survey/test: thanks, score + review of the latest attempt, attempt history, and "try again" when allowed. */
function Answered({ s, onDone }: { s: Survey; onDone: () => void }) {
  const { t, i18n } = useTranslation();
  const [retake, setRetake] = useState(false);
  const fmt = (d: string) => new Date(d).toLocaleString(localeOf(i18n.language), { dateStyle: "medium", timeStyle: "short" });
  if (retake) return <SurveyForm s={s} onDone={() => { setRetake(false); onDone(); }} />;
  const many = (s.attempts?.length ?? 0) > 1 || s.can_retake || !!s.retake_at;
  return (
    <Card className="space-y-3">
      <p className="flex items-center gap-2 font-semibold"><CheckCircle2 className="h-5 w-5 text-good" /> {s.title} · <span className="font-normal text-muted">{t("org.thanks")}</span></p>
      {s.last_result && <TestResultView r={s.last_result} />}
      {many && !!s.attempts?.length && (
        <div className="text-sm">
          <p className="font-semibold">{t("credSurvey.run.history")}</p>
          <ul className="mt-1 space-y-0.5">
            {s.attempts.map((a) => (
              <li key={a.attempt} className="flex flex-wrap gap-2 text-muted">
                <span>{t("credSurvey.run.attempt", { n: a.attempt })}</span><span>{fmt(a.submitted_at)}</span>
                {a.pct != null && <span className={a.passed ? "text-good" : ""}>{a.pct}%</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3 text-sm">
        {s.can_retake && <Button variant="outline" className="py-1.5 text-sm" onClick={() => setRetake(true)}><RotateCcw className="h-4 w-4" /> {t("credSurvey.run.retake")}</Button>}
        {s.retake_at && <span className="text-muted">{t("credSurvey.run.retakeAt", { time: fmt(s.retake_at) })}</span>}
        {s.attempts_left != null && many && <span className="text-muted">{s.attempts_left > 0 ? t("credSurvey.run.attemptsLeft", { n: s.attempts_left }) : t("credSurvey.run.noMore")}</span>}
      </div>
    </Card>
  );
}

export default function SurveysPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["my-surveys"], queryFn: orgs.mySurveys });
  const pending = data?.filter((s) => !s.answered) ?? [];
  const done = data?.filter((s) => s.answered) ?? [];
  const refresh = () => void qc.invalidateQueries({ queryKey: ["my-surveys"] });
  return (
    <div className="mx-auto max-w-3xl space-y-5 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("org.surveysTitle")}</h1>
        <p className="text-muted">{t("org.surveysSub")}</p>
      </header>
      {data && pending.length === 0 && <Card className="text-muted">{t("org.noSurveys")}</Card>}
      {pending.map((s) => <SurveyForm key={s.id} s={s} onDone={refresh} />)}
      {done.map((s) => <Answered key={s.id} s={s} onDone={refresh} />)}
    </div>
  );
}
