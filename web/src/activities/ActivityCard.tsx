import { CheckCircle2, RotateCcw, XCircle } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { celebrate, gameKey } from "@/lib/game";
import { useQueryClient } from "@tanstack/react-query";
import { cn } from "@/lib/cn";
import { isOfflineError, offlineQueue } from "@/lib/offline";
import { sfx } from "@/mascot/sfx";
import { mascot } from "@/mascot/store";

import { HintLadder } from "@/components/study/HintLadder";

import { REGISTRY } from "./registry";
import { typeLabelKey } from "./typeLabel";
import type { ActivityData, Answer, AttemptResult } from "./types";

export function ActivityCard({
  activity,
  index,
  onGraded,
  submitUrl,
  allowRetry = true,
  lang,
  hints = false,
  askConfidence = false,
  submitHeaders,
}: {
  activity: ActivityData;
  index: number;
  onGraded?: (r: AttemptResult) => void;
  /** Defaults to the lesson attempt endpoint; reviews post to their card. */
  submitUrl?: string;
  allowRetry?: boolean;
  /** Language the learner is reading (translated lesson) — answers are mapped back server-side. */
  lang?: string;
  /** Show Kili's hint ladder until the first correct answer. */
  hints?: boolean;
  /** Ask "how sure are you?" before checking (revision): a lucky guess comes back sooner. */
  askConfidence?: boolean;
  /** Extra request headers for submitUrl (guest links send their guest token). */
  submitHeaders?: Record<string, string>;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const def = REGISTRY[activity.type];
  const [answer, setAnswer] = useState<Answer>(activity.attempt?.answer ?? def.initial?.(activity.payload) ?? {});
  const [result, setResult] = useState<AttemptResult | null>(
    activity.attempt ? { score: activity.attempt.score, correct: activity.attempt.correct, feedback: activity.attempt.feedback, reveal: {} } : null,
  );
  const [busy, setBusy] = useState(false);
  const [confidence, setConfidence] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [queued, setQueued] = useState(() => !submitUrl && !activity.attempt && offlineQueue.has(`attempt:${activity.id}`));
  const locked = !!result;

  async function check() {
    setBusy(true);
    setError(null);
    const aiGraded = activity.type === "open_input" || activity.type === "code";
    if (aiGraded) mascot.react("thinking", 0);
    try {
      const r = await api<AttemptResult>(submitUrl ?? `/api/learn/activities/${activity.id}/attempt/`, { method: "POST", headers: submitHeaders, json: { answer, ...(lang ? { lang } : {}), ...(confidence ? { confidence } : {}) } });
      setResult(r);
      onGraded?.(r);
      celebrate(r.reward, { invalidate: () => void qc.invalidateQueries({ queryKey: gameKey }) });
      if (r.correct) {
        sfx("correct");
        mascot.react(r.score >= 0.999 ? "celebrate" : "cheer");
        mascot.say(r.score >= 0.999 ? t("lesson.kiliPerfect") : t("lesson.kiliGood"), { ms: 2500 });
      } else {
        sfx("wrong");
        mascot.react("hmm");
        mascot.say(t("lesson.kiliTryAgain"), { ms: 3000 });
      }
    } catch (e) {
      if (!submitUrl && isOfflineError(e)) {
        // No connection: keep the answer and send it (to be checked) when we're back online.
        offlineQueue.add({ key: `attempt:${activity.id}`, url: `/api/learn/activities/${activity.id}/attempt/`, json: lang ? { answer, lang } : { answer } });
        setQueued(true);
        mascot.say(t("offline.answerSaved"), { ms: 3500 });
        return;
      }
      mascot.react("confused");
      const code = e instanceof ApiError ? e.data?.code : null;
      setError(code === "grading_unavailable" ? t("lesson.gradingDown") : code === "grading_budget_exceeded" ? t("lesson.gradingBudget") : code === "artifact_check_rate_limited" ? t("lxMore.rateLimited") : t("mentor.errors.generic"));
    } finally {
      setBusy(false);
    }
  }

  const Body = def.Body;
  return (
    <Card className={cn("space-y-4 transition", result && (result.correct ? "border-good/60" : "border-bad/50"))}>
      <header className="flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-surface-2 text-xl" aria-hidden>
          {def.icon}
        </span>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">
            {t("lesson.activity", { n: index + 1 })} · {t(typeLabelKey(activity.type))}
          </p>
          <h3 className="font-display text-lg font-bold">{activity.title}</h3>
          <p className="text-muted">{activity.payload.prompt}</p>
        </div>
      </header>

      {activity.payload.image && activity.type !== "hotspot" && <img src={activity.payload.image} alt="" className="max-h-80 w-full rounded-2xl border border-line object-contain" loading="lazy" />}
      <Body payload={activity.payload} answer={answer as never} setAnswer={setAnswer as never} result={result} locked={locked} activityId={activity.id} />

      {result && (
        <div role="status" className={cn("flex items-start gap-2 rounded-xl px-3 py-2", result.correct ? "bg-good/10 text-good" : "bg-bad/10 text-bad")}>
          {result.correct ? <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0" /> : <XCircle className="mt-0.5 h-5 w-5 shrink-0" />}
          <div>
            <p className="font-semibold">
              {result.correct ? t("lesson.correct") : t("lesson.notQuite")} · {Math.round(result.score * 100)}%
            </p>
            {result.feedback && <p className="text-ink">{result.feedback}</p>}
          </div>
        </div>
      )}
      {result && !result.correct && confidence === 3 && <p className="text-sm text-muted">{t("confidence.sureWrong")}</p>}
      {askConfidence && !result && (
        <div className="flex flex-wrap items-center gap-1.5 text-sm" role="radiogroup" aria-label={t("confidence.ask")}>
          <span className="text-muted">{t("confidence.ask")}</span>
          {[1, 2, 3].map((v) => (
            <button key={v} type="button" role="radio" aria-checked={confidence === v} onClick={() => setConfidence(v)}
              className={cn("rounded-full border px-2.5 py-0.5", confidence === v ? "border-accent bg-accent/15 font-semibold" : "border-line")}>{t(`confidence.v${v}`)}</button>
          ))}
        </div>
      )}
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      {queued && !result && <p role="status" className="rounded-xl bg-amber-100 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950/60 dark:text-amber-200">{t("offline.answerSaved")}</p>}
      {hints && !result?.correct && <HintLadder activityId={activity.id} lang={lang} />}

      <footer className="flex gap-2">
        {!result ? (
          <Button onClick={check} loading={busy} disabled={!def.ready(answer, activity.payload)}>
            {t("lesson.check")}
          </Button>
        ) : (
          allowRetry && !result.correct && (
            <Button
              variant="outline"
              onClick={() => {
                setResult(null);
                setAnswer(def.initial?.(activity.payload) ?? {});
              }}
            >
              <RotateCcw className="h-4 w-4" /> {t("lesson.tryAgain")}
            </Button>
          )
        )}
      </footer>
    </Card>
  );
}
