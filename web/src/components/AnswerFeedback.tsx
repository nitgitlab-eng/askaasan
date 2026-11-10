import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { api } from "@/lib/api";
import { cn } from "@/lib/cn";

type Kind = "message" | "live" | "roleplay";
const REASONS = ["wrong", "unclear", "too_long", "unsafe", "other"] as const;

/** 👍/👎 on an AI answer. Only shown once the answer is saved (numeric id). */
export function AnswerFeedback({ kind, id, initial = 0 }: { kind: Kind; id: string | number; initial?: number }) {
  const { t } = useTranslation();
  const [rating, setRating] = useState(initial);
  const [asking, setAsking] = useState(false);
  const [comment, setComment] = useState("");
  const [sent, setSent] = useState(false);
  if (typeof id !== "number") return null;
  const send = (r: number, reason = "", note = "") =>
    api(`/api/assistant/feedback/${kind}/${id}/`, { method: "POST", json: { rating: r, reason, comment: note } }).catch(() => {});
  const vote = (r: 1 | -1) => {
    const next = rating === r ? 0 : r;
    setRating(next);
    setSent(false);
    setAsking(next === -1);
    void send(next);
  };
  return (
    <div className="mt-1 text-xs">
      <div className="flex items-center gap-1 text-muted">
        <button type="button" onClick={() => vote(1)} aria-pressed={rating === 1} aria-label={t("feedback.good")} title={t("feedback.good")}
          className={cn("rounded-lg p-1 hover:bg-surface-2", rating === 1 && "text-good")}><ThumbsUp className="h-3.5 w-3.5" /></button>
        <button type="button" onClick={() => vote(-1)} aria-pressed={rating === -1} aria-label={t("feedback.bad")} title={t("feedback.bad")}
          className={cn("rounded-lg p-1 hover:bg-surface-2", rating === -1 && "text-bad")}><ThumbsDown className="h-3.5 w-3.5" /></button>
        {sent && <span className="text-good">{t("feedback.thanks")}</span>}
      </div>
      {asking && !sent && (
        <div className="mt-1 space-y-1.5 rounded-xl border border-line bg-surface p-2">
          <p className="font-semibold">{t("feedback.why")}</p>
          <div className="flex flex-wrap gap-1">
            {REASONS.map((r) => (
              <button key={r} type="button" className="rounded-full border border-line px-2 py-0.5 hover:border-accent"
                onClick={() => { void send(-1, r, comment); setSent(true); setAsking(false); }}>{t(`feedback.reasons.${r}`)}</button>
            ))}
          </div>
          <input value={comment} onChange={(e) => setComment(e.target.value)} maxLength={500} placeholder={t("feedback.comment")}
            className="w-full rounded-lg border border-line bg-surface px-2 py-1" aria-label={t("feedback.comment")} />
          <Link to={`/help?report=answer&kind=${kind}&id=${id}`} className="font-semibold text-accent">{t("feedback.report")}</Link>
        </div>
      )}
    </div>
  );
}
