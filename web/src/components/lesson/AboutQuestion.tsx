import { useQuery, useQueryClient } from "@tanstack/react-query";
import { UserRound } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card } from "@/components/ui";
import { learner } from "@/lib/learner";

/** End of lesson: one short "about you" question at a time, so later lessons fit the learner. Skippable. */
export function AboutQuestion() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["about-me"], queryFn: learner.about });
  const [text, setText] = useState("");
  const [thanks, setThanks] = useState(false);
  const q = data?.next;
  if (thanks) return <Card><p className="text-sm text-muted">{t("about.thanks")}</p></Card>;
  if (!q) return null;
  const send = async (body: Parameters<typeof learner.answerAbout>[0]) => {
    qc.setQueryData(["about-me"], await learner.answerAbout(body));
    setText("");
    setThanks(true);
  };
  return (
    <Card className="space-y-3">
      <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted"><UserRound className="h-4 w-4" /> {t("about.kicker")}</p>
      <h2 className="font-display text-lg font-bold">{t(`about.q.${q.key}`)}</h2>
      {q.choices.length ? (
        <div className="flex flex-wrap gap-2">
          {q.choices.map((c) => <Button key={c} variant="outline" onClick={() => void send({ key: q.key, value: c })}>{t(`about.a.${q.key}.${c}`)}</Button>)}
        </div>
      ) : (
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) void send({ key: q.key, value: text.trim() }); }}>
          <input value={text} onChange={(e) => setText(e.target.value)} maxLength={300} placeholder={t(`about.ph.${q.key}`)}
            className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2" />
          <Button type="submit" disabled={!text.trim()}>{t("common.save")}</Button>
        </form>
      )}
      <button type="button" className="text-sm text-muted underline" onClick={() => void send({ skip: q.key })}>{t("about.skip")}</button>
    </Card>
  );
}
