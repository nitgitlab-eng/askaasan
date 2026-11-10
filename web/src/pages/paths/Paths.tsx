import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Play, Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { createCourse } from "@/lib/learn";
import { paths, type PathCard } from "@/lib/paths";

const title = (p: { title: string; title_ta: string }, lang: string) => (lang === "ta" && p.title_ta ? p.title_ta : p.title);

/** Curated learning paths: browse, join, and start each step as an AI-built course. */
export default function PathsPage() {
  const { slug } = useParams();
  return slug ? <PathDetail slug={slug} /> : <PathList />;
}

function PathList() {
  const { t, i18n } = useTranslation();
  const { data } = useQuery({ queryKey: ["paths-curated"], queryFn: paths.curated });
  const mine = data?.filter((p) => p.joined) ?? [];
  const rest = data?.filter((p) => !p.joined) ?? [];
  const grid = (list: PathCard[]) => (
    <div className="grid gap-3 sm:grid-cols-2">
      {list.map((p) => (
        <Link key={p.slug} to={`/paths/${p.slug}`} className="rounded-2xl border-2 border-line bg-surface p-4 transition hover:border-accent">
          <p className="text-3xl" aria-hidden>{p.emoji}</p>
          <p className="font-display text-lg font-bold">{title(p, i18n.language)}</p>
          <p className="text-sm text-muted">{p.description}</p>
          <p className="mt-2 text-xs text-muted">{t(`learn.levels.${p.level}`)} · {t("paths.stepsN", { count: p.steps_n })}{p.org ? ` · ${p.org}` : ""}</p>
        </Link>
      ))}
    </div>
  );
  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("paths.pathsTitle")}</h1>
        <p className="text-muted">{t("paths.pathsSub")}</p>
      </header>
      {!data && <p className="text-muted">{t("common.loading")}</p>}
      {!!mine.length && <section className="space-y-2"><h2 className="font-display text-xl font-bold">{t("paths.myPaths")}</h2>{grid(mine)}</section>}
      {!!rest.length && <section className="space-y-2"><h2 className="font-display text-xl font-bold">{t("paths.browse")}</h2>{grid(rest)}</section>}
    </div>
  );
}

function PathDetail({ slug }: { slug: string }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data: p, isError } = useQuery({ queryKey: ["path", slug], queryFn: () => paths.path(slug) });
  const [busy, setBusy] = useState<number | "join" | null>(null);
  const [error, setError] = useState("");
  if (isError) return <p className="p-8 text-muted">{t("paths.notFound")}</p>;
  if (!p) return <p className="p-8 text-muted">{t("common.loading")}</p>;

  async function join() {
    setBusy("join");
    setError("");
    try {
      qc.setQueryData(["path", slug], await paths.join(slug));
      void qc.invalidateQueries({ queryKey: ["paths-curated"] });
      void qc.invalidateQueries({ queryKey: ["paths-recs"] });
    } catch {
      setError(t("mentor.errors.generic")); // a failed join used to be an unhandled rejection with no message
    } finally {
      setBusy(null);
    }
  }
  async function start(index: number, goal: string) {
    setBusy(index);
    setError("");
    try {
      if (!p!.joined) await paths.join(slug);
      const c = await createCourse({ goal, level: p!.level });
      await paths.linkStep(slug, index, c.id);
      void qc.invalidateQueries({ queryKey: ["courses"] });
      navigate(`/learn/${c.id}`);
    } catch (e) {
      const code = e instanceof ApiError ? (e.data?.code as string | undefined) : undefined;
      setError(code === "too_many_generating" ? t("learn.tooMany") : code === "plan_limit" ? t("paths.planLimit") : t("learn.createFailed"));
    } finally {
      setBusy(null);
    }
  }
  const firstOpen = p.steps?.findIndex((s) => !s.course || s.course.done < s.course.total) ?? 0;

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">
      <Card className="bg-gradient-to-br from-accent/15 to-surface">
        <p className="text-4xl" aria-hidden>{p.emoji}</p>
        <h1 className="font-display text-3xl font-extrabold">{title(p, i18n.language)}</h1>
        <p className="text-muted">{p.description}</p>
        <p className="mt-1 text-xs text-muted">{t(`learn.levels.${p.level}`)} · {t("paths.stepsN", { count: p.steps_n })}</p>
        {!p.joined && <Button className="mt-3" loading={busy === "join"} onClick={() => void join()}><Plus className="h-4 w-4" /> {t("paths.join")}</Button>}
      </Card>
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      <ol className="space-y-3">
        {p.steps?.map((s) => {
          const done = !!s.course && s.course.total > 0 && s.course.done >= s.course.total;
          return (
            <li key={s.index}>
              <Card className={cn("flex items-center gap-4", s.index === firstOpen && "ring-2 ring-accent/40")}>
                <span className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-full font-bold", done ? "bg-good text-white" : "bg-surface-2")}>
                  {done ? <Check className="h-5 w-5" /> : s.index + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="font-semibold">{s.title}</p>
                  <p className="text-sm text-muted">{s.goal}</p>
                  {s.course && <p className="text-xs text-muted">{s.course.status === "generating" ? t("learn.building") : t("learn.progress", { done: s.course.done, count: s.course.total })}</p>}
                </div>
                {s.course ? (
                  <Link to={`/learn/${s.course.course_id}`} className="rounded-xl border-2 border-accent px-3 py-1.5 text-sm font-semibold text-accent hover:bg-accent hover:text-accent-ink">
                    {done ? t("paths.revisit") : t("paths.continue")}
                  </Link>
                ) : (
                  <Button loading={busy === s.index} disabled={busy !== null} onClick={() => void start(s.index, s.goal)}><Play className="h-4 w-4" /> {t("paths.startStep")}</Button>
                )}
              </Card>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
