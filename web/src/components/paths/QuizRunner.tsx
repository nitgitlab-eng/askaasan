import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { QuizQ } from "@/lib/paths";

/** One question at a time; calls onDone with {questionId: chosenIndex}. */
export function QuizRunner({ questions, onDone, busy }: { questions: QuizQ[]; onDone: (answers: Record<string, number>) => void; busy?: boolean }) {
  const { t } = useTranslation();
  const [i, setI] = useState(0);
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const q = questions[i];
  if (!q) return null;
  const pick = (o: number) => setAnswers({ ...answers, [q.id]: o });
  const last = i === questions.length - 1;
  return (
    <div className="space-y-3">
      <div className="flex gap-1">{questions.map((_, k) => <span key={k} className={cn("h-1.5 flex-1 rounded-full", k <= i ? "bg-accent" : "bg-surface-2")} />)}</div>
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">{q.skill}</p>
      <p className="font-medium">{q.prompt}</p>
      <div className="grid gap-2">
        {q.options.map((o, k) => (
          <button key={k} type="button" aria-pressed={answers[q.id] === k} onClick={() => pick(k)}
            className={cn("rounded-xl border-2 px-3 py-2 text-left", answers[q.id] === k ? "border-accent bg-accent/10" : "border-line hover:border-accent")}>{o}</button>
        ))}
        <button type="button" onClick={() => pick(-1)} className={cn("text-left text-sm text-muted underline-offset-2 hover:underline", answers[q.id] === -1 && "text-accent")}>{t("paths.notSure")}</button>
      </div>
      <div className="flex justify-between">
        <Button variant="ghost" disabled={i === 0} onClick={() => setI(i - 1)}>{t("common.back")}</Button>
        {last ? <Button loading={busy} disabled={answers[q.id] === undefined} onClick={() => onDone(answers)}>{t("paths.seeResult")}</Button>
          : <Button disabled={answers[q.id] === undefined} onClick={() => setI(i + 1)}>{t("onboarding.next")}</Button>}
      </div>
    </div>
  );
}
