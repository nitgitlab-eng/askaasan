import { Star } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";

/** One-tap feedback on the recap screen; everything after the stars is optional. */
export function LessonFeedbackCard({ lessonId }: { lessonId: number }) {
  const { t } = useTranslation();
  const [rating, setRating] = useState(0);
  const [difficulty, setDifficulty] = useState<"" | "easy" | "right" | "hard">("");
  const [comment, setComment] = useState("");
  const [done, setDone] = useState(false);
  const save = (extra: object = {}) =>
    api(`/api/learn/subsections/${lessonId}/feedback/`, { method: "POST", json: { rating, difficulty, comment, ...extra } }).catch(() => {});
  if (done) return <Card className="text-center text-sm text-good">{t("lessonFb.thanks")}</Card>;
  return (
    <Card className="space-y-3">
      <p className="font-display text-lg font-bold">{t("lessonFb.title")}</p>
      <div role="radiogroup" aria-label={t("lessonFb.title")} className="flex gap-1">
        {[1, 2, 3, 4, 5].map((n) => (
          <button key={n} type="button" role="radio" aria-checked={rating === n} aria-label={t("lessonFb.stars", { count: n })}
            onClick={() => { setRating(n); void save({ rating: n }); }}>
            <Star className={cn("h-8 w-8 transition", n <= rating ? "fill-amber-400 text-amber-400" : "text-line")} />
          </button>
        ))}
      </div>
      {rating > 0 && (
        <>
          <div className="flex flex-wrap gap-2">
            {(["easy", "right", "hard"] as const).map((d) => (
              <button key={d} type="button" aria-pressed={difficulty === d} onClick={() => setDifficulty(d)}
                className={cn("rounded-full border-2 px-3 py-1 text-sm", difficulty === d ? "border-accent bg-accent/10" : "border-line")}>{t(`lessonFb.${d}`)}</button>
            ))}
          </div>
          <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={2} maxLength={500} placeholder={t("lessonFb.comment")}
            aria-label={t("lessonFb.comment")} className="w-full rounded-xl border-2 border-line bg-surface p-2 text-sm" />
          <Button className="py-1.5 text-sm" onClick={() => { void save(); setDone(true); }}>{t("lessonFb.send")}</Button>
        </>
      )}
    </Card>
  );
}
