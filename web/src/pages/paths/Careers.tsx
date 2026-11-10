import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ClipboardCheck, Route, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { Radar } from "@/components/charts";
import { CareerPlan30 } from "@/components/career/CareerPlan30";
import { MyCareerGoal } from "@/components/career/MyCareerGoal";
import { RoleLadder } from "@/components/career/RoleLadder";
import { QuizRunner } from "@/components/paths/QuizRunner";
import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { paths, type Career, type QuizQ } from "@/lib/paths";
import { mascot } from "@/mascot/store";

const title = (c: { title: string; title_ta: string }, lang: string) => (lang === "ta" && c.title_ta ? c.title_ta : c.title);

/** Career paths for the Indian job market: role requirements, readiness, and an AI role assessment. */
export default function CareersPage() {
  const { slug } = useParams();
  return slug ? <CareerDetail slug={slug} /> : <CareerList />;
}

function CareerList() {
  const { t, i18n } = useTranslation();
  const { data } = useQuery({ queryKey: ["careers"], queryFn: paths.careers });
  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("paths.careersTitle")}</h1>
        <p className="text-muted">{t("paths.careersSub")}</p>
      </header>
      <MyCareerGoal />
      {!data && <p className="text-muted">{t("common.loading")}</p>}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {data?.map((c) => (
          <Link key={c.slug} to={`/careers/${c.slug}`} className="rounded-2xl border-2 border-line bg-surface p-4 transition hover:border-accent">
            <p className="text-3xl" aria-hidden>{c.emoji}</p>
            <p className="font-display text-lg font-bold">{title(c, i18n.language)}</p>
            <p className="line-clamp-2 text-sm text-muted">{c.summary}</p>
            {c.salary_band && <p className="mt-2 text-xs font-semibold">{c.salary_band}</p>}
          </Link>
        ))}
      </div>
      <p className="text-xs text-muted">{t("paths.salaryNote")}</p>
    </div>
  );
}

type Result = { levels: Record<string, number>; score: number; reveal: { id: number; correct: number; explanation: string }[] };

function CareerDetail({ slug }: { slug: string }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const { data: c, isError } = useQuery({ queryKey: ["career", slug], queryFn: () => paths.career(slug) });
  const [quiz, setQuiz] = useState<{ id: number; questions: QuizQ[] } | null>(null);
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (isError) return <p className="p-8 text-muted">{t("paths.notFound")}</p>;
  if (!c) return <p className="p-8 text-muted">{t("common.loading")}</p>;
  const name = (r: { name: string; name_ta: string }) => (i18n.language === "ta" && r.name_ta ? r.name_ta : r.name);

  async function begin() {
    setBusy(true);
    setError("");
    setResult(null);
    mascot.react("thinking", 0);
    try {
      setQuiz(await paths.startAssessment(slug));
      mascot.react("cheer");
    } catch (e) {
      const code = e instanceof ApiError ? (e.data?.code as string | undefined) : undefined;
      setError(code === "ai_budget_exceeded" ? t("paths.budget") : t("paths.assessFailed"));
      mascot.react("hmm");
    } finally {
      setBusy(false);
    }
  }
  async function submit(a: Record<string, number>) {
    if (!quiz) return;
    setBusy(true);
    try {
      const r = await paths.submitAssessment(quiz.id, a);
      setAnswers(a);
      setResult(r);
      qc.setQueryData<Career>(["career", slug], r.career);
      void qc.invalidateQueries({ queryKey: ["paths-skills"] });
      void qc.invalidateQueries({ queryKey: ["paths-recs"] });
      mascot.react(r.score >= 0.6 ? "celebrate" : "cheer");
    } catch {
      setError(t("paths.assessFailed"));
    } finally {
      setBusy(false);
    }
  }
  const ready = Math.round((c.readiness ?? 0) * 100);
  const gaps = c.requirements?.filter((r) => r.gap > 0) ?? [];

  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-8">
      <Card className="bg-gradient-to-br from-accent/15 to-surface">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <p className="text-4xl" aria-hidden>{c.emoji}</p>
            <h1 className="font-display text-3xl font-extrabold">{title(c, i18n.language)}</h1>
            <p className="text-muted">{c.summary}</p>
            {c.salary_band && <p className="mt-2 text-sm"><span className="font-semibold">{t("paths.salary")}:</span> {c.salary_band}</p>}
            {c.outlook && <p className="text-sm"><span className="font-semibold">{t("paths.outlook")}:</span> {c.outlook}</p>}
          </div>
          <div className="text-center">
            <p className="font-display text-5xl font-extrabold tabular-nums">{ready}%</p>
            <p className="text-xs text-muted">{t("paths.readiness")}</p>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {!quiz && <Button loading={busy} onClick={() => void begin()}><ClipboardCheck className="h-4 w-4" /> {c.last_assessment ? t("paths.reassess") : t("paths.assess")}</Button>}
          {c.path && <Link to={`/paths/${c.path}`} className="flex items-center gap-1.5 rounded-xl border-2 border-accent px-3 py-2 text-sm font-semibold text-accent hover:bg-accent hover:text-accent-ink"><Route className="h-4 w-4" /> {t("paths.recommendedPath")}</Link>}
        </div>
        {error && <p role="alert" className="mt-2 text-sm text-bad">{error}</p>}
      </Card>

      <RoleLadder career={c} />

      {quiz && !result && (
        <Card>
          <h2 className="mb-3 font-display text-xl font-bold">{t("paths.assessTitle")}</h2>
          <QuizRunner questions={quiz.questions} onDone={(a) => void submit(a)} busy={busy} />
        </Card>
      )}

      {result && quiz && (
        <Card className="space-y-3">
          <h2 className="font-display text-xl font-bold">{t("paths.assessDone", { score: Math.round(result.score * 100) })}</h2>
          {!!gaps.length && <p className="text-sm">{t("paths.gapsFollowed", { count: gaps.length })} <Link to="/skills" className="font-semibold text-accent">{t("paths.skillsTitle")} →</Link></p>}
          <ol className="space-y-2">
            {quiz.questions.map((q) => {
              const rv = result.reveal.find((x) => x.id === q.id);
              const ok = rv && answers[q.id] === rv.correct;
              return (
                <li key={q.id} className="rounded-xl border border-line p-3 text-sm">
                  <p className="flex items-start gap-2 font-medium">{ok ? <Check className="h-4 w-4 shrink-0 text-good" aria-label={t("paths.right")} /> : <X className="h-4 w-4 shrink-0 text-bad" aria-label={t("paths.wrong")} />}{q.prompt}</p>
                  {rv && <p className="mt-1 text-muted">{q.options[rv.correct]} — {rv.explanation}</p>}
                </li>
              );
            })}
          </ol>
          <Button variant="ghost" onClick={() => { setQuiz(null); setResult(null); }}>{t("common.close")}</Button>
        </Card>
      )}

      {!!c.requirements?.length && (
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <Radar title={t("paths.radarTitle")} axes={c.requirements.map((r) => ({ label: name(r), value: r.level, target: r.required }))}
              labels={{ you: t("paths.you"), target: t("paths.required"), skill: t("paths.skill") }} />
          </Card>
          <Card>
            <h2 className="mb-3 font-display text-base font-bold">{t("paths.requirements")}</h2>
            <ul className="space-y-2">
              {c.requirements.map((r) => (
                <li key={r.skill} className="text-sm">
                  <div className="flex justify-between"><span className="font-medium">{name(r)}</span><span className={cn("tabular-nums", r.gap ? "text-muted" : "text-good")}>{r.level}/{r.required}{!r.gap && " ✓"}</span></div>
                  <div className="mt-1 flex gap-0.5" aria-hidden>
                    {Array.from({ length: 4 }, (_, k) => <span key={k} className={cn("h-1.5 flex-1 rounded-full", k < r.level ? "bg-accent" : k < r.required ? "bg-surface-2 ring-1 ring-line" : "bg-transparent")} />)}
                  </div>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-muted">{t("paths.levelScale")}</p>
          </Card>
        </div>
      )}

      <CareerPlan30 slug={slug} />
    </div>
  );
}
