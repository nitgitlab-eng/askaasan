import { useQuery } from "@tanstack/react-query";
import { BookOpen, Dumbbell, Play, RotateCcw, Route, Sparkles, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { paths, type Rec } from "@/lib/paths";

const ICON: Record<Rec["kind"], LucideIcon> = { review: RotateCcw, continue: Play, practice: Dumbbell, next: BookOpen, start: Sparkles, path: Route };

/** "For you" — adaptive next-best actions, each with a one-line reason. */
export function ForYou() {
  const { t } = useTranslation();
  const { data } = useQuery({ queryKey: ["paths-recs"], queryFn: paths.recs, staleTime: 60_000 });
  if (!data?.length) return null;
  return (
    <section aria-labelledby="for-you" className="space-y-2">
      <div className="flex items-end justify-between">
        <h2 id="for-you" className="font-display text-xl font-bold">{t("paths.forYou")}</h2>
        <Link to="/skills" className="text-sm font-semibold text-accent">{t("paths.tune")}</Link>
      </div>
      <div className="-mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-2">
        {data.map((r, i) => {
          const Icon = ICON[r.kind] ?? Sparkles;
          return (
            <Link key={`${r.kind}-${r.link}-${i}`} to={r.link} className="w-60 shrink-0 snap-start rounded-2xl border-2 border-line bg-surface p-4 transition hover:border-accent">
              <span className="mb-2 flex h-9 w-9 items-center justify-center rounded-xl bg-accent/15 text-accent"><Icon className="h-5 w-5" /></span>
              <p className="text-xs font-semibold uppercase tracking-wide text-accent">{t(`paths.kind.${r.kind}`)}</p>
              <p className="line-clamp-2 font-display font-bold">{r.title}</p>
              <p className="mt-1 line-clamp-2 text-xs text-muted">{t(`paths.why.${r.why.key}`, { ...r.why.params, count: Number(r.why.params?.n ?? 0) })}</p>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
