import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Dumbbell, Drama, Map as MapIcon, Play, Plus, RefreshCw, RotateCcw, Timer, Trophy, Zap, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { PageError } from "@/components/PageState";
import { StreakRepairBanner } from "@/components/study/StreakRepairBanner";
import { Button, Card, Toggle } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { celebrate, gameKey, type Reward } from "@/lib/game";
import { baseKey, study, type Station, type StationKind, type Today } from "@/lib/study";
import { useMe } from "@/lib/useMe";
import { Kili } from "@/mascot/Kili";
import { mascot } from "@/mascot/store";

const ICON: Record<StationKind, LucideIcon> = { review: RotateCcw, weak: Dumbbell, quiz: Zap, roleplay: Drama, lesson: Play, exam: Timer };
const TIER_EMOJI: Record<string, string> = { seedling: "🌱", sprout: "🌿", explorer: "🧭", achiever: "🏅", scholar: "🎓", master: "🏆" };

/** P5: today's revision — a few themed stations, swappable, with a focus theme and a weekly revision board. */
export default function TodayPage() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const { data, error, refetch } = useQuery({ queryKey: ["today"], queryFn: study.today });
  const { data: board } = useQuery({ queryKey: ["revision-board"], queryFn: study.board });
  const set = (d: Today) => qc.setQueryData(["today"], d);

  if (error && !data) return <PageError error={error} onRetry={() => void refetch()} />;
  if (!data) return <p className="p-8 text-muted">{t("common.loading")}</p>;
  const all = data.total > 0 && data.done >= data.total;

  const detail = (s: Station) => {
    switch (baseKey(s.key)) {
      case "review": return t("today.reviewDetail", { count: s.n });
      case "weak": return t("today.weakDetail", { title: s.title, pct: s.pct });
      case "quiz": return t("today.quizDetail", { n: s.n });
      case "roleplay": return `${s.emoji ?? "🎭"} ${s.title}`;
      case "exam": return t("exam.detail", { n: s.n });
      default: return `${s.title} · ${s.course}`;
    }
  };
  async function markDone(key: string) {
    const r = await study.done(key);
    set(r);
    if (r.reward) {
      celebrate(r.reward as Reward, { reducedMotion: me?.preferences.appearance.reduced_motion, invalidate: () => void qc.invalidateQueries({ queryKey: gameKey }) });
      mascot.react("celebrate");
      void qc.invalidateQueries({ queryKey: ["revision-board"] });
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-8">
      <header className="flex flex-wrap items-center gap-4">
        <Kili mood={all ? "celebrate" : "wave"} size={90} color={me?.preferences.mascot.color} accessories={me?.preferences.mascot.accessories} outfit={me?.preferences.mascot.outfit} />
        <div className="min-w-0 flex-1">
          <h1 className="font-display text-3xl font-extrabold">{t("today.title")}</h1>
          <p className="text-muted">{all ? t("today.allDone") : t("today.sub", { done: data.done, count: data.total })}</p>
          <div className="mt-2 h-2 rounded-full bg-surface-2" role="progressbar" aria-valuemin={0} aria-valuemax={data.total} aria-valuenow={data.done}>
            <div className="h-2 rounded-full bg-accent transition-all" style={{ width: `${data.total ? (100 * data.done) / data.total : 0}%` }} />
          </div>
        </div>
      </header>
      <StreakRepairBanner />

      <div className="flex flex-wrap items-center gap-2" role="radiogroup" aria-label={t("today.focus")}>
        <span className="text-sm font-medium text-muted">{t("today.focus")}:</span>
        {[{ slug: "", name: t("today.mixed"), name_ta: "" }, ...data.themes].map((th) => (
          <button key={th.slug || "mixed"} role="radio" aria-checked={data.focus === th.slug} onClick={async () => set(await study.focus(th.slug))}
            className={cn("rounded-full border-2 px-3 py-1 text-sm", data.focus === th.slug ? "border-accent bg-accent/10 font-semibold" : "border-line hover:border-accent")}>
            {i18n.language === "ta" && th.name_ta ? th.name_ta : th.name}
          </button>
        ))}
        {!data.themes.length && <Link to="/skills" className="text-sm font-semibold text-accent">{t("today.followSkills")}</Link>}
      </div>

      {!data.stations.length && (
        <Card className="text-center">
          <p>{t("today.empty")}</p>
          <Link to="/learn" className="mt-2 inline-block font-semibold text-accent">{t("learn.start")} →</Link>
        </Card>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        {data.stations.map((s) => {
          const Icon = ICON[baseKey(s.key)] ?? Play;
          return (
            <Card key={s.key} className={cn("flex flex-col gap-3", s.done && "border-good/60 bg-good/5")}>
              <div className="flex items-start gap-3">
                <span className={cn("flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl", s.done ? "bg-good text-white" : "bg-accent/15 text-accent")}>
                  {s.done ? <Check className="h-6 w-6" /> : <Icon className="h-6 w-6" />}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="font-display text-lg font-bold">{baseKey(s.key) === "exam" ? t("exam.title") : t(`today.station.${baseKey(s.key)}`)}
                    {(s.round ?? 1) > 1 && <span className="ml-2 rounded-full bg-accent/15 px-2 py-0.5 text-xs font-semibold text-accent">{t("todayPlus.round", { n: s.round })}</span>}</p>
                  <p className="text-sm text-muted">{detail(s)}</p>
                  <p className="text-xs text-muted">~{s.minutes} {t("today.min")}</p>
                </div>
              </div>
              <div className="mt-auto flex flex-wrap items-center gap-2">
                <Link to={s.link} className="rounded-xl bg-accent px-3 py-1.5 text-sm font-semibold text-accent-ink">{s.done ? t("today.again") : t("today.go")}</Link>
                {!s.done && baseKey(s.key) !== "review" && <button onClick={() => void markDone(s.key)} className="rounded-xl border-2 border-line px-3 py-1.5 text-sm font-semibold hover:border-accent">{t("today.markDone")}</button>}
                {(baseKey(s.key) === "weak" || baseKey(s.key) === "roleplay") && (s.alts ?? 0) > 1 && data.swaps_left > 0 && (
                  <button onClick={async () => set(await study.swap(s.key))} className="ml-auto flex items-center gap-1 text-sm text-muted hover:text-accent">
                    <RefreshCw className="h-3.5 w-3.5" /> {t("today.another")}
                  </button>
                )}
              </div>
            </Card>
          );
        })}
      </div>

      {data.can_add_circuit && (
        <Card className="flex flex-wrap items-center justify-between gap-3 border-accent/50">
          <p className="font-semibold">{t("todayPlus.moreQ")}</p>
          <Button onClick={async () => set(await study.circuit())}><Plus className="h-4 w-4" /> {t("todayPlus.circuit")}</Button>
        </Card>
      )}

      <Card className="space-y-3">
        <h2 className="flex items-center gap-2 font-display text-xl font-bold"><MapIcon className="h-5 w-5 text-accent" /> {t("todayPlus.map")}</h2>
        <ol className="flex items-center gap-1 overflow-x-auto pb-1" aria-label={t("todayPlus.map")}>
          {data.tier.tiers.map((tr, idx) => {
            const reached = idx < data.tier.level;
            const here = idx === data.tier.level - 1;
            return (
              <li key={tr.key} className="flex items-center gap-1" aria-current={here ? "step" : undefined}>
                <span className={cn("flex min-w-20 flex-col items-center rounded-2xl border-2 px-2 py-1.5 text-center", here ? "border-accent bg-accent/15" : reached ? "border-good/50" : "border-line opacity-60")}>
                  <span className="text-2xl" aria-hidden>{TIER_EMOJI[tr.key]}</span>
                  <span className="text-xs font-semibold">{t(`todayPlus.tiers.${tr.key}`)}</span>
                  <span className="text-[10px] text-muted">{tr.at}+</span>
                </span>
                {idx < data.tier.tiers.length - 1 && <span className={cn("h-0.5 w-4", reached && idx + 1 < data.tier.level ? "bg-good" : "bg-line")} />}
              </li>
            );
          })}
        </ol>
        <p className="text-sm text-muted">{data.tier.next ? t("todayPlus.toNext", { points: data.tier.points, n: (data.tier.next_at ?? 0) - data.tier.points, next: t(`todayPlus.tiers.${data.tier.next}`) }) : t("todayPlus.top", { points: data.tier.points })}</p>
      </Card>

      {board && (
        <Card>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="flex items-center gap-2 font-display text-xl font-bold"><Trophy className="h-5 w-5 text-accent" /> {t("today.board")}</h2>
            <Toggle label={t("today.showMe")} checked={board.visible} onChange={async (v) => {
              await api("/api/game/settings/", { method: "POST", json: { show_on_leaderboard: v } });
              void qc.invalidateQueries({ queryKey: ["revision-board"] });
            }} />
          </div>
          {!board.rows.length ? <p className="text-sm text-muted">{t("today.boardEmpty")}</p> : (
            <ol className="divide-y divide-line">
              {board.rows.map((r) => (
                <li key={`${r.rank}-${r.name}`} className={cn("flex items-center gap-3 py-2", r.me && "font-semibold")}>
                  <span className="w-6 text-right tabular-nums text-muted">{r.rank}</span>
                  <span className="min-w-0 flex-1 truncate">{r.name}{r.me && ` (${t("paths.you")})`}</span>
                  <span className="text-xs text-muted">{t("today.boardReviews", { count: r.reviews })} · {t("today.boardStations", { count: r.stations })}</span>
                  <span className="w-12 text-right tabular-nums">{r.score}</span>
                </li>
              ))}
            </ol>
          )}
          <p className="mt-2 text-xs text-muted">{t("today.boardHint")}</p>
        </Card>
      )}
    </div>
  );
}
