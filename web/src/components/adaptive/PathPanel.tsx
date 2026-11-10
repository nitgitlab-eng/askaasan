import { ArrowRight, Dumbbell, Flag, Map as MapIcon, Route, Zap } from "lucide-react";
import type { TFunction } from "i18next";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Card } from "@/components/ui";
import { seenVersion, stepLink, usePath, useSkillMap, type LearnerPath, type PathItem } from "@/lib/adaptive";
import { cn } from "@/lib/cn";
import { mascot } from "@/mascot/store";

const ICON = { lesson: Route, skip_check: Zap, remediation: Dumbbell, final: Flag } as const;

function StepLabel({ it }: { it: PathItem }) {
  const { t } = useTranslation();
  const Icon = ICON[it.kind];
  return (
    <span className="flex min-w-0 items-center gap-2">
      <Icon className="h-4 w-4 shrink-0 text-accent" aria-hidden />
      <span className="min-w-0">
        <span className="block truncate font-semibold">{it.subsection?.title ?? t("adaptive.path.finalTitle")}</span>
        <span className="block text-xs text-muted">
          {t(`adaptive.path.kind.${it.kind}`)}
          {it.reason && ` · ${t(`adaptive.path.reason.${it.reason}`, { concept: it.concept?.title ?? "" })}`}
        </span>
      </span>
    </span>
  );
}

function changesText(t: TFunction, p: LearnerPath) {
  const parts = [];
  if (p.changes.practice) parts.push(t("adaptive.path.changed.practice", { count: p.changes.practice }));
  if (p.changes.skip) parts.push(t("adaptive.path.changed.skip", { count: p.changes.skip }));
  if (p.changes.unskip) parts.push(t("adaptive.path.changed.unskip", { count: p.changes.unskip }));
  return parts.join(" ");
}

/** The learner's own path through this course: what's next and why, and what changed since they last looked. */
export function PathPanel({ courseId }: { courseId: number }) {
  const { t } = useTranslation();
  const { data: p } = usePath(courseId);
  const [showMap, setShowMap] = useState(false);
  const [seen] = useState(() => seenVersion.get(courseId)); // as of opening the page
  const updated = p && seen && p.version > seen ? changesText(t, p) : "";

  useEffect(() => {
    if (!p) return;
    if (updated) mascot.say(t("adaptive.path.updatedSay"), { ms: 4000 });
    seenVersion.set(courseId, p.version);
  }, [p, courseId, t, updated]);

  if (!p) return null;
  const current = p.items.find((i) => i.current);
  const upcoming = p.items.filter((i) => i.status === "pending" && !i.current).slice(0, 4);
  const link = current ? stepLink(courseId, current) : null;
  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 font-display text-xl font-bold"><Route className="h-5 w-5 text-accent" /> {t("adaptive.path.title")}</h2>
        <span className="text-sm text-muted">{t("adaptive.path.progress", { done: p.done, count: p.items.length })}</span>
      </div>
      {updated && (
        <p role="status" className="rounded-xl bg-accent/10 px-3 py-2 text-sm">
          <strong>{t("adaptive.path.updated")}</strong> {updated}
        </p>
      )}
      {current ? (
        <div className={cn("flex flex-wrap items-center justify-between gap-3 rounded-xl border-2 border-accent p-3")}>
          <StepLabel it={current} />
          {link ? (
            <Link to={link} className="flex items-center gap-1 rounded-xl bg-accent px-3 py-1.5 text-sm font-semibold text-accent-ink">
              {t(`adaptive.path.go.${current.kind}`)} <ArrowRight className="h-4 w-4" />
            </Link>
          ) : (
            <span className="text-sm text-muted">{t("adaptive.path.finalHint")}</span>
          )}
        </div>
      ) : (
        <p className="text-sm font-semibold text-good">{t("adaptive.path.allDone")}</p>
      )}
      {upcoming.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{t("adaptive.path.next")}</p>
          <ol className="space-y-2">{upcoming.map((it) => <li key={it.id}><StepLabel it={it} /></li>)}</ol>
        </div>
      )}
      <button type="button" aria-expanded={showMap} className="flex items-center gap-1 text-sm font-semibold text-accent" onClick={() => setShowMap((v) => !v)}>
        <MapIcon className="h-4 w-4" /> {t(showMap ? "adaptive.map.hide" : "adaptive.map.show")}
      </button>
      {showMap && <SkillMapList courseId={courseId} />}
    </Card>
  );
}

const STATE_STYLE = {
  mastered: "bg-good text-white",
  learning: "bg-accent/15 text-accent",
  weak: "bg-bad/15 text-bad",
  new: "bg-surface-2 text-muted",
} as const;

/** v1 skill map: concepts in course order with their state; the critical ones count toward the goal. */
export function SkillMapList({ courseId }: { courseId: number }) {
  const { t } = useTranslation();
  const { data: m, isLoading } = useSkillMap(courseId);
  if (isLoading) return <p className="text-sm text-muted">{t("common.loading")}</p>;
  if (!m) return null;
  return (
    <div className="space-y-2">
      <p className="text-sm">{t("adaptive.map.summary", { done: m.critical_mastered, count: m.critical_total })}</p>
      <ul className="space-y-1.5">
        {m.concepts.map((c) => (
          <li key={c.key} className="flex items-center justify-between gap-3 text-sm">
            <span className="min-w-0">
              <span className="font-medium">{c.title}</span>
              {!c.critical && <span className="ml-1 text-xs text-muted">({t("adaptive.map.extra")})</span>}
            </span>
            <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold", STATE_STYLE[c.state])}>{t(`adaptive.map.state.${c.state}`)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
