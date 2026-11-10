import { useQuery } from "@tanstack/react-query";
import { ArrowRight, BookOpen, ClipboardList, Flame, RotateCcw, Send, Target } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { Card } from "@/components/ui";
import { api } from "@/lib/api";
import { orgs } from "@/lib/orgs";
import { ForYou } from "@/components/paths/ForYou";
import { CohortCourses, MemberFieldsPrompt } from "@/components/orgs/SchoolHomeCards";
import { PinnedCharts } from "@/components/study/PinnedCharts";
import { StreakRepairBanner } from "@/components/study/StreakRepairBanner";
import { TodayCard } from "@/components/study/TodayCard";
import { MyAssignmentsCard } from "@/pages/orgs/teach/MyAssignments";
import { JourneyHomeCard } from "@/components/journeys/JourneyHomeCard";
import { useGame } from "@/lib/game";
import { useReviewOverview } from "@/lib/review";
import { useMe } from "@/lib/useMe";

interface ConvRow {
  id: number;
  title: string;
  updated_at: string;
}

export default function HomePage() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const { data: convs } = useQuery({ queryKey: ["conversations"], queryFn: () => api<ConvRow[]>("/api/assistant/conversations/") });
  const { data: next } = useQuery({
    queryKey: ["continue"],
    queryFn: () => api<{ curriculum_id: number; curriculum_title: string; subsection_id: number; subsection_title: string } | null>("/api/learn/continue/"),
  });
  const { data: review } = useReviewOverview();
  const { data: game } = useGame();
  const name = me?.profile.display_name;
  const suggestions = t("home.suggestions", { returnObjects: true }) as string[];

  const ask = (text: string) => navigate("/mentor", { state: { ask: text } });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (q.trim()) ask(q.trim());
  };

  const { data: surveys } = useQuery({ queryKey: ["my-surveys"], queryFn: orgs.mySurveys });
  const openSurveys = surveys?.filter((s) => !s.answered).length ?? 0;

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold sm:text-4xl">{name ? t("home.greeting", { name }) : t("home.greetingNoName")}</h1>
        <p className="text-lg text-muted">{t("home.sub")}</p>
      </header>
      <StreakRepairBanner />

      <Link to={next ? `/learn/${next.curriculum_id}/lesson/${next.subsection_id}` : "/learn"} className="group block">
        <Card className="flex items-center gap-4 border-2 border-accent/40 transition group-hover:border-accent">
          <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-accent text-accent-ink">
            <BookOpen className="h-7 w-7" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-accent">{next ? t("learn.continue") : t("learn.start")}</p>
            <p className="truncate font-display text-xl font-bold">{next ? next.subsection_title : t("learn.newTitle")}</p>
            {next && <p className="truncate text-sm text-muted">{next.curriculum_title}</p>}
          </div>
          <ArrowRight className="h-6 w-6 text-accent transition group-hover:translate-x-1" />
        </Card>
      </Link>

      <MemberFieldsPrompt />
      <JourneyHomeCard />
      <TodayCard />
      <ForYou />
      <PinnedCharts />

      {openSurveys > 0 && (
        <Link to="/surveys" className="flex items-center gap-3 rounded-2xl border-2 border-accent/40 bg-accent/10 px-4 py-3 font-semibold hover:border-accent">
          <ClipboardList className="h-5 w-5 text-accent" /> {t("org.surveyBanner", { count: openSurveys })}
          <ArrowRight className="ml-auto h-5 w-5 text-accent" />
        </Link>
      )}

      <MyAssignmentsCard />

      <CohortCourses />

      <Card className="bg-gradient-to-br from-accent/15 to-surface">
        <h2 className="mb-3 font-display text-xl font-bold">{t("home.askMentor")}</h2>
        <form onSubmit={submit} className="flex gap-2">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t("home.askPlaceholder")}
            className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-4 py-3 outline-none focus:border-accent"
            aria-label={t("home.askMentor")}
          />
          <button className="rounded-xl bg-accent px-4 text-accent-ink" aria-label={t("mentor.send")}>
            <Send className="h-5 w-5" />
          </button>
        </form>
        <div className="mt-3 flex flex-wrap gap-2">
          {suggestions.map((s) => (
            <button key={s} onClick={() => ask(s)} className="rounded-full border border-line bg-surface px-3 py-1 text-sm hover:border-accent">
              {s}
            </button>
          ))}
        </div>
      </Card>

      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <Target className="mb-2 h-6 w-6 text-accent" />
          <p className="text-sm text-muted">{t("home.dailyGoal")}</p>
          <p className="font-display text-2xl font-bold">{t("home.minutes", { n: me?.preferences.learning.daily_goal_minutes ?? 15 })}</p>
        </Card>
        <Card>
          <Flame className="mb-2 h-6 w-6 text-orange-500" />
          <p className="text-sm text-muted">{t("home.streak")}</p>
          <p className="font-display text-2xl font-bold">{t("home.days", { count: game?.streak ?? 0 })}</p>
        </Card>
        <Link to="/review" className="group">
          <Card className="h-full transition group-hover:border-accent">
            <RotateCcw className="mb-2 h-6 w-6 text-accent" />
            <p className="text-sm text-muted">{t("home.review")}</p>
            <p className="font-display text-2xl font-bold">{t("review.homeCard", { n: review?.due ?? 0 })}</p>
          </Card>
        </Link>
      </div>

      <Card>
        <h2 className="mb-3 font-display text-xl font-bold">{t("home.recent")}</h2>
        {convs?.length ? (
          <ul className="divide-y divide-line">
            {convs.slice(0, 6).map((c) => (
              <li key={c.id}>
                <Link to={`/mentor/${c.id}`} className="block py-2 hover:text-accent">
                  {c.title || "…"}
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted">{t("home.none")}</p>
        )}
      </Card>
    </div>
  );
}
