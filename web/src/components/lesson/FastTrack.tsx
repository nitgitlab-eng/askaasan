import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Zap } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { journey, type FastTrackQ, type FastTrackResult } from "@/lib/journey";

/** "I already know this — fast-track": a short, harder check; all correct completes the lesson (keys stay on the server). */
export function FastTrack({ lessonId, courseId, lang, autoOpen = false }: { lessonId: number; courseId: number; lang: string; autoOpen?: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [run, setRun] = useState<{ run_id: number; questions: FastTrackQ[] } | null>(null);
  const [picked, setPicked] = useState<Record<number, number>>({});
  const [result, setResult] = useState<FastTrackResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState(autoOpen); // opened straight from an adaptive "quick check" step

  const start = async () => {
    setBusy(true);
    setErr("");
    setResult(null);
    setPicked({});
    try { setRun(await journey.fastTrack(lessonId, lang)); }
    catch (e) { setErr(e instanceof ApiError && e.status === 429 ? t("lj.fast.budget") : t("lj.fast.error")); }
    finally { setBusy(false); }
  };
  const submit = async () => {
    if (!run) return;
    if (run.questions.some((q) => picked[q.id] === undefined)) return setErr(t("lj.fast.pick"));
    setBusy(true);
    setErr("");
    try {
      const r = await journey.submitFastTrack(run.run_id, picked);
      setResult(r);
      void qc.invalidateQueries({ queryKey: ["adaptive-path", courseId] }); // pass or fail, the path may change
      if (r.passed) {
        void qc.invalidateQueries({ queryKey: ["course", courseId] });
        void qc.invalidateQueries({ queryKey: ["courses"] });
      }
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 409 ? t("lj.fast.answered") : t("lj.fast.error"));
      if (e instanceof ApiError && e.status === 409) setRun(null);
    } finally { setBusy(false); }
  };
  const close = () => { setOpen(false); setRun(null); setResult(null); setErr(""); };

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="inline-flex items-center gap-2 rounded-xl border-2 border-line px-3 py-1.5 text-sm font-semibold hover:border-accent">
        <Zap className="h-4 w-4 text-accent" /> {t("lj.fast.open")}
      </button>
    );
  }
  const review = new Map(result?.results.map((r) => [r.id, r]) ?? []);
  return (
    <Card className="space-y-3 border-accent/50">
      <p className="flex items-center gap-2 font-semibold"><Zap className="h-5 w-5 text-accent" /> {t("lj.fast.open")}</p>
      {!run ? (
        <>
          <p className="text-sm text-muted">{t("lj.fast.intro")}</p>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void start()} loading={busy}>{busy ? t("lj.fast.loading") : t("lj.fast.start")}</Button>
            <Button variant="ghost" onClick={close}>{t("lj.fast.cancel")}</Button>
          </div>
        </>
      ) : (
        <>
          <p className="text-sm text-muted">{t("lj.fast.sub", { n: run.questions.length })}</p>
          {run.questions.map((q, qi) => {
            const rv = review.get(q.id);
            return (
              <fieldset key={q.id} className="space-y-1.5">
                <legend className="font-medium">{qi + 1}. {q.prompt}</legend>
                {q.options.map((o, j) => (
                  <label key={j} className={cn("flex cursor-pointer items-center gap-2 rounded-lg border-2 px-3 py-1.5 text-sm",
                    rv ? (rv.answer.includes(j) ? "border-good bg-good/10" : picked[q.id] === j ? "border-bad bg-bad/10" : "border-line") : picked[q.id] === j ? "border-accent bg-accent/10" : "border-line")}>
                    <input type="radio" name={`ft-${q.id}`} checked={picked[q.id] === j} disabled={!!result}
                      onChange={() => setPicked((p) => ({ ...p, [q.id]: j }))} />
                    {o}
                  </label>
                ))}
                {rv && !rv.correct && <p className="text-xs text-muted">{t("lj.fast.answerIs", { answer: rv.answer.map((i) => q.options[i]).join(", ") })}{rv.explanation ? ` — ${rv.explanation}` : ""}</p>}
              </fieldset>
            );
          })}
          {!result && <Button onClick={() => void submit()} loading={busy}>{t("lj.fast.submit")}</Button>}
          {result?.passed && (
            <div className="space-y-2" role="status">
              <p className="font-semibold text-good">{t("lj.fast.passed", { pct: Math.round(result.score * 100) })}</p>
              {result.next_subsection_id ? (
                <Button onClick={() => navigate(`/learn/${courseId}/lesson/${result.next_subsection_id}`)}>{t("lj.fast.next")} <ArrowRight className="h-4 w-4" /></Button>
              ) : <Button variant="outline" onClick={() => navigate(`/learn/${courseId}`)}>{t("lesson.backToPath")}</Button>}
            </div>
          )}
          {result && !result.passed && (
            <div className="space-y-2" role="status">
              <p className="font-semibold">{t("lj.fast.failed")}</p>
              <Button variant="outline" onClick={close}>{t("lj.fast.learn")}</Button>
            </div>
          )}
        </>
      )}
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
    </Card>
  );
}
