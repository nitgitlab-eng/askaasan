import { CheckCircle2, Hammer, RotateCcw, XCircle } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { REGISTRY } from "@/activities/registry";
import type { Answer, AttemptResult } from "@/activities/types";
import { Button, Card } from "@/components/ui";
import { cn } from "@/lib/cn";
import { errorCode, isBuildTask, workshops, type BuildTask, type Session } from "@/lib/workshops";

/** Server codes that share a message: the rest map to workshop.build.err.<code>. */
const SHARED_ERRORS: Record<string, string> = {
  grading_budget_exceeded: "lesson.gradingBudget",
  artifact_check_rate_limited: "lxMore.rateLimited",
  cap: "workshop.build.err.budget",
};
const pct = (x: number) => Math.round((x <= 1 ? x * 100 : x));

/**
 * A `build` stage's task: the same activity body as in lessons (code, open_input or artifact_check), handed in to the
 * workshop's build endpoint and graded on the server. Feedback is plain text. Nothing is submitted until Check is tapped.
 */
export function BuildTaskCard({ sessionId, task, stageTitle, onSession }: { sessionId: number; task: BuildTask; stageTitle?: string; onSession?: (s: Session) => void }) {
  const { t } = useTranslation();
  const def = isBuildTask(task) ? REGISTRY[task.type] : undefined;
  const payload = task.payload as Record<string, unknown>;
  const last = task.attempt;
  const [answer, setAnswer] = useState<Answer>(last?.answer ?? def?.initial?.(payload) ?? {});
  const [result, setResult] = useState<AttemptResult | null>(last ? { score: last.score, correct: last.passed, feedback: last.feedback, reveal: last.reveal ?? {} } : null);
  const [left, setLeft] = useState<number | undefined>(task.attempts_left);
  const [best, setBest] = useState<number | null | undefined>(task.best_score);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  if (!def) return null;
  const out = left === 0;

  async function check() {
    setBusy(true);
    setProblem("");
    try {
      const r = await workshops.build(sessionId, answer);
      setResult({ score: r.score, correct: r.passed, feedback: r.feedback ?? "", reveal: r.reveal ?? {} });
      if (typeof r.attempts_left === "number") setLeft(r.attempts_left);
      if (typeof r.best_score === "number") setBest(r.best_score);
      if (r.session && onSession) onSession(r.session);
    } catch (e) {
      const code = errorCode(e);
      if (code === "no_attempts_left") setLeft(0);
      setProblem(t(SHARED_ERRORS[code] ?? `workshop.build.err.${code || "generic"}`, { defaultValue: t("mentor.errors.generic") }));
    } finally {
      setBusy(false);
    }
  }

  const Body = def.Body;
  const prompt = typeof payload.prompt === "string" ? payload.prompt : "";
  // The reference solution is sent only once no tries are left. Untrusted text: shown as plain code, never markup.
  const solution = typeof result?.reveal?.model_solution === "string" ? result.reveal.model_solution : "";
  return (
    <Card data-testid="build-task" className={cn("space-y-4", result && (result.correct ? "border-good/60" : "border-bad/50"))}>
      <header className="flex items-start gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-accent/10 text-accent"><Hammer className="h-5 w-5" aria-hidden /></span>
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">{t("workshop.build.title")}</p>
          {task.title && task.title !== stageTitle && <h3 className="break-words font-display text-lg font-bold">{task.title}</h3>}
          {prompt && <p className="whitespace-pre-wrap break-words text-muted">{prompt}</p>}
        </div>
      </header>
      {/* Only the server's own media URLs reach the payload (as in lessons). */}
      {typeof payload.image === "string" && payload.image && <img src={payload.image} alt="" className="max-h-80 w-full rounded-2xl border border-line object-contain" loading="lazy" />}
      <Body payload={payload} answer={answer as never} setAnswer={setAnswer as never} result={result} locked={!!result || busy || out} />
      {result && (
        <div role="status" className={cn("flex items-start gap-2 rounded-xl px-3 py-2", result.correct ? "bg-good/10" : "bg-bad/10")}>
          {result.correct ? <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-good" aria-hidden /> : <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-bad" aria-hidden />}
          <div className="min-w-0">
            <p className="font-semibold">{result.correct ? t("lesson.correct") : t("lesson.notQuite")} · {Math.round(result.score * 100)}%</p>
            {result.feedback && <p className="whitespace-pre-wrap break-words">{result.feedback}</p>}
            <p className="text-sm text-muted">{result.correct ? t("workshop.build.passed") : out ? t("workshop.build.noAttempts") : t("workshop.build.notYet")}</p>
          </div>
        </div>
      )}
      {solution && (
        <div data-testid="build-solution" className="space-y-1">
          <p className="text-sm font-semibold">{t("workshop.build.solution")}</p>
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-surface-2 p-3 font-mono text-sm"><code>{solution}</code></pre>
        </div>
      )}
      {problem && <p role="alert" className="text-sm text-bad">{problem}</p>}
      <div className="flex flex-wrap items-center gap-3">
        {!result ? (
          <Button onClick={() => void check()} loading={busy} disabled={out || !def.ready(answer, payload)}>{t("lesson.check")}</Button>
        ) : !result.correct && !out && (
          <Button variant="outline" onClick={() => setResult(null)}><RotateCcw className="h-4 w-4" aria-hidden /> {t("lesson.tryAgain")}</Button>
        )}
        {typeof left === "number" && (out ? !result : !result?.correct) && (
          <span data-testid="build-attempts" className={cn("text-sm font-semibold", out ? "text-bad" : "text-muted")}>{out ? t("workshop.build.noAttempts") : t("workshop.build.attemptsLeft", { count: left })}</span>
        )}
        {typeof best === "number" && <span data-testid="build-best" className="text-sm text-muted">{t("workshop.build.best", { n: pct(best) })}</span>}
      </div>
    </Card>
  );
}
