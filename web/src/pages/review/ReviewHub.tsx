import { useQueryClient } from "@tanstack/react-query";
import confetti from "canvas-confetti";
import { motion } from "motion/react";
import { ArrowRight, Brain, CalendarClock, RotateCcw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";

import { localeOf } from "@/i18n/languages";
import { ActivityCard } from "@/activities/ActivityCard";
import type { AttemptResult } from "@/activities/types";
import { Button, Card } from "@/components/ui";
import { gameKey } from "@/lib/game";
import { fetchSession, useReviewOverview, type ReviewCardData } from "@/lib/review";
import { useMe } from "@/lib/useMe";
import { Kili } from "@/mascot/Kili";
import { sfx } from "@/mascot/sfx";
import { mascot } from "@/mascot/store";

type Phase = "idle" | "loading" | "running" | "done";

/**
 * Review hub. ?mode=section&section=ID (or mode=course&curriculum=ID) starts a
 * checkpoint quiz immediately; otherwise shows due cards with a Start button.
 */
export default function ReviewHub() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const { data: me } = useMe();
  const { data: ov } = useReviewOverview();
  const [phase, setPhase] = useState<Phase>("idle");
  const [loadErr, setLoadErr] = useState(false);
  const [cards, setCards] = useState<ReviewCardData[]>([]);
  const [i, setI] = useState(0);
  const [scores, setScores] = useState<number[]>([]);
  const [answered, setAnswered] = useState(false);
  const mode = params.get("mode") ?? "due";
  const EXAM_SECONDS = 300;
  const [left, setLeft] = useState(EXAM_SECONDS);
  useEffect(() => {
    if (mode !== "exam" || phase !== "running") return;
    const id = setInterval(() => setLeft((s) => s - 1), 1000);
    return () => clearInterval(id);
  }, [mode, phase]);
  useEffect(() => {
    if (mode === "exam" && phase === "running" && left <= 0) finish();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [left]);

  // Only the latest request may fill the session: an older one finishing late (React's dev double-run of effects, or
  // the section changing) would swap the cards under the learner and throw away the answer they were giving.
  const latest = useRef(0);
  async function start(extra: Record<string, string> = {}) {
    const req = ++latest.current;
    setPhase("loading");
    setLoadErr(false);
    const p: Record<string, string> = { mode, ...extra };
    params.forEach((v, k) => (p[k] = v));
    let s: Awaited<ReturnType<typeof fetchSession>>;
    try {
      s = await fetchSession(p);
    } catch {
      if (req !== latest.current) return;
      setLoadErr(true); // don't spin forever on a bad section id or a network error
      setPhase("idle");
      return;
    }
    if (req !== latest.current) return;
    setCards(s.cards);
    setI(0);
    setScores([]);
    setAnswered(false);
    setLeft(EXAM_SECONDS);
    setPhase(s.cards.length ? "running" : "done");
  }

  useEffect(() => {
    if (mode !== "due") void start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, params.get("section"), params.get("curriculum")]);

  function graded(r: AttemptResult) {
    setScores((s) => [...s, r.score]);
    setAnswered(true);
  }

  function next() {
    if (i + 1 < cards.length) {
      setI(i + 1);
      setAnswered(false);
      return;
    }
    finish();
  }

  function finish() {
    setPhase("done");
    void qc.invalidateQueries({ queryKey: ["review-overview"] });
    void qc.invalidateQueries({ queryKey: ["mastery"] });
    void qc.invalidateQueries({ queryKey: gameKey });
    const avg = scores.reduce((a, b) => a + b, 0) / Math.max(1, scores.length);
    if (avg >= 0.7) {
      sfx("levelup");
      mascot.react("celebrate");
      if (!me?.preferences.appearance.reduced_motion) void confetti({ particleCount: 120, spread: 70, origin: { y: 0.7 } });
    } else mascot.react("cheer");
  }

  const kili = { color: me?.preferences.mascot.color, accessories: me?.preferences.mascot.accessories, outfit: me?.preferences.mascot.outfit };
  const title = mode === "section" ? t("review.checkpoint") : mode === "course" ? t("review.courseQuiz") : mode === "quick" ? t("today.quickQuiz") : mode === "exam" ? t("exam.title") : t("review.title");

  if (phase === "running") {
    const c = cards[i];
    return (
      <div className="mx-auto max-w-3xl space-y-4 px-4 py-8">
        <header className="flex items-center justify-between gap-3">
          <h1 className="font-display text-2xl font-extrabold">{title}</h1>
          <span className="flex items-center gap-3 text-sm font-semibold text-muted">
            {mode === "exam" && <span role="timer" aria-label={t("exam.timeLeft")} className={left <= 30 ? "text-bad" : ""}>⏱ {Math.floor(Math.max(0, left) / 60)}:{String(Math.max(0, left) % 60).padStart(2, "0")}</span>}
            {i + 1} / {cards.length}
          </span>
        </header>
        <div className="h-2 overflow-hidden rounded-full bg-surface-2">
          <motion.div className="h-full bg-accent" animate={{ width: `${(100 * (i + (answered ? 1 : 0))) / cards.length}%` }} />
        </div>
        <p className="text-sm text-muted">📘 {c.lesson.title}</p>
        <ActivityCard key={c.card_id} activity={c.activity} index={i} submitUrl={`/api/review/cards/${c.card_id}/answer/`} onGraded={graded} allowRetry={false} askConfidence />
        {answered && (
          <div className="flex justify-end">
            <Button onClick={next}>{i + 1 < cards.length ? t("review.next") : t("review.finish")} <ArrowRight className="h-4 w-4" /></Button>
          </div>
        )}
      </div>
    );
  }

  if (phase === "done") {
    const avg = scores.length ? Math.round((100 * scores.reduce((a, b) => a + b, 0)) / scores.length) : null;
    return (
      <div className="mx-auto max-w-xl px-4 py-12">
        <Card className="flex flex-col items-center gap-3 text-center">
          <Kili mood={avg === null ? "sleepy" : avg >= 70 ? "celebrate" : "cheer"} size={150} {...kili} />
          <h1 className="font-display text-3xl font-extrabold">{avg === null ? t("review.nothing") : t("review.doneTitle")}</h1>
          {avg !== null && <p className="font-display text-5xl font-extrabold text-accent">{avg}%</p>}
          <p className="text-muted">{avg === null ? t("review.nothingSub") : mode === "exam" ? t("exam.result", { n: scores.length, total: cards.length }) : t("review.doneSub", { count: scores.length })}</p>
          <div className="flex flex-wrap justify-center gap-2">
            <Link to="/learn" className="rounded-xl border-2 border-line px-4 py-2 font-semibold hover:border-accent">{t("nav.learn")}</Link>
            <Link to="/mastery" className="rounded-xl bg-accent px-4 py-2 font-semibold text-accent-ink">{t("nav.mastery")}</Link>
          </div>
        </Card>
      </div>
    );
  }

  const nextDue = ov?.next_due_at ? new Date(ov.next_due_at).toLocaleString(localeOf(i18n.language), { weekday: "short", hour: "numeric", minute: "2-digit" }) : null;
  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("review.title")}</h1>
        <p className="text-muted">{t("review.sub")}</p>
      </header>
      {loadErr && <p role="alert" className="rounded-xl bg-bad/10 px-3 py-2 text-sm text-bad">{t("page.error")}</p>}
      <Card className="flex flex-col items-center gap-4 text-center sm:flex-row sm:text-left">
        <Kili mood={ov?.due ? "wave" : "sleepy"} size={120} {...kili} />
        <div className="flex-1 space-y-1">
          <p className="font-display text-4xl font-extrabold text-accent">{ov?.due ?? "…"}</p>
          <p className="font-semibold">{t("review.dueNow")}</p>
          <p className="text-sm text-muted">
            {ov?.due ? t("review.dueHint") : nextDue ? t("review.nextAt", { when: nextDue }) : t("review.emptyHint")}
          </p>
        </div>
        <Button onClick={() => void start()} disabled={!ov?.due} loading={phase === "loading"}>
          <RotateCcw className="h-4 w-4" /> {t("review.start")}
        </Button>
      </Card>
      <div className="grid gap-4 sm:grid-cols-3">
        <Card><Brain className="mb-1 h-5 w-5 text-accent" /><p className="text-sm text-muted">{t("review.total")}</p><p className="font-display text-2xl font-bold">{ov?.total ?? 0}</p></Card>
        <Card><CalendarClock className="mb-1 h-5 w-5 text-accent" /><p className="text-sm text-muted">{t("review.today")}</p><p className="font-display text-2xl font-bold">{ov?.reviewed_today ?? 0}</p></Card>
        <Card><p className="mb-1 text-sm text-muted">{t("review.byCourse")}</p>
          {ov?.by_course.length ? ov.by_course.map((c) => (
            <button key={c.curriculum_id} onClick={() => void start({ curriculum: String(c.curriculum_id) })} className="block w-full truncate text-left text-sm hover:text-accent">
              {c.title} · <b>{c.due}</b>
            </button>
          )) : <p className="text-sm">—</p>}
        </Card>
      </div>
    </div>
  );
}
