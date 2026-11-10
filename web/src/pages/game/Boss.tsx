import { useQueryClient } from "@tanstack/react-query";
import confetti from "canvas-confetti";
import { motion } from "motion/react";
import { ArrowRight, Heart } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { ActivityCard } from "@/activities/ActivityCard";
import type { AttemptResult } from "@/activities/types";
import { PageError } from "@/components/PageState";
import { Button, Card } from "@/components/ui";
import { api } from "@/lib/api";
import { celebrate, gameKey, type Reward } from "@/lib/game";
import { fetchSession, type ReviewCardData } from "@/lib/review";
import { useMe } from "@/lib/useMe";
import { Kili } from "@/mascot/Kili";
import { sfx } from "@/mascot/sfx";

const HEARTS = 3;

/** Section boss: every correct answer hits the boss; wrong answers cost a heart. */
export default function BossPage() {
  const { t } = useTranslation();
  const { courseId, sectionId } = useParams();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const [cards, setCards] = useState<ReviewCardData[] | null>(null);
  const [i, setI] = useState(0);
  const [hits, setHits] = useState(0);
  const [hearts, setHearts] = useState(HEARTS);
  const [answered, setAnswered] = useState(false);
  const [shake, setShake] = useState(0);
  const [verdict, setVerdict] = useState<{ won: boolean; score: number; reward?: Reward } | null>(null);
  const [loadErr, setLoadErr] = useState<unknown>(null);
  const [saveErr, setSaveErr] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchSession({ mode: "section", section: String(sectionId), limit: "8" }).then((s) => setCards(s.cards), setLoadErr);
  }, [sectionId]);

  const total = cards?.length ?? 0;
  const bossHp = total ? Math.max(0, 1 - hits / Math.ceil(total * 0.7)) : 1;

  async function finish() {
    type Verdict = { won: boolean; score: number; reward?: Reward };
    setSaving(true);
    setSaveErr(false);
    let r: Verdict;
    try {
      r = await api<Verdict>(`/api/game/boss/${sectionId}/result/`, { method: "POST" });
    } catch {
      setSaveErr(true); // a failed save is not a defeat: let the learner try sending it again
      return;
    } finally {
      setSaving(false);
    }
    setVerdict(r);
    if (r.won) {
      sfx("levelup");
      if (!me?.preferences.appearance.reduced_motion) void confetti({ particleCount: 200, spread: 110, origin: { y: 0.5 } });
      celebrate(r.reward, { reducedMotion: true, invalidate: () => void qc.invalidateQueries({ queryKey: gameKey }) });
    }
  }

  function graded(r: AttemptResult) {
    setAnswered(true);
    if (r.correct) {
      setHits((h) => h + 1);
      setShake((s) => s + 1);
    } else setHearts((h) => h - 1);
  }

  function next() {
    if (hearts <= 0 || i + 1 >= total || bossHp <= 0) return void finish();
    setI(i + 1);
    setAnswered(false);
  }

  const kili = { color: me?.preferences.mascot.color, accessories: me?.preferences.mascot.accessories, outfit: me?.preferences.mascot.outfit };

  if (verdict) {
    return (
      <div className="mx-auto max-w-xl px-4 py-12">
        <Card className="flex flex-col items-center gap-3 text-center">
          <Kili mood={verdict.won ? "celebrate" : "hmm"} size={160} {...kili} />
          <h1 className="font-display text-3xl font-extrabold">{verdict.won ? t("boss.won") : t("boss.lost")}</h1>
          <p className="text-muted">{verdict.won ? t("boss.wonSub") : t("boss.lostSub")}</p>
          <div className="flex gap-2">
            <Link to={`/learn/${courseId}`} className="rounded-xl border-2 border-line px-4 py-2 font-semibold hover:border-accent">{t("lesson.backToPath")}</Link>
            {!verdict.won && <Button onClick={() => location.reload()}>{t("boss.retry")}</Button>}
          </div>
        </Card>
      </div>
    );
  }

  if (loadErr) return <PageError error={loadErr} onRetry={() => location.reload()} />;
  if (!cards) return <p className="p-8 text-muted">{t("common.loading")}</p>;
  if (!total) return <p className="p-8 text-muted">{t("review.nothingSub")}</p>;
  const c = cards[i];
  return (
    <div className="mx-auto max-w-3xl space-y-4 px-4 py-6">
      <Card className="flex items-center gap-4 overflow-hidden bg-gradient-to-r from-violet-900 to-fuchsia-800 text-white">
        <motion.div key={shake} animate={{ x: [0, -10, 10, -6, 0], rotate: [0, -8, 8, 0] }} transition={{ duration: 0.4 }} className="text-6xl" aria-hidden>
          👾
        </motion.div>
        <div className="flex-1">
          <p className="font-display text-xl font-bold">{t("boss.title")}</p>
          <div className="mt-1 h-3 overflow-hidden rounded-full bg-white/20"><motion.div className="h-full bg-red-500" animate={{ width: `${bossHp * 100}%` }} /></div>
        </div>
        <div className="flex gap-1" aria-label={t("boss.hearts", { count: hearts })}>
          {Array.from({ length: HEARTS }, (_, k) => <Heart key={k} className={k < hearts ? "h-6 w-6 fill-red-500 text-red-500" : "h-6 w-6 text-white/40"} />)}
        </div>
      </Card>
      <ActivityCard key={c.card_id} activity={c.activity} index={i} submitUrl={`/api/review/cards/${c.card_id}/answer/`} onGraded={graded} allowRetry={false} />
      {saveErr && <p role="alert" className="text-right text-sm text-bad">{t("page.saveFailed")}</p>}
      {answered && <div className="flex justify-end"><Button loading={saving} onClick={next}>{saveErr ? t("common.retry") : t("review.next")} <ArrowRight className="h-4 w-4" /></Button></div>}
    </div>
  );
}
