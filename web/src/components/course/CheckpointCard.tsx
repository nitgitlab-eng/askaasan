import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Gauge, XCircle } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { learner, type CheckpointReview } from "@/lib/learner";

const pct = (x: number) => `${Math.round(x * 100)}%`;

/** Pre-test before the course, post-test after: shows how much you actually learned. */
export function CheckpointCard({ courseId, progress }: { courseId: number; progress: { done: number; total: number } }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const key = ["checkpoint", courseId];
  const { data } = useQuery({ queryKey: key, queryFn: () => learner.checkpoint(courseId),
    refetchInterval: (q) => (q.state.data?.status === "generating" ? 2500 : false) });
  const [taking, setTaking] = useState<"pre" | "post" | null>(null);
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [conf, setConf] = useState<Record<string, number>>({});
  const [review, setReview] = useState<CheckpointReview[] | null>(null);
  const [err, setErr] = useState("");
  if (!data) return null;
  const nearlyDone = progress.total > 0 && progress.done / progress.total >= 0.8;
  const want: "pre" | "post" | null = !data.pre && progress.done === 0 ? "pre" : data.pre && nearlyDone ? "post" : !data.pre && nearlyDone ? "post" : null;

  async function start(kind: "pre" | "post") {
    setErr("");
    setReview(null);
    setAnswers({});
    setConf({});
    if (data!.status !== "ready") qc.setQueryData(key, await learner.prepareCheckpoint(courseId).catch(() => data));
    setTaking(kind);
  }
  async function submit() {
    try {
      const r = await learner.submitCheckpoint(courseId, taking!, answers, conf);
      setReview(r.review);
      qc.setQueryData(key, { ...data!, pre: r.pre, post: r.post, gain: r.gain });
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 429 ? t("checkpoint.later") : t("mentor.errors.generic"));
    }
  }

  return (
    <Card className="space-y-3">
      <h2 className="flex items-center gap-2 font-display text-lg font-bold"><Gauge className="h-5 w-5 text-accent" /> {t("checkpoint.title")}</h2>
      <div className="flex flex-wrap gap-4 text-sm">
        <span>{t("checkpoint.before")}: <b>{data.pre ? pct(data.pre.score) : "—"}</b></span>
        <span>{t("checkpoint.after")}: <b>{data.post ? pct(data.post.score) : "—"}</b></span>
        {data.gain !== null && <span className={data.gain >= 0 ? "text-good" : "text-bad"}>{t("checkpoint.gain")}: <b>{data.gain >= 0 ? "+" : ""}{Math.round(data.gain * 100)} pts</b></span>}
      </div>
      {!taking && (
        <div className="flex flex-wrap items-center gap-2">
          {!data.pre && <Button variant={want === "pre" ? "primary" : "outline"} onClick={() => void start("pre")}>{t("checkpoint.takePre")}</Button>}
          {(data.pre || nearlyDone) && <Button variant={want === "post" ? "primary" : "outline"} onClick={() => void start("post")}>{t(data.post ? "checkpoint.retakePost" : "checkpoint.takePost")}</Button>}
          <p className="text-xs text-muted">{t(data.pre ? "checkpoint.hintPost" : "checkpoint.hintPre")}</p>
        </div>
      )}
      {taking && data.status !== "ready" && <p role="status" className="text-sm text-muted">{data.status === "failed" ? t("checkpoint.failed") : t("checkpoint.preparing")}</p>}
      {taking && data.status === "ready" && (
        <div className="space-y-4">
          {data.questions.map((q, qi) => {
            const r = review?.find((x) => x.id === q.id);
            return (
              <fieldset key={q.id} className="space-y-2 rounded-xl border border-line p-3">
                <legend className="px-1 font-semibold">{qi + 1}. {q.prompt}</legend>
                {q.options.map((o, i) => (
                  <label key={i} className={cn("flex items-center gap-2 rounded-lg px-2 py-1", r?.correct?.includes(i) && "bg-good/15", r && r.picked.includes(i) && !r.ok && "bg-bad/15")}>
                    <input type="radio" name={q.id} disabled={!!review} checked={answers[q.id] === i} onChange={() => setAnswers((a) => ({ ...a, [q.id]: i }))} />
                    {o}
                  </label>
                ))}
                {!review && (
                  <div className="flex flex-wrap items-center gap-1.5 text-xs">
                    <span className="text-muted">{t("confidence.ask")}</span>
                    {[1, 2, 3].map((v) => (
                      <button key={v} type="button" aria-pressed={conf[q.id] === v} onClick={() => setConf((c) => ({ ...c, [q.id]: v }))}
                        className={cn("rounded-full border px-2 py-0.5", conf[q.id] === v ? "border-accent bg-accent/15 font-semibold" : "border-line")}>{t(`confidence.v${v}`)}</button>
                    ))}
                  </div>
                )}
                {r && <p className={cn("flex items-start gap-1.5 text-sm", r.ok ? "text-good" : "text-bad")}>{r.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4" /> : <XCircle className="mt-0.5 h-4 w-4" />}
                  <span className="text-ink">{r.explanation ?? ""}{r.confidence === 3 && !r.ok ? ` ${t("confidence.sureWrong")}` : ""}</span></p>}
              </fieldset>
            );
          })}
          {!review ? <Button onClick={submit} disabled={Object.keys(answers).length < data.questions.length}>{t("checkpoint.submit")}</Button>
            : <Button variant="outline" onClick={() => { setTaking(null); setReview(null); }}>{t("common.close")}</Button>}
          {err && <p role="alert" className="text-sm text-bad">{err}</p>}
        </div>
      )}
    </Card>
  );
}
