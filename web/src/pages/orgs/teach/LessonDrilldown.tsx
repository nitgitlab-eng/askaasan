import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, KeyRound, Lightbulb, XCircle } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { localeOf } from "@/i18n/languages";
import { cn } from "@/lib/cn";
import { teach, type QuestionDrill } from "@/lib/teach";

import { aiError, pct } from "./teachUtils";

function Question({ q }: { q: QuestionDrill }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-2 rounded-xl border border-line p-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <p className="flex-1 font-semibold">{q.title}</p>
        <span className="text-xs text-muted">{t("teach.correctOf", { c: q.correct, n: q.answered })}</span>
      </div>
      {q.prompt && <p className="text-sm">{q.prompt}</p>}
      {q.key && (
        <div className="rounded-lg bg-good/10 p-2 text-sm">
          <p className="flex items-center gap-1 text-xs font-semibold text-good"><KeyRound className="h-3.5 w-3.5" /> {t("teach.keyLabel")}</p>
          <p className="whitespace-pre-wrap">{q.key.answer}</p>
          {q.key.rationale && <p className="text-xs text-muted"><b>{t("teach.why")}:</b> {q.key.rationale}</p>}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted"><tr><th className="py-1 pr-2">{t("teach.col.learner")}</th><th className="pr-2">{t("teach.col.answer")}</th><th>{t("teach.col.result")}</th></tr></thead>
          <tbody>
            {q.learners.map((r) => (
              <tr key={r.user_id} className="border-t border-line align-top">
                <td className="py-1.5 pr-2 font-medium">{r.name}</td>
                <td className="max-w-md whitespace-pre-wrap break-words pr-2">{r.answered ? r.answer : <span className="text-muted">{t("teach.notAnswered")}</span>}</td>
                <td className="whitespace-nowrap">
                  {r.answered && (r.correct
                    ? <span className="flex items-center gap-1 text-good"><CheckCircle2 className="h-4 w-4" /> {t("teach.right")}</span>
                    : <span className="flex items-center gap-1 text-bad"><XCircle className="h-4 w-4" /> {t("teach.wrong")}</span>)}
                  {r.attempts > 1 && <span className="text-xs text-muted">{t("teach.tries", { count: r.attempts })}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Lesson({ slug, id, sid, back }: { slug: string; id: number; sid: number; back: () => void }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const key = ["teach-lesson", slug, id, sid];
  const { data, error } = useQuery({ queryKey: key, queryFn: () => teach.lesson(slug, id, sid) });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  if (error) return <p className="text-sm text-bad">{aiError(t, error)}</p>;
  if (!data) return <p className="text-sm text-muted">{t("common.loading")}</p>;
  const mis = data.misconceptions;
  async function find() {
    setBusy(true);
    setErr("");
    try {
      const r = await teach.misconceptions(slug, id, sid);
      qc.setQueryData(key, { ...data!, misconceptions: r.misconceptions });
    } catch (e) {
      setErr(aiError(t, e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-3">
      <button onClick={back} className="flex items-center gap-1 text-sm font-semibold text-accent"><ArrowLeft className="h-4 w-4" /> {t("teach.back")}</button>
      <h3 className="font-display text-lg font-bold">{data.lesson.title}</h3>
      {!data.keys && <p className="rounded-lg bg-surface-2 p-2 text-sm text-muted">{t("teachScope.keysHidden")}</p>}
      {data.keys && <div className="space-y-2 rounded-xl border border-line p-3">
        <div className="flex flex-wrap items-center gap-2">
          <p className="flex flex-1 items-center gap-2 font-display text-base font-bold"><Lightbulb className="h-4 w-4 text-accent" /> {t("teach.misTitle")}</p>
          {mis && <span className="text-xs text-muted">{t("teach.updated", { d: new Date(mis.updated_at).toLocaleDateString(localeOf(i18n.language)) })}</span>}
          <Button variant="outline" className="py-1 text-sm" loading={busy} onClick={() => void find()}>{mis ? t("teach.regenerate") : t("teach.misFind")}</Button>
        </div>
        <p className="text-xs text-muted">{t("teach.aiCost")}</p>
        {err && <p role="alert" className="text-sm text-bad">{err}</p>}
        {mis && (
          <div className="space-y-2 text-sm">
            <p className="font-semibold">{mis.summary}</p>
            {mis.misconceptions.map((m) => (
              <div key={m.topic} className="rounded-lg bg-surface-2 p-2">
                <p className="font-semibold">{m.topic} <span className="text-xs font-normal text-muted">· {t("teach.misLearners", { count: m.learners })}</span></p>
                <p>{m.explanation}</p>
                {!!m.questions.length && <p className="text-xs text-muted">{t("teach.misIn", { q: m.questions.join(", ") })}</p>}
                <p className="mt-1"><b>{t("teach.reteach")}:</b> {m.reteach_tip}</p>
              </div>
            ))}
          </div>
        )}
      </div>}
      {data.questions.map((q) => <Question key={q.id} q={q} />)}
    </div>
  );
}

/** Course assignment → lessons → each question with every learner's latest answer, the key, and AI misconceptions. */
export function LessonDrilldown({ slug, id }: { slug: string; id: number }) {
  const { t } = useTranslation();
  const { data, error } = useQuery({ queryKey: ["teach-lessons", slug, id], queryFn: () => teach.lessons(slug, id) });
  const [sid, setSid] = useState<number | null>(null);
  if (error) return <p className="text-sm text-bad">{aiError(t, error)}</p>;
  if (!data) return <p className="text-sm text-muted">{t("common.loading")}</p>;
  if (sid) return <Lesson slug={slug} id={id} sid={sid} back={() => setSid(null)} />;
  if (data.no_class) return <p className="text-sm text-muted">{t("teachScope.noClass")}</p>;
  return (
    <div className="space-y-2">
      <p className="font-display text-base font-bold">{t("teach.answersTitle")}</p>
      <p className="text-xs text-muted">{t("teach.pickLesson")}</p>
      <ul className="divide-y divide-line">
        {data.lessons.map((l) => (
          <li key={l.id}>
            <button className="flex w-full flex-wrap items-center gap-2 py-2 text-left hover:text-accent" onClick={() => setSid(l.id)}>
              <span className="min-w-0 flex-1"><span className="font-medium">{l.title}</span> <span className="text-xs text-muted">· {l.section}</span></span>
              <span className="text-xs text-muted">{t("teach.lessonQuestions", { count: l.questions })} · {t("teach.lessonFinished", { count: l.completed })} · {t("teach.lessonCorrect", { rate: pct(l.correct_rate) })}</span>
              <span className={cn("h-2 w-16 overflow-hidden rounded-full bg-surface-2")} aria-hidden>
                <span className="block h-full rounded-full bg-accent" style={{ width: `${(l.correct_rate ?? 0) * 100}%` }} />
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
