import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/cn";
import { paths } from "@/lib/paths";

/** Choose skills to focus on and rate yourself 1–5 on each (onboarding & the Skills page). */
export function SkillPicker({ value, onChange }: { value: Record<string, number>; onChange: (v: Record<string, number>) => void }) {
  const { t, i18n } = useTranslation();
  const { data } = useQuery({ queryKey: ["paths-skills"], queryFn: paths.skills });
  if (!data) return <p className="text-sm text-muted">{t("common.loading")}</p>;
  const cats = [...new Set(data.map((s) => s.category))];
  const name = (s: { name: string; name_ta: string }) => (i18n.language === "ta" && s.name_ta ? s.name_ta : s.name);
  const toggle = (slug: string) => {
    const next = { ...value };
    if (slug in next) delete next[slug];
    else next[slug] = 0;
    onChange(next);
  };
  return (
    <div className="max-h-[50vh] space-y-3 overflow-y-auto pr-1">
      {cats.map((c) => (
        <div key={c}>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{c}</p>
          <div className="flex flex-wrap gap-1.5">
            {data.filter((s) => s.category === c).map((s) => {
              const on = s.slug in value;
              return (
                <div key={s.slug} className={cn("flex items-center gap-1 rounded-full border-2 pl-3 pr-1 text-sm", on ? "border-accent bg-accent/10" : "border-line")}>
                  <button type="button" aria-pressed={on} onClick={() => toggle(s.slug)} className="py-1">{name(s)}</button>
                  {on && (
                    <span className="flex" role="radiogroup" aria-label={t("paths.rateYourself", { skill: name(s) })}>
                      {[1, 2, 3, 4, 5].map((n) => (
                        <button key={n} type="button" role="radio" aria-checked={value[s.slug] === n} title={t(`paths.levels.${n}`)}
                          onClick={() => onChange({ ...value, [s.slug]: n })} className={cn("mx-px h-3 w-3 rounded-full", n <= value[s.slug] ? "bg-accent" : "bg-surface-2")} />
                      ))}
                    </span>
                  )}
                  {!on && <span className="w-1" />}
                </div>
              );
            })}
          </div>
        </div>
      ))}
      <p className="text-xs text-muted">{t("paths.rateHint")}</p>
    </div>
  );
}
