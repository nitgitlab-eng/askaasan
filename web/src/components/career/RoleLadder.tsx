import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Card } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { Career, LadderRole } from "@/lib/paths";

function Rung({ label, roles, current }: { label: string; roles: LadderRole[]; current?: boolean }) {
  const { t, i18n } = useTranslation();
  return (
    <div className="min-w-0 flex-1">
      <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{label}</p>
      {roles.length ? (
        <ul className="space-y-1.5">
          {roles.map((r) => (
            <li key={r.slug}>
              <Link to={`/careers/${r.slug}`} aria-current={current ? "page" : undefined}
                className={cn("flex items-center gap-2 rounded-xl border-2 px-3 py-2 text-sm transition hover:border-accent", current ? "border-accent bg-accent/10 font-bold" : "border-line bg-surface")}>
                <span aria-hidden>{r.emoji}</span>
                <span className="min-w-0 flex-1 truncate">{i18n.language === "ta" && r.title_ta ? r.title_ta : r.title}</span>
                <span className="text-xs text-muted">{t(`jr.career.seniority.${r.seniority}`)}</span>
              </Link>
            </li>
          ))}
        </ul>
      ) : <p className="text-sm text-muted">—</p>}
    </div>
  );
}

/** Role ladder: where people come from → this role → next roles → senior roles. */
export function RoleLadder({ career }: { career: Career }) {
  const { t } = useTranslation();
  const l = career.ladder;
  if (!l) return null;
  const arrow = <ChevronRight className="hidden h-5 w-5 shrink-0 self-center text-muted md:block" aria-hidden />;
  return (
    <Card>
      <h2 className="mb-3 font-display text-xl font-bold">{t("jr.career.ladderTitle")}</h2>
      <div className="flex flex-col gap-4 md:flex-row">
        {!!l.previous.length && <><Rung label={t("jr.career.ladderPrev")} roles={l.previous} />{arrow}</>}
        <Rung label={t("jr.career.ladderNow")} roles={[l.current]} current />
        {arrow}
        <Rung label={t("jr.career.ladderNext")} roles={l.next} />
        {arrow}
        <Rung label={t("jr.career.ladderSenior")} roles={l.senior} />
      </div>
      {!l.next.length && !l.senior.length && <p className="mt-2 text-sm text-muted">{t("jr.career.ladderNone")}</p>}
    </Card>
  );
}
