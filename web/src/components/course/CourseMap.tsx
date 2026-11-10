import {
  ArrowDown, ArrowUp, BarChart3, Check, ChevronLeft, ChevronRight, CircleHelp, ClipboardCheck, Code2, Crosshair, Drama, EyeOff,
  FileCheck, GitBranch, Hand, Headphones, Link2, ListOrdered, Lock, MapPin, MousePointerClick, Network, PenLine, Play,
  Presentation, Shapes, Sparkles, Star, TextCursorInput, Video, Workflow,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { motion } from "motion/react";
import { useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { cn } from "@/lib/cn";
import { Kili } from "@/mascot/Kili";

import { layoutMap } from "./mapLayout";

export interface MapLesson {
  id: number;
  n: number; // 1-based position in the whole course
  title: string;
  objective: string;
  done: boolean;
  locked: boolean;
  /** The lesson to do next ("you are here"). */
  current: boolean;
  step?: string; // adaptive path step kind (skip_check, remediation…)
  score: number | null;
  minutes: number | null;
  activityCount: number;
  activityTypes: string[];
  skills: string[];
  listened: boolean;
  href: string;
}

export interface MapSection {
  id: number;
  n: number;
  title: string;
  summary: string;
  lessons: MapLesson[];
  done: number;
  complete: boolean;
}

const TYPE_ICON: Record<string, LucideIcon> = {
  quiz: CircleHelp, fill_blank: TextCursorInput, sequencing: ListOrdered, categorization: Shapes, matching: Link2,
  open_input: PenLine, code: Code2, diagram: Workflow, slides: Presentation, concept_map: Network, viz: BarChart3,
  decision_tree: GitBranch, task: Hand, map: MapPin, browser_task: MousePointerClick, roleplay: Drama, video: Video,
  hotspot: Crosshair, artifact_check: FileCheck,
};

const pct = (s: number) => `${Math.round(s * 100)}%`;

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setW(el.clientWidth);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

/** The learner's companion with one bubble per section around it; the chosen section glows. */
export function SectionHotspots({ sections, selected, onSelect, allDone }: { sections: MapSection[]; selected: number; onSelect: (id: number) => void; allDone: boolean }) {
  const { t } = useTranslation();
  const W = 280, H = 400, cx = W / 2, cy = H / 2;
  const spots = sections.map((s, i) => {
    const a = (-135 + (360 / sections.length) * i) * (Math.PI / 180); // from top-left, so 2 sections sit diagonally
    return { s, x: cx + Math.cos(a) * 112, y: cy + Math.sin(a) * 162 };
  });
  const sel = sections.find((s) => s.id === selected);
  return (
    <div className="relative mx-auto h-[400px] w-[280px]">
      <svg className="absolute inset-0" width={W} height={H} aria-hidden>
        {spots.map(({ s, x, y }) => (
          <path key={s.id} d={`M ${cx} ${cy} Q ${x} ${cy} ${x} ${y}`} fill="none" strokeLinecap="round"
            stroke={s.id === selected ? "var(--accent)" : "var(--border)"} strokeWidth={s.id === selected ? 2.5 : 2} />
        ))}
      </svg>
      <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
        <Kili mood={allDone || sel?.complete ? "cheer" : "idle"} size={150} />
      </div>
      {spots.map(({ s, x, y }) => {
        const on = s.id === selected;
        const left = s.lessons.length - s.done;
        return (
          <button key={s.id} type="button" aria-pressed={on} aria-label={t("courseMap.sectionN", { n: s.n }) + ": " + s.title}
            title={s.title} onClick={() => onSelect(s.id)}
            className={cn(
              "absolute flex -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full font-display font-bold shadow-md transition",
              on ? "h-16 w-16 bg-accent text-xl text-accent-ink ring-[10px] ring-accent/25" : "h-11 w-11 bg-surface text-ink hover:ring-4 hover:ring-accent/20",
            )}
            style={{ left: x, top: y }}>
            {on && <motion.span aria-hidden className="absolute inset-0 rounded-full bg-accent/30" animate={{ scale: [1, 1.5], opacity: [0.6, 0] }} transition={{ duration: 1.8, repeat: Infinity }} />}
            <span className="relative">{s.n}</span>
            <span className={cn("absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full px-1 text-[11px] font-bold", s.complete ? "bg-good text-white" : "bg-ink text-bg")}>
              {s.complete ? <Check className="h-3 w-3" aria-hidden /> : left}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/** What the chosen section is about, how far along it is, and its checkpoint / boss fight once every lesson is done. */
export function SectionDetail({ s, courseId, onHide }: { s: MapSection; courseId: number; onHide?: () => void }) {
  const { t } = useTranslation();
  const mins = s.lessons.reduce((m, l) => m + (l.minutes ?? 0), 0);
  return (
    <div className="rounded-3xl bg-surface p-4 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">{t("courseMap.sectionN", { n: s.n })}</p>
      <h2 className="flex items-start gap-2 font-display text-lg font-bold leading-tight">
        {s.title}
        {onHide && <button type="button" aria-label={t("courseEdit.hideItem", { title: s.title })} title={t("courseEdit.hide")} className="mt-0.5 text-muted hover:text-bad" onClick={onHide}><EyeOff className="h-4 w-4" /></button>}
      </h2>
      {s.summary && <p className="mt-1 line-clamp-3 text-sm text-muted">{s.summary}</p>}
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuemin={0} aria-valuemax={s.lessons.length} aria-valuenow={s.done}
        aria-label={t("learn.progress", { done: s.done, count: s.lessons.length })}>
        <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${s.lessons.length ? (s.done / s.lessons.length) * 100 : 0}%` }} />
      </div>
      <p className="mt-1.5 text-xs text-muted">
        {t("learn.progress", { done: s.done, count: s.lessons.length })}{mins > 0 && <> · {t("courseMap.minutes", { n: mins })}</>}
      </p>
      {s.complete && (
        <div className="mt-3 flex flex-wrap gap-2">
          <Link to={`/review?mode=section&section=${s.id}`} className="flex items-center gap-1.5 rounded-full border-2 border-accent px-3 py-1.5 text-sm font-semibold text-accent hover:bg-accent hover:text-accent-ink">
            <ClipboardCheck className="h-4 w-4" /> {t("review.checkpoint")}
          </Link>
          <Link to={`/learn/${courseId}/boss/${s.id}`} className="flex items-center gap-1.5 rounded-full bg-violet-700 px-3 py-1.5 text-sm font-semibold text-white hover:bg-violet-800">
            👾 {t("boss.fight")}
          </Link>
        </div>
      )}
    </div>
  );
}

/** Sections as a vertical rail on wide screens (the chosen one opens up), a row of chips on phones. */
export function SectionRail({ sections, selected, onSelect, detail }: { sections: MapSection[]; selected: number; onSelect: (id: number) => void; detail: React.ReactNode }) {
  const { t } = useTranslation();
  return (
    <nav aria-label={t("courseMap.sections")} className="min-w-0">
      <ul className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 lg:mx-0 lg:flex-col lg:overflow-visible lg:px-0">
        {sections.map((s) => {
          const on = s.id === selected;
          return (
            <li key={s.id} className="shrink-0 lg:shrink">
              {on && <div className="hidden lg:block">{detail}</div>}
              <button type="button" aria-pressed={on} onClick={() => onSelect(s.id)}
                className={cn(
                  "flex w-full items-center gap-2.5 rounded-full px-3 py-2 text-left text-sm font-medium transition lg:rounded-2xl lg:py-3",
                  on ? "bg-accent text-accent-ink lg:hidden" : "bg-surface hover:ring-2 hover:ring-accent/30",
                )}>
                <span className={cn("flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold", s.complete ? "bg-good text-white" : on ? "bg-accent-ink/20" : "bg-surface-2")}>
                  {s.complete ? <Check className="h-3.5 w-3.5" aria-hidden /> : s.n}
                </span>
                <span className="max-w-44 truncate lg:max-w-none lg:whitespace-normal lg:leading-tight">{s.title}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function LessonCard({ l, editing, controls }: { l: MapLesson; editing: boolean; controls?: React.ReactNode }) {
  const { t } = useTranslation();
  const open = !l.locked && !l.done;
  const Icon = l.done ? Check : l.locked ? Lock : l.current ? Play : Sparkles;
  const dark = l.current;
  const body = (
    <div className={cn(
      "relative flex h-full flex-col rounded-3xl p-4 transition",
      dark && "bg-ink text-bg shadow-xl ring-4 ring-accent/30",
      l.done && "bg-surface shadow-sm hover:-translate-y-0.5 hover:shadow-md",
      open && !dark && "border-2 border-accent bg-surface shadow-sm hover:-translate-y-0.5",
      l.locked && "border-2 border-dashed border-line bg-surface/60 text-muted",
    )}>
      <div className="flex items-start gap-2.5">
        <span className={cn("relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full",
          dark ? "bg-accent text-accent-ink" : l.done ? "bg-good/15 text-good" : l.locked ? "bg-surface-2" : "bg-accent/15 text-accent")}>
          <Icon className="h-4 w-4" aria-hidden />
          {l.done && l.score !== null && l.score >= 0.999 && <Star className="absolute -right-1.5 -top-1.5 h-4 w-4 fill-yellow-400 text-yellow-500" aria-hidden />}
        </span>
        <span className="min-w-0 flex-1">
          <span className={cn("block text-[11px] font-medium", dark ? "text-bg/70" : "text-muted")}>
            {t("courseMap.lessonN", { n: l.n })}{l.minutes ? <> · {t("courseMap.minutes", { n: l.minutes })}</> : null}
          </span>
          <span className="line-clamp-2 font-semibold leading-snug">{l.title}</span>
        </span>
        {!editing && (
          <span className="flex shrink-0 gap-1">
            {l.listened && <span title={t("lj.listened.badgeTitle")} className="rounded-full bg-accent/15 p-1 text-accent"><Headphones className="h-3 w-3" aria-label={t("lj.listened.badge")} /></span>}
            {l.step === "skip_check" && <span title={t("adaptive.path.kind.skip_check")} className="rounded-full bg-accent/15 px-1.5 text-xs">⚡</span>}
            {l.step === "remediation" && <span title={t("adaptive.path.kind.remediation")} className="rounded-full bg-bad/10 px-1.5 text-xs">💪</span>}
          </span>
        )}
      </div>
      <div className="mt-auto flex items-end justify-between gap-2 pt-2">
        {dark && l.activityCount > 0 ? (
          <span className="flex flex-wrap items-end gap-1" aria-label={t("courseMap.activities", { count: l.activityCount })}>
            {Array.from({ length: Math.min(l.activityCount, 10) }, (_, i) => (
              <span key={i} className={cn("rounded-full", i === 0 ? "h-3 w-3 bg-accent" : "h-2 w-2 bg-bg/50")} />
            ))}
          </span>
        ) : (
          <span className="flex items-center gap-1.5 text-xs">
            {l.activityTypes.map((ty) => {
              const I = TYPE_ICON[ty] ?? Sparkles;
              return <I key={ty} className="h-3.5 w-3.5 opacity-70" aria-hidden />;
            })}
            {l.activityCount > 0 && <span className={dark ? "text-bg/70" : "text-muted"}>{t("courseMap.activities", { count: l.activityCount })}</span>}
          </span>
        )}
        {l.done && l.score !== null && <span className="font-display text-2xl font-bold leading-none text-good">{pct(l.score)}</span>}
        {dark && <span className="rounded-full bg-accent px-3 py-1 text-xs font-bold text-accent-ink">{t("courseMap.go")}</span>}
      </div>
      {controls}
    </div>
  );
  if (editing) return <div className="relative h-full">{body}</div>; // no link: the reorder buttons can't sit inside one
  return l.locked
    ? <div aria-disabled title={t("learn.locked")} className="h-full">{body}</div>
    : <Link to={l.href} aria-label={l.title} className="block h-full rounded-3xl">{body}</Link>;
}

/** The chosen section's lessons as cards joined by lines, snaking across the screen (one column on phones). */
export function LessonMap({ lessons, editing, onMove, onHide }: {
  lessons: MapLesson[]; editing: boolean; onMove?: (index: number, dir: -1 | 1) => void; onHide?: (l: MapLesson) => void;
}) {
  const { t } = useTranslation();
  const [ref, measured] = useWidth<HTMLDivElement>();
  const m = layoutMap(lessons.length, measured || 320);
  return (
    <div ref={ref} className="relative w-full" style={{ height: m.height }}>
      <svg className="pointer-events-none absolute inset-0 overflow-visible" width="100%" height={m.height} aria-hidden>
        {m.links.map((d, i) => {
          const walked = lessons[i].done;
          return <path key={i} d={d} fill="none" strokeLinecap="round" strokeWidth={2}
            stroke={walked ? "var(--muted)" : "var(--border)"} strokeDasharray={walked ? undefined : "5 6"} />;
        })}
      </svg>
      <ol>
        {lessons.map((l, i) => (
          <motion.li key={l.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i, 8) * 0.04 }}
            className="absolute" style={{ left: m.cards[i].x, top: m.cards[i].y, width: m.cardW, height: m.cardH }}>
            <LessonCard l={l} editing={editing} controls={editing && (
              <span className="absolute right-3 top-3 z-10 flex gap-1.5 rounded-full bg-surface px-2 py-1 text-ink shadow">
                <button type="button" aria-label={t("lj.lessons.up", { title: l.title })} disabled={i === 0} className="hover:text-accent disabled:opacity-30" onClick={(e) => { e.preventDefault(); onMove?.(i, -1); }}><ArrowUp className="h-4 w-4" /></button>
                <button type="button" aria-label={t("lj.lessons.down", { title: l.title })} disabled={i === lessons.length - 1} className="hover:text-accent disabled:opacity-30" onClick={(e) => { e.preventDefault(); onMove?.(i, 1); }}><ArrowDown className="h-4 w-4" /></button>
                <button type="button" aria-label={t("courseEdit.hideItem", { title: l.title })} title={t("courseEdit.hide")} className="hover:text-bad" onClick={(e) => { e.preventDefault(); onHide?.(l); }}><EyeOff className="h-4 w-4" /></button>
              </span>
            )} />
          </motion.li>
        ))}
      </ol>
    </div>
  );
}

/** Every lesson in the course on one strip, grouped by section; the chosen section is highlighted. */
export function Timeline({ sections, selected, onSelect }: { sections: MapSection[]; selected: number; onSelect: (id: number) => void }) {
  const { t } = useTranslation();
  const at = sections.findIndex((s) => s.id === selected);
  return (
    <div className="flex items-center gap-3">
      <div className="flex shrink-0 gap-1.5">
        <button type="button" aria-label={t("courseMap.prev")} disabled={at <= 0} onClick={() => onSelect(sections[at - 1].id)}
          className="flex h-10 w-10 items-center justify-center rounded-full bg-ink text-bg disabled:opacity-30"><ChevronLeft className="h-5 w-5" /></button>
        <button type="button" aria-label={t("courseMap.next")} disabled={at >= sections.length - 1} onClick={() => onSelect(sections[at + 1].id)}
          className="flex h-10 w-10 items-center justify-center rounded-full bg-ink text-bg disabled:opacity-30"><ChevronRight className="h-5 w-5" /></button>
      </div>
      <div className="min-w-0 flex-1 overflow-x-auto rounded-full bg-surface px-3 py-2 shadow-sm" role="group" aria-label={t("courseMap.timeline")}>
        <div className="flex w-max min-w-full items-start gap-1">
          {sections.map((s) => {
            const on = s.id === selected;
            return (
              <button key={s.id} type="button" aria-pressed={on} onClick={() => onSelect(s.id)} aria-label={t("courseMap.sectionN", { n: s.n }) + ": " + s.title}
                className={cn("flex flex-1 flex-col items-center gap-1 rounded-full px-2 py-1 transition", on ? "bg-accent/25" : "hover:bg-surface-2")}>
                <span className="flex items-center gap-1.5">
                  {s.lessons.map((l) => (
                    <span key={l.id} className={cn("rounded-full",
                      l.current ? "h-3.5 w-3.5 bg-accent ring-4 ring-accent/25" : l.done ? "h-2.5 w-2.5 bg-ink/60" : "h-2 w-2 bg-line")} />
                  ))}
                </span>
                <span className={cn("text-[10px] font-semibold", on ? "text-ink" : "text-muted")}>{s.n}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-3xl bg-surface p-5 shadow-sm">
      <h3 className="mb-3 font-display text-lg font-bold">{title}</h3>
      {children}
    </section>
  );
}

/** Up next, scores so far and skills: the three cards under the map. */
export function MapPanels({ next, lessons, skills }: { next?: MapLesson; lessons: MapLesson[]; skills: string[] }) {
  const { t } = useTranslation();
  const scored = lessons.filter((l) => l.done && l.score !== null);
  const avg = scored.length ? scored.reduce((a, l) => a + (l.score ?? 0), 0) / scored.length : null;
  const bySkill = skills.map((sk) => {
    const has = lessons.filter((l) => l.skills.includes(sk));
    return { sk, total: has.length, done: has.filter((l) => l.done).length };
  });
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <Panel title={t("courseMap.upNext")}>
        {next ? (
          <div className="space-y-3">
            <div className="rounded-2xl bg-accent/15 p-3">
              <p className="text-[11px] font-medium text-muted">{t("courseMap.lessonN", { n: next.n })}{next.minutes ? <> · {t("courseMap.minutes", { n: next.minutes })}</> : null}</p>
              <p className="font-semibold leading-snug">{next.title}</p>
              {next.objective && <p className="mt-1 line-clamp-2 text-xs text-muted">{next.objective}</p>}
            </div>
            <Link to={next.href} className="inline-flex items-center gap-1.5 rounded-full bg-ink px-4 py-2 text-sm font-semibold text-bg hover:opacity-90">
              <Play className="h-4 w-4" /> {t("learn.continue")}
            </Link>
          </div>
        ) : <p className="text-sm text-muted">{t("courseMap.allDone")}</p>}
      </Panel>
      <Panel title={t("courseMap.scores")}>
        {avg === null ? <p className="text-sm text-muted">{t("courseMap.noScores")}</p> : (
          <div className="flex items-end justify-between gap-4">
            <p><span className="font-display text-4xl font-bold">{pct(avg)}</span> <span className="text-xs text-muted">{t("courseMap.avg")}</span></p>
            <div className="flex h-14 items-end gap-1" aria-hidden>
              {scored.slice(-10).map((l, i, a) => (
                <span key={l.id} title={`${l.title}: ${pct(l.score ?? 0)}`} className={cn("w-2.5 rounded-full", i === a.length - 1 ? "bg-accent" : "bg-line")}
                  style={{ height: `${Math.max(12, (l.score ?? 0) * 100)}%` }} />
              ))}
            </div>
          </div>
        )}
      </Panel>
      <Panel title={t("courseMap.skills")}>
        {bySkill.length === 0 ? <p className="text-sm text-muted">{t("courseMap.noSkills")}</p> : (
          <ul className="space-y-2">
            {bySkill.slice(0, 6).map(({ sk, total, done }) => (
              <li key={sk} className="flex items-center justify-between gap-3 text-sm">
                <span className="truncate">{sk}</span>
                {total > 0 && (
                  <span className="flex shrink-0 items-center gap-1" aria-label={t("learn.progress", { done, count: total })}>
                    {Array.from({ length: Math.min(total, 6) }, (_, i) => (
                      <span key={i} className={cn("h-2.5 w-2.5 rounded-full", i < Math.round((done / total) * Math.min(total, 6)) ? "bg-accent" : "bg-line")} />
                    ))}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
