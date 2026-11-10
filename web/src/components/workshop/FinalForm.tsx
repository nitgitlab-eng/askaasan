import { Award, Bot } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { confirmDialog } from "@/lib/dialog";
import { asPercent, workshops, type FinalPublic, type FinalResult } from "@/lib/workshops";

/** The final round: MCQs (graded on the server, keys never sent here) plus the practical task. Never auto-submits. */
export function FinalForm({ sessionId, final, passMark, attemptsLeft, onResult }: { sessionId: number; final: FinalPublic | null | undefined; passMark: number; attemptsLeft?: number; onResult: (r: FinalResult) => void }) {
  const { t } = useTranslation();
  const questions = final?.mcqs ?? [];
  const prompt = final?.practical?.prompt ?? "";
  const outOfTries = attemptsLeft === 0;
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [practical, setPractical] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (questions.some((_, i) => answers[i] === undefined)) return setProblem(t("workshop.final.unanswered"));
    if (!(await confirmDialog(t("workshop.final.confirm"), { ok: t("workshop.final.submit") }))) return;
    setBusy(true);
    setProblem("");
    try {
      onResult(await workshops.final(sessionId, answers, practical.trim()));
    } catch (err) {
      setProblem(err instanceof ApiError && err.data?.code === "no_attempts_left" ? t("workshop.final.attempts") : t("workshop.final.failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-5">
      <div>
        <h2 className="flex items-center gap-2 font-display text-2xl font-bold"><Award className="h-6 w-6 text-accent" aria-hidden /> {t("workshop.final.title")}</h2>
        <p className="text-muted">{t("workshop.final.sub", { n: asPercent(passMark) })}</p>
      </div>
      {!!final?.agent_tests && (
        <p className="flex gap-2 rounded-xl bg-accent/10 px-3 py-2.5 text-base" data-testid="agent-tests-note">
          <Bot className="mt-0.5 h-5 w-5 shrink-0 text-accent" aria-hidden /> {t("workshop.agent.finalNote", { count: final.agent_tests })}
        </p>
      )}
      {!questions.length && !prompt && !final?.agent_tests && <p className="text-muted">{t("workshop.final.noQuestions")}</p>}
      {outOfTries ? (
        <p role="status" className="rounded-xl bg-surface-2 px-3 py-2">{t("workshop.final.attempts")}</p>
      ) : attemptsLeft !== undefined && <p data-testid="attempts-left" className="text-sm font-semibold text-accent">{t("workshop.final.attemptsLeft", { count: attemptsLeft })}</p>}
      <form onSubmit={submit} className="space-y-5">
        {questions.map((q, i) => (
          <fieldset key={i} className="space-y-2">
            <legend className="break-words text-lg font-semibold"><span className="text-muted">{t("workshop.final.q", { n: i + 1 })} · </span>{q.q}</legend>
            <div className="grid gap-2">
              {q.options.map((o, j) => (
                <label key={j} className={cn("flex cursor-pointer items-start gap-3 rounded-xl border-2 px-3 py-2.5 text-base transition", answers[i] === j ? "border-accent bg-accent/10" : "border-line hover:border-accent")}>
                  <input type="radio" name={`q${i}`} checked={answers[i] === j} onChange={() => setAnswers((a) => ({ ...a, [i]: j }))} className="mt-1.5 accent-[var(--accent)]" />
                  <span className="min-w-0 break-words">{o}</span>
                </label>
              ))}
            </div>
          </fieldset>
        ))}
        {prompt && (
          <label className="block space-y-2">
            <span className="text-lg font-semibold">{t("workshop.final.practical")}</span>
            <p className="whitespace-pre-wrap break-words text-base text-muted">{prompt}</p>
            <textarea value={practical} onChange={(e) => setPractical(e.target.value)} rows={6} maxLength={4000} placeholder={t("workshop.final.practicalPh")}
              className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2 text-base outline-none focus:border-accent" />
          </label>
        )}
        {problem && <p role="alert" className="text-sm text-bad">{problem}</p>}
        <Button type="submit" loading={busy} disabled={outOfTries || (!questions.length && !prompt && !final?.agent_tests)} className="w-full py-3 text-lg">{t("workshop.final.submit")}</Button>
      </form>
    </Card>
  );
}
