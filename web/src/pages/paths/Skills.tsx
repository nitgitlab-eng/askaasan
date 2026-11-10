import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Eye, EyeOff, GripVertical, Plus, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { PageError } from "@/components/PageState";
import { Card } from "@/components/ui";
import { cn } from "@/lib/cn";
import { paths, type SkillRow } from "@/lib/paths";

/** Follow, hide, reorder and self-rate skills — this drives "For you" recommendations. */
export default function SkillsPage() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const { data, error, refetch } = useQuery({ queryKey: ["paths-skills"], queryFn: paths.skills });
  const [drag, setDrag] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const done = (rows: SkillRow[]) => {
    qc.setQueryData(["paths-skills"], rows);
    void qc.invalidateQueries({ queryKey: ["paths-recs"] });
  };
  const patch = useMutation({ mutationFn: ({ slug, body }: { slug: string; body: Parameters<typeof paths.setSkill>[1] }) => paths.setSkill(slug, body), onSuccess: done });
  const reorder = useMutation({ mutationFn: paths.reorder, onSuccess: done });
  if (error && !data) return <PageError error={error} onRetry={() => void refetch()} />;
  if (!data) return <p className="p-8 text-muted">{t("common.loading")}</p>;

  const name = (s: SkillRow) => (i18n.language === "ta" && s.name_ta ? s.name_ta : s.name);
  const followed = data.filter((s) => s.followed && !s.hidden).sort((a, b) => a.order - b.order);
  const hidden = data.filter((s) => s.hidden);
  const others = data.filter((s) => !s.followed && !s.hidden && name(s).toLowerCase().includes(filter.toLowerCase()));
  const move = (from: number, to: number) => {
    if (to < 0 || to >= followed.length || from === to) return;
    const slugs = followed.map((s) => s.slug);
    const [x] = slugs.splice(from, 1);
    slugs.splice(to, 0, x);
    reorder.mutate(slugs);
  };
  const mastery = (s: SkillRow) => (s.mastery === null ? null : Math.round(s.mastery * 100));

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("paths.skillsTitle")}</h1>
        <p className="text-muted">{t("paths.skillsSub")}</p>
        <p className="mt-1 text-sm"><Link to="/careers" className="font-semibold text-accent">{t("paths.exploreCareers")} →</Link></p>
      </header>

      <Card>
        <h2 className="mb-3 font-display text-xl font-bold">{t("paths.following")}</h2>
        {!followed.length && <p className="text-sm text-muted">{t("paths.noneFollowed")}</p>}
        <ol className="space-y-2">
          {followed.map((s, i) => (
            <li key={s.slug} draggable onDragStart={() => setDrag(s.slug)} onDragOver={(e) => e.preventDefault()}
              onDrop={() => { if (drag) move(followed.findIndex((x) => x.slug === drag), i); setDrag(null); }}
              className={cn("flex flex-wrap items-center gap-2 rounded-xl border-2 border-line bg-surface px-3 py-2", drag === s.slug && "opacity-50")}>
              <GripVertical className="h-4 w-4 cursor-grab text-muted" aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="font-semibold">{name(s)}</span>
                <span className="ml-2 text-xs text-muted">{s.category}</span>
                {mastery(s) !== null && <span className="ml-2 text-xs text-muted">· {t("paths.mastery", { n: mastery(s) })}</span>}
                {s.assessed_level > 0 && <span className="ml-2 text-xs text-muted">· {t("paths.assessed", { n: s.assessed_level })}</span>}
              </span>
              <span className="flex" role="radiogroup" aria-label={t("paths.rateYourself", { skill: name(s) })}>
                {[1, 2, 3, 4, 5].map((n) => (
                  <button key={n} role="radio" aria-checked={s.self_rating === n} title={t(`paths.levels.${n}`)} onClick={() => patch.mutate({ slug: s.slug, body: { self_rating: n } })}
                    className={cn("mx-0.5 h-3.5 w-3.5 rounded-full", n <= s.self_rating ? "bg-accent" : "bg-surface-2 ring-1 ring-line")} />
                ))}
              </span>
              <button onClick={() => move(i, i - 1)} disabled={i === 0} aria-label={t("paths.moveUp")} className="rounded p-1 text-muted hover:bg-surface-2 disabled:opacity-30"><ArrowUp className="h-4 w-4" /></button>
              <button onClick={() => move(i, i + 1)} disabled={i === followed.length - 1} aria-label={t("paths.moveDown")} className="rounded p-1 text-muted hover:bg-surface-2 disabled:opacity-30"><ArrowDown className="h-4 w-4" /></button>
              <button onClick={() => patch.mutate({ slug: s.slug, body: { followed: false } })} aria-label={t("paths.unfollow")} className="rounded p-1 text-muted hover:bg-surface-2"><X className="h-4 w-4" /></button>
            </li>
          ))}
        </ol>
      </Card>

      <Card>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-display text-xl font-bold">{t("paths.allSkills")}</h2>
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={t("paths.searchSkills")} aria-label={t("paths.searchSkills")}
            className="rounded-xl border-2 border-line bg-surface px-3 py-1.5 text-sm outline-none focus:border-accent" />
        </div>
        <ul className="grid gap-2 sm:grid-cols-2">
          {others.map((s) => (
            <li key={s.slug} className="flex items-center gap-2 rounded-xl border border-line px-3 py-2">
              <span className="min-w-0 flex-1"><span className="font-medium">{name(s)}</span> <span className="text-xs text-muted">{s.category}</span></span>
              <button onClick={() => patch.mutate({ slug: s.slug, body: { followed: true } })} className="flex items-center gap-1 rounded-lg bg-accent px-2 py-1 text-xs font-semibold text-accent-ink"><Plus className="h-3 w-3" /> {t("paths.follow")}</button>
              <button onClick={() => patch.mutate({ slug: s.slug, body: { hidden: true } })} aria-label={t("paths.hide", { skill: name(s) })} title={t("paths.hideHint")} className="rounded p-1 text-muted hover:bg-surface-2"><EyeOff className="h-4 w-4" /></button>
            </li>
          ))}
        </ul>
      </Card>

      {!!hidden.length && (
        <Card>
          <h2 className="mb-2 font-display text-lg font-bold">{t("paths.hidden")}</h2>
          <div className="flex flex-wrap gap-2">
            {hidden.map((s) => (
              <button key={s.slug} onClick={() => patch.mutate({ slug: s.slug, body: { hidden: false } })} className="flex items-center gap-1 rounded-full border border-line px-3 py-1 text-sm text-muted hover:border-accent">
                <Eye className="h-3.5 w-3.5" /> {name(s)}
              </button>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
