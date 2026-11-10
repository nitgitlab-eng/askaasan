import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Trophy } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/cn";
import { orgs } from "@/lib/orgs";

/** Cockpit → Classes: "This week's top learners" expander per class (top 10 by XP; hidden learners only counted). */
export function ClassBoardToggle({ slug, id }: { slug: string; id: number }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="flex items-center gap-1 text-sm font-semibold text-accent">
        <Trophy className="h-4 w-4" /> {t("org.classBoard")}
        <ChevronDown className={cn("h-4 w-4 transition", open && "rotate-180")} />
      </button>
      {open && <ClassBoard slug={slug} id={id} />}
    </div>
  );
}

export function ClassBoard({ slug, id }: { slug: string; id: number }) {
  const { t, i18n } = useTranslation();
  const { data, isError } = useQuery({ queryKey: ["class-board", slug, id], queryFn: () => orgs.classBoard(slug, id) });
  if (isError) return <p className="mt-2 text-sm text-bad">{t("org.classBoardError")}</p>;
  if (!data) return <p className="mt-2 text-sm text-muted">…</p>;
  const day = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString(i18n.language, { day: "numeric", month: "short" });
  return (
    <div className="mt-2 space-y-2">
      <p className="text-xs text-muted">{t("org.classBoardWeek", { from: day(data.week_start), to: day(data.week_end) })}</p>
      {data.rows.length ? (
        <ol className="divide-y divide-line rounded-xl border border-line">
          {data.rows.map((r) => (
            <li key={r.user_id} className="flex items-center gap-3 px-3 py-1.5 text-sm">
              <span className="w-6 text-center font-bold">{r.rank}</span>
              <span className="min-w-0 flex-1 truncate">{r.name}</span>
              <span className="font-semibold tabular-nums">{r.xp} XP</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-sm text-muted">{t("org.classBoardEmpty")}</p>
      )}
      {data.hidden > 0 && <p className="text-xs text-muted">{t("org.classBoardHidden", { count: data.hidden })}</p>}
      {!data.enabled && <p className="text-xs text-muted">{t("org.classBoardOff")}</p>}
    </div>
  );
}
