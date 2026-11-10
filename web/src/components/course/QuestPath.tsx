import { ArrowDown, ArrowUp, Check, ClipboardCheck, EyeOff, Headphones, Lock, Play, Star } from "lucide-react";
import { motion } from "motion/react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { cn } from "@/lib/cn";

import type { MapLesson, MapSection } from "./CourseMap";

/** The classic view: every section in turn, lessons as round nodes on a winding quest path. */
export function QuestPath({ sections, courseId, editing, onMove, onHide }: {
  sections: MapSection[];
  courseId: number;
  editing: boolean;
  onMove: (section: MapSection, index: number, dir: -1 | 1) => void;
  onHide: (kind: "section" | "lesson", id: number) => void;
}) {
  const { t } = useTranslation();
  let k = 0;
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      {sections.map((s) => (
        <section key={s.id} id={`section-${s.id}`} className="scroll-mt-24 space-y-4">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h2 className="flex items-center gap-2 font-display text-xl font-bold">{s.title}
                {editing && <button type="button" aria-label={t("courseEdit.hideItem", { title: s.title })} title={t("courseEdit.hide")} className="text-muted hover:text-bad"
                  onClick={() => onHide("section", s.id)}><EyeOff className="h-4 w-4" /></button>}
              </h2>
              <p className="text-sm text-muted">{s.summary}</p>
            </div>
            {s.complete && (
              <div className="flex gap-2">
                <Link to={`/review?mode=section&section=${s.id}`} className="flex items-center gap-1.5 rounded-xl border-2 border-accent px-3 py-1.5 text-sm font-semibold text-accent hover:bg-accent hover:text-accent-ink">
                  <ClipboardCheck className="h-4 w-4" /> {t("review.checkpoint")}
                </Link>
                <Link to={`/learn/${courseId}/boss/${s.id}`} className="flex items-center gap-1.5 rounded-xl bg-violet-700 px-3 py-1.5 text-sm font-semibold text-white hover:bg-violet-800">
                  👾 {t("boss.fight")}
                </Link>
              </div>
            )}
          </div>
          <ol className="relative space-y-4">
            {s.lessons.map((l, bi) => (
              <li key={l.id} className="relative">
                <Node l={l} offset={[0, 48, 72, 48, 0, -48, -72, -48][k++ % 8]} />
                {editing && (
                  <span className="absolute right-0 top-6 flex gap-1.5">
                    <button type="button" aria-label={t("lj.lessons.up", { title: l.title })} disabled={bi === 0} className="text-muted hover:text-accent disabled:opacity-30"
                      onClick={() => onMove(s, bi, -1)}><ArrowUp className="h-4 w-4" /></button>
                    <button type="button" aria-label={t("lj.lessons.down", { title: l.title })} disabled={bi === s.lessons.length - 1} className="text-muted hover:text-accent disabled:opacity-30"
                      onClick={() => onMove(s, bi, 1)}><ArrowDown className="h-4 w-4" /></button>
                    <button type="button" aria-label={t("courseEdit.hideItem", { title: l.title })} title={t("courseEdit.hide")} className="text-muted hover:text-bad"
                      onClick={() => onHide("lesson", l.id)}><EyeOff className="h-4 w-4" /></button>
                  </span>
                )}
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}

function Node({ l, offset }: { l: MapLesson; offset: number }) {
  const { t } = useTranslation();
  const open = !l.locked && !l.done;
  const node = (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex items-center gap-4"
      style={{ marginLeft: `calc(50% - 40px + ${offset}px)` }}>
      <span className={cn(
        "relative flex h-20 w-20 shrink-0 items-center justify-center rounded-full border-b-8 text-2xl shadow-md transition",
        l.done && "border-good/70 bg-good text-white",
        open && "border-accent/60 bg-accent text-accent-ink ring-8 ring-accent/20",
        l.locked && "border-line bg-surface-2 text-muted",
      )}>
        {l.done ? <Check className="h-8 w-8" /> : l.locked ? <Lock className="h-7 w-7" /> : <Play className="h-8 w-8" />}
        {l.done && l.score !== null && l.score >= 0.999 && <Star className="absolute -right-1 -top-1 h-6 w-6 fill-yellow-400 text-yellow-500" />}
      </span>
      <span className="max-w-48">
        <span className="block font-semibold leading-tight">{l.title}</span>
        {l.done && l.score !== null && <span className="text-xs text-muted">{Math.round(l.score * 100)}%</span>}
        {l.step === "skip_check" && <span className="ml-1 inline-flex items-center gap-0.5 rounded-full bg-accent/15 px-1.5 text-xs font-semibold text-accent">⚡ {t("adaptive.path.kind.skip_check")}</span>}
        {l.step === "remediation" && <span className="ml-1 inline-flex items-center gap-0.5 rounded-full bg-bad/10 px-1.5 text-xs font-semibold text-bad">💪 {t("adaptive.path.kind.remediation")}</span>}
        {l.listened && (
          <span title={t("lj.listened.badgeTitle")} className="ml-1 inline-flex items-center gap-0.5 rounded-full bg-accent/15 px-1.5 text-xs font-semibold text-accent">
            <Headphones className="h-3 w-3" aria-hidden /> {t("lj.listened.badge")}
          </span>
        )}
      </span>
    </motion.div>
  );
  return l.locked ? <div aria-disabled title={t("learn.locked")}>{node}</div> : <Link to={l.href} aria-label={l.title}>{node}</Link>;
}
