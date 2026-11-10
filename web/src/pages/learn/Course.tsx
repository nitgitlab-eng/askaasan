import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CloudDownload, Map as MapIcon, PencilRuler, Play, RotateCcw, Route } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { confirmDialog } from "@/lib/dialog";
import { Kolam } from "@/components/Kolam";
import { PageError } from "@/components/PageState";
import { PathPanel } from "@/components/adaptive/PathPanel";
import { CheckpointCard } from "@/components/course/CheckpointCard";
import { EditCourse } from "@/components/course/EditCourse";
import { LessonMap, MapPanels, SectionDetail, SectionHotspots, SectionRail, Timeline } from "@/components/course/CourseMap";
import type { MapLesson, MapSection } from "@/components/course/CourseMap";
import { QuestPath } from "@/components/course/QuestPath";
import { journey, move } from "@/lib/journey";
import { learner } from "@/lib/learner";
import { Button } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { badId } from "@/lib/ids";
import { usePath } from "@/lib/adaptive";
import { useCourse } from "@/lib/learn";
import { saveCourseOffline, savedCourses, useOnline } from "@/lib/offline";
import { useMe, useUpdatePreferences } from "@/lib/useMe";
import { Kili } from "@/mascot/Kili";

/**
 * A course in one of two views, the learner's choice (saved in preferences): the map (sections around your companion,
 * lessons as linked cards) or the classic quest path. The timeline and the up-next / scores / skills panels show in both.
 */
type CourseView = "map" | "path";

export default function CoursePage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const { data: c, isLoading, error, refetch } = useCourse(Number(id));
  // Every learner gets their own path once the course is ready (the first visit creates it on the server).
  const { data: path } = usePath(Number(id), c?.status === "ready");
  const pending = new Map<number, string>(); // lesson → its next step kind on my path
  for (const it of path?.items ?? []) if (it.status === "pending" && it.subsection && !pending.has(it.subsection.id)) pending.set(it.subsection.id, it.kind);
  const currentStep = (path?.items ?? []).find((i) => i.current)?.subsection?.id;
  const online = useOnline();
  const [saving, setSaving] = useState<{ done: number; total: number } | null>(null);
  const [saved, setSaved] = useState(() => savedCourses.has(Number(id)));
  const [saveErr, setSaveErr] = useState("");
  const [editing, setEditing] = useState(false);
  const [reorderErr, setReorderErr] = useState("");
  const [picked, setPicked] = useState<number | null>(null); // the section on the map; defaults to where you are
  const updatePrefs = useUpdatePreferences();
  const [localView, setLocalView] = useState<CourseView | null>(null); // offline: the switch still works, unsaved
  const view: CourseView = localView ?? me?.preferences.learning.course_view ?? "map";
  const switchView = (v: CourseView) => {
    setLocalView(v);
    if (online) updatePrefs.mutate({ learning: { course_view: v } });
  };
  const { data: heard } = useQuery({ queryKey: ["course-listened", Number(id)], queryFn: () => journey.courseListened(Number(id)), enabled: !badId(Number(id)) && online });
  const listened = new Set(heard?.lessons ?? []);
  const reorder = async (courseId: number, sectionId: number, ids: number[]) => {
    setReorderErr("");
    try { await journey.reorderLessons(courseId, sectionId, ids); } catch { setReorderErr(t("lj.lessons.error")); }
    void qc.invalidateQueries({ queryKey: ["course", courseId] });
    void qc.invalidateQueries({ queryKey: ["course-edit", courseId] });
  };

  if (badId(Number(id))) return <PageError notFound />;
  if (error && !c) return <PageError error={error} onRetry={() => void refetch()} />;
  if (isLoading || !c) return <p className="p-8 text-muted">{t("common.loading")}</p>;

  if (c.status === "generating") {
    return (
      <div className="flex flex-col items-center gap-4 px-4 py-20 text-center">
        <Kili mood="thinking" size={160} />
        <h1 className="font-display text-2xl font-bold">{t("learn.building")}</h1>
        <p className="max-w-md text-muted">{c.goal}</p>
      </div>
    );
  }
  if (c.status === "failed") {
    return (
      <div className="flex flex-col items-center gap-4 px-4 py-20 text-center">
        <Kili mood="confused" size={140} />
        <p>{t("learn.failed")}</p>
        <Button onClick={async () => { await api(`/api/learn/curriculums/${c.id}/retry/`, { method: "POST" }); void qc.invalidateQueries({ queryKey: ["course", c.id] }); }}>
          <RotateCcw className="h-4 w-4" /> {t("common.retry")}
        </Button>
      </div>
    );
  }

  // One view model for every part of the map: what's done, open, locked and next, in course order.
  let n = 0;
  const sections: MapSection[] = c.sections.map((s, si) => {
    const lessons = s.subsections.map((b): MapLesson => {
      const done = b.state === "completed";
      const step = pending.get(b.id);
      // With a path, what's open follows the path: done lessons, the current step and quick checks (any time).
      const pathLocked = path ? !done && b.id !== currentStep && step !== "skip_check" : b.locked;
      const locked = pathLocked && !(saved && !online && b.lesson_status === "ready"); // offline: saved lessons stay open
      return {
        id: b.id, n: ++n, title: b.title, objective: b.objective, done, locked, step, score: b.score,
        current: !done && !locked && (path ? b.id === currentStep : true), // narrowed to the first one below
        minutes: b.minutes ?? null, activityCount: b.activity_count ?? 0, activityTypes: b.activity_types ?? [], skills: b.skills ?? [],
        listened: listened.has(b.id), href: `/learn/${c.id}/lesson/${b.id}${step === "skip_check" ? "?fast=1" : ""}`,
      };
    });
    const doneCount = lessons.filter((l) => l.done).length;
    return { id: s.id, n: si + 1, title: s.title, summary: s.summary, lessons, done: doneCount, complete: lessons.length > 0 && doneCount === lessons.length };
  });
  const allLessons = sections.flatMap((s) => s.lessons);
  const nextLesson = allLessons.find((l) => l.current);
  for (const l of allLessons) l.current = l === nextLesson;
  const shown = sections.find((s) => s.id === picked) ?? sections.find((s) => s.lessons.some((l) => l.current)) ?? sections[0];
  const allDone = c.progress.total > 0 && c.progress.done >= c.progress.total;
  const hide = async (kind: "section" | "lesson", itemId: number) => {
    await learner.setHidden(c.id, kind, itemId, true).catch(() => null);
    void qc.invalidateQueries({ queryKey: ["course", c.id] });
    void qc.invalidateQueries({ queryKey: ["course-edit", c.id] });
  };
  const pill = "flex items-center gap-1.5 rounded-full border border-line bg-surface px-3.5 py-2 text-sm font-semibold transition disabled:opacity-60";
  const detail = shown && <SectionDetail s={shown} courseId={c.id} onHide={editing ? () => void hide("section", shown.id) : undefined} />;

  return (
    <div className="mx-auto max-w-7xl space-y-5 px-4 py-6 lg:py-8">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-4">
          <Kolam filled={c.progress.done} slots={c.progress.total} size={72} label={t("learn.kolam", { done: c.progress.done, count: c.progress.total })} />
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">{t(`learn.levels.${c.level}`)} · {t("learn.progress", { done: c.progress.done, count: c.progress.total })}</p>
            <h1 className="font-display text-2xl font-extrabold leading-tight sm:text-3xl">{c.title}</h1>
            {c.description && <p className="line-clamp-2 max-w-2xl text-sm text-muted">{c.description}</p>}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {nextLesson && (
            <Link to={nextLesson.href} className="flex items-center gap-1.5 rounded-full bg-ink px-4 py-2 text-sm font-semibold text-bg hover:opacity-90">
              <Play className="h-4 w-4" /> {t("learn.continue")}
            </Link>
          )}
          {saved ? <span className={cn(pill, "text-good")}><CloudDownload className="h-4 w-4" /> {t("offline.saved")}</span> : online && (
            <button className={cn(pill, "hover:border-accent")} disabled={!!saving} onClick={async () => {
              setSaveErr("");
              setSaving({ done: 0, total: 0 });
              try {
                await import("./Lesson"); // the lesson screen's code must be cached too, or saved lessons can't open offline
                await saveCourseOffline(c, me?.preferences.learning.lesson_language ?? "", (done, total) => setSaving({ done, total }));
                setSaved(true);
              } catch {
                setSaveErr(t("offline.saveFailed"));
              } finally {
                setSaving(null);
              }
            }}><CloudDownload className="h-4 w-4" /> {saving ? t("offline.saving", saving) : t("offline.save")}</button>
          )}
          {saved && online && <button className="text-xs text-muted hover:text-bad" onClick={() => { savedCourses.remove(c.id); setSaved(false); }}>{t("offline.forget")}</button>}
          {c.kind === "personal" && c.is_owner && (
            <button className={cn(pill, editing ? "border-accent text-accent" : "hover:border-accent")} aria-pressed={editing} onClick={() => setEditing((v) => !v)}>
              <PencilRuler className="h-4 w-4" />{t(editing ? "courseEdit.done" : "courseEdit.open")}
            </button>
          )}
          {c.progress.done > 0 && (
            <button className={cn(pill, "text-muted hover:border-bad hover:text-bad")} onClick={async () => {
              if (!(await confirmDialog(t("studio.resetConfirm"), { danger: true }))) return;
              await api(`/api/learn/curriculums/${c.id}/reset/`, { method: "POST" });
              void qc.invalidateQueries({ queryKey: ["course", c.id] });
              void qc.invalidateQueries({ queryKey: ["courses"] });
            }}><RotateCcw className="h-4 w-4" />{t("studio.reset")}</button>
          )}
        </div>
        {saveErr && <p role="alert" className="w-full text-sm text-bad">{saveErr}</p>}
      </header>

      {editing && <EditCourse courseId={c.id} onChanged={() => void qc.invalidateQueries({ queryKey: ["course", c.id] })} />}
      {reorderErr && <p role="alert" className="text-sm text-bad">{reorderErr}</p>}
      {c.status === "ready" && <CheckpointCard courseId={c.id} progress={c.progress} />}

      {shown && (
        <div className="space-y-5 rounded-[2rem] bg-surface-2/70 p-3 sm:p-5">
          <div className="flex justify-end">
            <div role="radiogroup" aria-label={t("courseMap.view")} className="flex gap-1 rounded-full bg-surface p-1 shadow-sm">
              {([["map", MapIcon], ["path", Route]] as const).map(([v, Icon]) => (
                <button key={v} type="button" role="radio" aria-checked={view === v} onClick={() => switchView(v)}
                  className={cn("flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm font-semibold transition", view === v ? "bg-ink text-bg" : "text-muted hover:text-ink")}>
                  <Icon className="h-4 w-4" aria-hidden /> {t(`courseMap.views.${v}`)}
                </button>
              ))}
            </div>
          </div>
          {view === "map" ? (
            <div className="grid gap-5 lg:grid-cols-[240px_minmax(0,1fr)] xl:grid-cols-[280px_240px_minmax(0,1fr)]">
              <div className="hidden rounded-3xl bg-surface/60 py-2 xl:block">
                <SectionHotspots sections={sections} selected={shown.id} onSelect={setPicked} allDone={allDone} />
              </div>
              <SectionRail sections={sections} selected={shown.id} onSelect={setPicked} detail={detail} />
              <div className="min-w-0 space-y-4">
                <div className="lg:hidden">{detail}</div>
                <LessonMap lessons={shown.lessons} editing={editing}
                  onMove={(i, dir) => void reorder(c.id, shown.id, move(shown.lessons.map((x) => x.id), i, dir))}
                  onHide={(l) => void hide("lesson", l.id)} />
              </div>
            </div>
          ) : (
            <QuestPath sections={sections} courseId={c.id} editing={editing}
              onMove={(s, i, dir) => void reorder(c.id, s.id, move(s.lessons.map((x) => x.id), i, dir))}
              onHide={(kind, itemId) => void hide(kind, itemId)} />
          )}
          <Timeline sections={sections} selected={shown.id} onSelect={(sid) => {
            setPicked(sid);
            // On the path every section is on the page, so the timeline jumps to it instead.
            if (view === "path") document.getElementById(`section-${sid}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
          }} />
          <MapPanels next={nextLesson} lessons={allLessons} skills={c.skills} />
        </div>
      )}

      {c.status === "ready" && <PathPanel courseId={c.id} />}
    </div>
  );
}
