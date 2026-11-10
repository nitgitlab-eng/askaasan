import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { AnswerValue, Question, SubmitResult } from "@/lib/orgs";

const pill = (active: boolean) => cn("min-w-10 rounded-xl border-2 px-3 py-2 text-sm font-semibold transition", active ? "border-accent bg-accent text-accent-ink" : "border-line hover:border-accent");

export function QuestionInput({ q, value, onChange }: { q: Question; value: AnswerValue | undefined; onChange: (v: AnswerValue | undefined) => void }) {
  const { t } = useTranslation();
  switch (q.type) {
    case "rating":
      return <div role="radiogroup" aria-label={q.text} className="flex flex-wrap gap-2">{[1, 2, 3, 4, 5].map((n) => <button key={n} type="button" role="radio" aria-checked={value === n} className={pill(value === n)} onClick={() => onChange(n)}>{"★".repeat(n)}</button>)}</div>;
    case "nps":
    case "scale": {
      const lo = q.type === "nps" ? 0 : q.min ?? 1, hi = q.type === "nps" ? 10 : q.max ?? 10;
      return (
        <div>
          <div role="radiogroup" aria-label={q.text} className="flex flex-wrap gap-1.5">
            {Array.from({ length: hi - lo + 1 }, (_, i) => lo + i).map((n) => <button key={n} type="button" role="radio" aria-checked={value === n} className={pill(value === n)} onClick={() => onChange(n)}>{n}</button>)}
          </div>
          <div className="mt-1 flex justify-between text-xs text-muted"><span>{q.type === "nps" ? t("org.npsLow") : q.min_label}</span><span>{q.type === "nps" ? t("org.npsHigh") : q.max_label}</span></div>
        </div>
      );
    }
    case "choice":
      return <div role="radiogroup" aria-label={q.text} className="flex flex-wrap gap-2">{q.options?.map((o) => <button key={o} type="button" role="radio" aria-checked={value === o} className={pill(value === o)} onClick={() => onChange(o)}>{o}</button>)}</div>;
    case "multi": {
      const sel = Array.isArray(value) ? value : [];
      return (
        <div role="group" aria-label={q.text} className="flex flex-wrap gap-2">
          {q.options?.map((o) => {
            const on = sel.includes(o);
            return <button key={o} type="button" aria-pressed={on} className={pill(on)} onClick={() => { const next = on ? sel.filter((x) => x !== o) : [...sel, o]; onChange(next.length ? next : undefined); }}>{on ? "✓ " : ""}{o}</button>;
          })}
          <span className="w-full text-xs text-muted">{t("survey.pickAny")}</span>
        </div>
      );
    }
    case "matrix": {
      const cur = value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, string>) : {};
      return (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr><th /> {q.options?.map((o) => <th key={o} className="px-2 py-1 text-xs font-medium text-muted">{o}</th>)}</tr></thead>
            <tbody>
              {q.rows?.map((r) => (
                <tr key={r} className="border-t border-line">
                  <th scope="row" className="py-1.5 pr-2 text-left font-medium">{r}</th>
                  {q.options?.map((o) => (
                    <td key={o} className="text-center">
                      <input type="radio" name={`${q.id}-${r}`} checked={cur[r] === o} aria-label={`${r}: ${o}`} onChange={() => onChange({ ...cur, [r]: o })} className="h-4 w-4 accent-[var(--accent)]" />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    default:
      return <textarea value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value || undefined)} maxLength={2000} rows={3} aria-label={q.text} className="w-full rounded-xl border-2 border-line bg-surface p-2" />;
  }
}

/** Answers a survey with autosaved drafts (save-and-resume) and required-question checks. */
export function SurveyRunner({ questions, initial, saveDraft, submit, onDone }: {
  questions: Question[];
  initial?: Record<string, AnswerValue>;
  saveDraft: (a: Record<string, AnswerValue>) => Promise<unknown>;
  submit: (a: Record<string, AnswerValue>) => Promise<unknown>;
  onDone: (res?: SubmitResult) => void;
}) {
  const { t } = useTranslation();
  const [answers, setAnswers] = useState<Record<string, AnswerValue>>(initial ?? {});
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<"" | "saving" | "saved">("");
  const [err, setErr] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dirty = useRef(false);
  const missing = questions.filter((q) => q.required && (answers[q.id] === undefined || answers[q.id] === "")).length;

  useEffect(() => {
    if (!dirty.current) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      setSaved("saving");
      try {
        await saveDraft(answers);
        setSaved("saved");
      } catch {
        setSaved("");
      }
    }, 900);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [answers, saveDraft]);

  const set = (id: string, v: AnswerValue | undefined) => {
    dirty.current = true;
    setAnswers((a) => {
      const next = { ...a };
      if (v === undefined) delete next[id];
      else next[id] = v;
      return next;
    });
  };
  async function send() {
    setBusy(true);
    setErr("");
    if (timer.current) clearTimeout(timer.current);
    try {
      const res = await submit(answers);
      onDone(res && typeof res === "object" && "ok" in res ? (res as SubmitResult) : undefined);
    } catch (e) {
      const code = e instanceof ApiError ? String(e.data?.code ?? "") : "";
      setErr(code === "already_answered" ? t("org.alreadyAnswered") : code === "cooldown" ? t("credSurvey.run.coolingDown") : code === "required" ? t("survey.requiredLeft") : t("mentor.errors.generic"));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-5">
      {questions.map((q, i) => (
        <div key={q.id} className="space-y-2">
          {q.section && q.section !== questions[i - 1]?.section && <h3 className="border-b border-line pb-1 pt-2 font-display text-lg font-bold">{q.section}</h3>}
          <p className="font-medium">{i + 1}. {q.text}{q.required && <span className="text-bad" aria-label={t("survey.required")}> *</span>}</p>
          <QuestionInput q={q} value={answers[q.id]} onChange={(v) => set(q.id, v)} />
        </div>
      ))}
      <div className="flex flex-wrap items-center gap-3">
        <Button loading={busy} disabled={missing > 0 || !Object.keys(answers).length} onClick={() => void send()}>{t("org.submit")}</Button>
        {missing > 0 && <span className="text-sm text-muted">{t("survey.requiredN", { count: missing })}</span>}
        {saved && <span role="status" className="text-xs text-muted">{saved === "saving" ? t("survey.saving") : t("survey.saved")}</span>}
        {err && <span role="alert" className="text-sm text-bad">{err}</span>}
      </div>
    </div>
  );
}
