import { useQuery } from "@tanstack/react-query";
import { CheckCircle2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { SurveyRunner } from "@/components/surveys/SurveyRunner";
import { TestResultView } from "@/components/surveys/TestResult";
import { Button, Card } from "@/components/ui";
import { orgs, type SubmitResult } from "@/lib/orgs";

/** A random id this browser keeps per survey, so a half-done survey can be resumed (we store only an HMAC of it). */
function resumeKey(token: string): string {
  const k = `aasan-survey-${token}`;
  try {
    const have = localStorage.getItem(k);
    if (have) return have;
    const fresh = crypto.randomUUID();
    localStorage.setItem(k, fresh);
    return fresh;
  } catch {
    return crypto.randomUUID(); // private mode: works, just can't resume later
  }
}

export default function PublicSurveyPage() {
  const { t } = useTranslation();
  const { token = "" } = useParams();
  const [r] = useState(() => resumeKey(token));
  const [done, setDone] = useState<SubmitResult | null>(null);
  const [retake, setRetake] = useState(false);
  const { data, error, refetch } = useQuery({ queryKey: ["public-survey", token], queryFn: () => orgs.publicSurvey(token, r), retry: false });
  if (error) return <main className="mx-auto max-w-xl px-4 py-16 text-center text-muted">{t("survey.closed")}</main>;
  if (!data) return <main className="p-8 text-muted">{t("common.loading")}</main>;
  return (
    <main className="mx-auto max-w-2xl space-y-4 px-4 py-10">
      <header className="flex items-center gap-3">
        {data.logo_url && <img src={data.logo_url} alt="" className="h-12 w-12 rounded-xl object-contain" />}
        <div>
          <p className="text-sm font-semibold" style={data.brand_color ? { color: data.brand_color } : undefined}>{data.org}</p>
          <h1 className="font-display text-3xl font-extrabold">{data.title}</h1>
        </div>
      </header>
      {data.description && <p className="text-muted">{data.description}</p>}
      <Card>
        {(done || data.answered) && !retake ? (
          <div className="space-y-3">
            <p className="flex items-center gap-2 py-4 text-lg"><CheckCircle2 className="h-6 w-6 text-good" /> {t("survey.thanksPublic")}</p>
            {(done ? done.result : data.last_result) && <TestResultView r={(done ? done.result : data.last_result)!} />}
            {(done ? done.can_retake : data.can_retake) && (
              <Button variant="outline" onClick={() => { setDone(null); setRetake(true); }}>{t("credSurvey.run.retake")}</Button>
            )}
          </div>
        ) : (
          <SurveyRunner questions={data.questions} initial={retake ? {} : data.draft} saveDraft={(a) => orgs.publicDraft(token, r, a)}
            submit={(a) => orgs.publicRespond(token, r, a)} onDone={(res) => { setDone(res ?? { ok: true, attempt: 1, result: null, can_retake: false, retake_at: null, attempts_left: null }); setRetake(false); void refetch(); }} />
        )}
      </Card>
      <p className="text-center text-xs text-muted">{t("survey.publicPrivacy")}</p>
    </main>
  );
}
