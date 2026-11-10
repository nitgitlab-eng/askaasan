import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, ArrowDown, ArrowLeft, ArrowUp, Copy, Eye, Globe, ImagePlus, Link2, Loader2, Lock, Pencil, Plus, Presentation, RefreshCw, Sparkles, Star, Trash2, Wand2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { confirmDialog, promptDialog } from "@/lib/dialog";
import { Md } from "@/components/Md";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ActivityCard } from "@/activities/ActivityCard";
import { typeLabelKey } from "@/activities/typeLabel";
import { PageError } from "@/components/PageState";
import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { badId } from "@/lib/ids";
import { media } from "@/lib/media";
import { lab, shareUrl, type LabCourse, type LabLesson } from "@/lib/lab";
import { Kili } from "@/mascot/Kili";

import { ActivityEditor } from "./ActivityEditor";
import { emptyArtifactCheck } from "./artifactKit";
import { ArtifactCheckForm } from "./ArtifactCheckForm";
import { emptyHotspot, emptyVideo } from "./creatorKit";
import { HotspotForm, VideoForm } from "./CreatorForms";
import { MediaPicker } from "./MediaPicker";
import { StatusBadge } from "./LabHome";
import { Grounding } from "./studio/Grounding";
import { KiliChat } from "./studio/KiliChat";
import { LectureTool } from "./studio/LectureTool";
import { LessonPicker } from "./studio/LessonPicker";
import { StudioToolbar } from "./studio/Toolbar";
import { downloadFile } from "@/lib/download";
import { studio } from "@/lib/studio";

const TYPES = ["quiz", "fill_blank", "sequencing", "categorization", "matching", "open_input", "diagram", "slides", "concept_map", "decision_tree", "task", "viz", "code", "map", "browser_task", "roleplay", "video", "hotspot", "artifact_check"];
const HANDMADE = new Set(["video", "hotspot", "artifact_check"]);

function PublishPanel({ c, onChange }: { c: LabCourse; onChange: (c: LabCourse) => void }) {
  const { t } = useTranslation();
  const [error, setError] = useState<string[] | null>(null);
  const [copied, setCopied] = useState(false);
  const [rotated, setRotated] = useState(false);
  async function rotate() {
    if (!(await confirmDialog(t("lab.resetLinkConfirm"), { danger: true, ok: t("lab.resetLink") }))) return;
    const { share_token } = await lab.rotateShare(c.id);
    onChange({ ...c, share_token });
    setCopied(false);
    setRotated(true);
  }
  async function go(v: "private" | "link" | "catalog") {
    setError(null);
    try {
      onChange(await lab.publish(c.id, v));
    } catch (e) {
      if (e instanceof ApiError && e.data?.code === "lessons_not_ready") setError((e.data.lessons as string[]) ?? []);
    }
  }
  return (
    <Card className="space-y-3">
      <div className="flex items-center justify-between"><h3 className="font-display text-lg font-bold">{t("lab.publish")}</h3><StatusBadge c={c} /></div>
      <div className="grid gap-2 sm:grid-cols-3">
        {([["private", Lock], ["link", Link2], ["catalog", Globe]] as const).map(([v, Icon]) => (
          <button key={v} onClick={() => go(v)} aria-pressed={(c.published_at ? c.visibility : "private") === v}
            className={cn("rounded-xl border-2 p-3 text-left", (c.published_at ? c.visibility : "private") === v ? "border-accent bg-accent/10" : "border-line hover:border-accent")}>
            <Icon className="mb-1 h-5 w-5 text-accent" />
            <p className="font-semibold">{t(`lab.vis.${v}`)}</p>
            <p className="text-xs text-muted">{t(`lab.visHint.${v}`)}</p>
          </button>
        ))}
      </div>
      {c.catalog_status === "rejected" && <p className="rounded-xl bg-bad/10 p-2 text-sm text-bad">{t("lab.rejected")}: {c.catalog_note}</p>}
      {error && <p role="alert" className="rounded-xl bg-bad/10 p-2 text-sm text-bad">{t("lab.notReady")} {error.join(", ")}</p>}
      {c.published_at && (
        <div className="flex flex-wrap items-center gap-2">
          <code className="truncate rounded-lg bg-surface-2 px-3 py-2 text-xs">{shareUrl(c.share_token)}</code>
          <Button variant="outline" className="py-1.5 text-sm" onClick={() => { void navigator.clipboard.writeText(shareUrl(c.share_token)); setCopied(true); }}>
            <Copy className="h-4 w-4" /> {copied ? t("game.copied") : t("game.copyLink")}
          </Button>
          <a href={`/s/${c.share_token}`} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-sm font-semibold text-accent"><Eye className="h-4 w-4" /> {t("lab.viewAsGuest")}</a>
          <Link to={`/guests?course=${c.id}`} className="flex items-center gap-1 text-sm font-semibold text-accent"><Link2 className="h-4 w-4" /> {t("guest.entryLab")}</Link>
          <Button variant="ghost" className="py-1.5 text-sm" onClick={() => void rotate()}><RefreshCw className="h-4 w-4" /> {t("lab.resetLink")}</Button>
          <p className="w-full text-xs text-muted">{rotated ? t("lab.resetLinkDone") : t("lab.resetLinkHint")}</p>
        </div>
      )}
    </Card>
  );
}

function LessonPanel({ id, courseId, onChanged }: { id: number; courseId: number; onChanged: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: l } = useQuery({
    queryKey: ["lab-lesson", id],
    queryFn: () => lab.lesson(id),
    refetchInterval: (q) => (q.state.data?.lesson_status === "generating" ? 2500 : false),
  });
  const [editText, setEditText] = useState<string | null>(null);
  const [points, setPoints] = useState<string | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [preview, setPreview] = useState<number | null>(null);
  const [newType, setNewType] = useState("quiz");
  const [instr, setInstr] = useState("");
  const [adding, setAdding] = useState(false);
  const [addErr, setAddErr] = useState("");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [draft, setDraft] = useState<Record<string, any> | null>(null);
  const [picking, setPicking] = useState(false);
  const [illustrating, setIllustrating] = useState(false);
  const refresh = (x?: Partial<LabLesson>) => {
    if (x) qc.setQueryData(["lab-lesson", id], (old: LabLesson | undefined) => (old ? { ...old, ...x } : old));
    void qc.invalidateQueries({ queryKey: ["lab-lesson", id] });
    onChanged();
  };
  if (!l) return <p className="text-muted">{t("common.loading")}</p>;

  async function generate() {
    await lab.generate(id);
    refresh({ lesson_status: "generating" });
  }
  async function addImageToText(url: string, alt: string) {
    const md = `![${alt.replace(/[[\]]/g, "")}](${url})`;
    if (editText !== null) setEditText(`${editText}\n\n${md}\n`);
    else refresh(await lab.patchLesson(id, { explanation_md: `${md}\n\n${l!.explanation_md}` }));
  }
  async function illustrate() {
    setIllustrating(true);
    setAddErr("");
    try {
      const a = await media.generate(`An illustration for a lesson titled "${l!.title}". The idea: ${l!.objective || l!.title}`, l!.title);
      await addImageToText(a.url, l!.title);
    } catch (e) {
      setAddErr(t(`lab.media.err.${e instanceof ApiError ? e.data?.code : ""}`, { defaultValue: t("mentor.errors.generic") }));
    } finally {
      setIllustrating(false);
    }
  }
  async function saveDraft() {
    if (!draft) return;
    setAdding(true);
    setAddErr("");
    try {
      await lab.addActivity(id, { type: draft.type, source: draft });
      setDraft(null);
      refresh();
    } catch (e) {
      setAddErr(e instanceof ApiError ? String(e.data?.detail ?? e.data?.code) : t("mentor.errors.generic"));
    } finally {
      setAdding(false);
    }
  }
  async function add() {
    if (HANDMADE.has(newType)) {
      setDraft(newType === "video" ? emptyVideo() : newType === "artifact_check" ? emptyArtifactCheck() : emptyHotspot());
      return;
    }
    setAdding(true);
    setAddErr("");
    try {
      await lab.addActivity(id, { type: newType, instructions: instr });
      setInstr("");
      refresh();
    } catch (e) {
      setAddErr(e instanceof ApiError ? String(e.data?.detail ?? e.data?.code) : t("mentor.errors.generic"));
    } finally {
      setAdding(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card className="space-y-3">
        <input defaultValue={l.title} key={`t${l.id}${l.title}`} onBlur={(e) => e.target.value !== l.title && void lab.patchLesson(id, { title: e.target.value }).then(() => refresh())}
          className="w-full bg-transparent font-display text-2xl font-extrabold outline-none" aria-label={t("lab.f.title")} />
        <input defaultValue={l.objective} key={`o${l.id}${l.objective}`} placeholder={t("lab.objective")} onBlur={(e) => e.target.value !== l.objective && void lab.patchLesson(id, { objective: e.target.value }).then(() => refresh())}
          className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent" aria-label={t("lab.objective")} />
        {l.lesson_status === "generating" ? (
          <div className="flex items-center gap-3 py-6"><Kili mood="thinking" size={70} /><p className="text-muted">{t("lab.generating")}</p></div>
        ) : (
          <div className="flex flex-wrap gap-2">
            <Button onClick={generate} variant={l.lesson_status === "ready" ? "outline" : "primary"}>
              <Wand2 className="h-4 w-4" /> {l.lesson_status === "ready" ? t("lab.regenerate") : t("lab.generate")}
            </Button>
            {l.lesson_status === "failed" && <span className="self-center text-sm text-bad">{t("lesson.failed")} ({l.error})</span>}
            {l.lesson_status === "ready" && (
              <Button variant="ghost" onClick={() => void downloadFile(studio.urls.pptx(courseId, id), "lesson.pptx")}><Presentation className="h-4 w-4" /> {t("studio.lessonSlides")}</Button>
            )}
          </div>
        )}
      </Card>
      {l.lesson_status !== "generating" && (
        <>
          <Card className="space-y-2">
            <div className="flex items-center justify-between"><h3 className="font-display text-lg font-bold">{t("lab.explanation")}</h3>
              <div className="flex flex-wrap gap-1">
                <Button variant="ghost" className="py-1 text-sm" onClick={() => setPicking(!picking)}><ImagePlus className="h-4 w-4" /> {t("lab.media.add")}</Button>
                <Button variant="ghost" className="py-1 text-sm" loading={illustrating} onClick={illustrate}><Sparkles className="h-4 w-4" /> {t("lab.media.illustrate")}</Button>
                {editText === null && <Button variant="ghost" className="py-1 text-sm" onClick={() => setEditText(l.explanation_md)}><Pencil className="h-4 w-4" /> {t("lab.edit")}</Button>}
              </div>
            </div>
            {picking && <MediaPicker suggestion={`An illustration for a lesson titled "${l.title}"`} onClose={() => setPicking(false)} onPick={(a) => { setPicking(false); void addImageToText(a.url, a.alt || l.title); }} />}
            {editText === null ? (
              l.explanation_md ? <div className="prose-chat"><Md>{l.explanation_md}</Md></div> : <p className="text-sm text-muted">{t("lab.noText")}</p>
            ) : (
              <>
                <textarea value={editText} onChange={(e) => setEditText(e.target.value)} rows={12} className="w-full rounded-xl border-2 border-line bg-surface p-3 font-mono text-sm outline-none focus:border-accent" aria-label={t("lab.explanation")} />
                <div className="flex gap-2">
                  <Button onClick={async () => { refresh(await lab.patchLesson(id, { explanation_md: editText })); setEditText(null); }}>{t("common.save")}</Button>
                  <Button variant="ghost" onClick={() => setEditText(null)}>{t("lab.cancel")}</Button>
                </div>
              </>
            )}
            <h4 className="pt-2 font-semibold">{t("lesson.keyPoints")}</h4>
            {points === null ? (
              <button className="w-full text-left" onClick={() => setPoints(l.key_points.join("\n"))}>
                <ul className="list-disc pl-5 text-sm">{l.key_points.length ? l.key_points.map((k) => <li key={k}>{k}</li>) : <li className="text-muted">{t("lab.edit")}</li>}</ul>
              </button>
            ) : (
              <div className="space-y-2">
                <textarea value={points} onChange={(e) => setPoints(e.target.value)} rows={4} className="w-full rounded-xl border-2 border-line bg-surface p-2 text-sm" aria-label={t("lesson.keyPoints")} />
                <Button onClick={async () => { refresh(await lab.patchLesson(id, { key_points: points.split("\n").map((x) => x.trim()).filter(Boolean).slice(0, 8) })); setPoints(null); }}>{t("common.save")}</Button>
              </div>
            )}
          </Card>

          {l.feedback && (
            <Card className="space-y-1 text-sm">
              <p className="font-semibold">⭐ {t("lab.learnerRating", { avg: l.feedback.avg, count: l.feedback.n })} · {t("lab.tooHard", { n: l.feedback.hard })} · {t("lab.tooEasy", { n: l.feedback.easy })}</p>
              {l.feedback.comments.map((c, i) => <p key={i} className="rounded-lg bg-surface-2 px-2 py-1 text-muted">“{c}”</p>)}
            </Card>
          )}
          <h3 className="font-display text-lg font-bold">{t("lesson.practice")} ({l.activities.length})</h3>
          {l.activities.map((a, i) => (
            <Card key={a.id} className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-surface-2 px-2.5 py-0.5 text-xs font-semibold">{t(typeLabelKey(a.type))}</span>
                <p className="flex-1 font-semibold">{a.title}</p>
                <Button variant="ghost" className="py-1 text-sm" onClick={() => setPreview(preview === a.id ? null : a.id)}><Eye className="h-4 w-4" /> {t("lab.preview")}</Button>
                <Button variant="ghost" className="py-1 text-sm" onClick={() => setEditing(editing === a.id ? null : a.id)}><Pencil className="h-4 w-4" /> {t("lab.edit")}</Button>
              </div>
              {editing === a.id && <ActivityEditor a={a} lessonId={id} onSaved={() => { setEditing(null); refresh(); }} onDeleted={() => { setEditing(null); refresh(); }} />}
              {preview === a.id && <ActivityCard key={`p${a.id}${a.title}`} activity={{ ...a, type: a.type as never, attempt: null }} index={i} />}
            </Card>
          ))}
          <LectureTool lessonId={id} onBuilt={() => refresh()} />
          <Card className="space-y-2">
            <h4 className="font-semibold">{t("lab.addActivity")}</h4>
            <div className="flex flex-wrap gap-2">
              <select value={newType} onChange={(e) => setNewType(e.target.value)} className="rounded-xl border-2 border-line bg-surface px-3 py-2" aria-label={t("lab.type")}>
                {TYPES.map((x) => <option key={x} value={x}>{t(typeLabelKey(x))}</option>)}
              </select>
              <input value={instr} onChange={(e) => setInstr(e.target.value)} maxLength={500} placeholder={t("lab.instructions")} className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2" aria-label={t("lab.instructions")} />
              <Button onClick={add} loading={adding && !draft}>{HANDMADE.has(newType) ? <><Pencil className="h-4 w-4" /> {t("lab.addByHand")}</> : <><Sparkles className="h-4 w-4" /> {t("lab.addAi")}</>}</Button>
            </div>
            {draft && (
              <div className="space-y-3 rounded-2xl border-2 border-dashed border-accent/40 bg-surface-2/50 p-4">
                <input className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2" placeholder={t("lab.f.title")} value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
                <input className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2" placeholder={t("lab.f.prompt")} value={draft.prompt} onChange={(e) => setDraft({ ...draft, prompt: e.target.value })} />
                {draft.type === "video" ? <VideoForm src={draft} setSrc={setDraft} lessonId={id} /> : draft.type === "artifact_check" ? <ArtifactCheckForm src={draft} setSrc={setDraft} /> : <HotspotForm src={draft} setSrc={setDraft} />}
                <div className="flex gap-2"><Button onClick={saveDraft} loading={adding}>{t("common.save")}</Button><Button variant="ghost" onClick={() => setDraft(null)}>{t("lab.cancel")}</Button></div>
              </div>
            )}
            {addErr && <p role="alert" className="text-sm text-bad">{addErr}</p>}
          </Card>
        </>
      )}
    </div>
  );
}

export default function CourseEditor() {
  const { t } = useTranslation();
  const { id } = useParams();
  const cid = Number(id);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data: c, error, refetch } = useQuery({
    queryKey: ["lab-course", cid],
    queryFn: () => lab.course(cid),
    enabled: !badId(cid),
    refetchInterval: (q) => (q.state.data?.status === "generating" ? 2000 : false),
  });
  const [selected, setSelected] = useState<number | null>(null);
  const [panel, setPanel] = useState("");
  const [picker, setPicker] = useState<number | null>(null);
  const set = (x: LabCourse) => qc.setQueryData(["lab-course", cid], x);
  const reload = () => void qc.invalidateQueries({ queryKey: ["lab-course", cid] });

  if (badId(cid)) return <PageError notFound />;
  if (error && !c) return <PageError error={error} onRetry={() => void refetch()} />;
  if (!c) return <p className="p-8 text-muted">{t("common.loading")}</p>;
  if (c.status === "generating") {
    return <div className="flex flex-col items-center gap-3 py-20"><Kili mood="thinking" size={140} /><p className="font-display text-xl font-bold">{t("lab.outlining")}</p></div>;
  }
  const sections = c.sections ?? [];
  const moveSection = (i: number, d: number) => {
    const ids = sections.map((s) => s.id);
    [ids[i], ids[i + d]] = [ids[i + d], ids[i]];
    void lab.reorder(cid, { sections: ids }).then(set);
  };
  const moveLesson = (sid: number, i: number, d: number) => {
    const ids = sections.find((s) => s.id === sid)!.subsections.map((b) => b.id);
    [ids[i], ids[i + d]] = [ids[i + d], ids[i]];
    void lab.reorder(cid, { subsections: { [sid]: ids } }).then(set);
  };

  return (
    <div className="mx-auto max-w-7xl space-y-4 px-4 py-6">
      <Link to="/lab" className="inline-flex items-center gap-1 text-sm font-medium text-muted hover:text-accent"><ArrowLeft className="h-4 w-4" /> {t("lab.title")}</Link>
      <Card className="flex flex-wrap items-center gap-3">
        <input defaultValue={c.cover_emoji} maxLength={4} onBlur={(e) => e.target.value && void lab.patchCourse(cid, { cover_emoji: e.target.value }).then(set)} className="w-14 rounded-xl border-2 border-line bg-surface text-center text-3xl" aria-label={t("lab.emoji")} />
        <div className="min-w-0 flex-1 space-y-1">
          <input defaultValue={c.title} key={c.title} onBlur={(e) => e.target.value !== c.title && void lab.patchCourse(cid, { title: e.target.value }).then(set)} className="w-full bg-transparent font-display text-2xl font-extrabold outline-none" aria-label={t("lab.f.title")} />
          <input defaultValue={c.description} key={c.description} placeholder={t("lab.description")} onBlur={(e) => e.target.value !== c.description && void lab.patchCourse(cid, { description: e.target.value }).then(set)} className="w-full bg-transparent text-sm text-muted outline-none" aria-label={t("lab.description")} />
        </div>
        <Button variant="ghost" className="text-bad" aria-label={t("lab.deleteCourse")} title={t("lab.deleteCourse")} onClick={async () => { if (await confirmDialog(t("lab.confirmDelete"), { danger: true })) { await lab.deleteCourse(cid); navigate("/lab"); } }}><Trash2 className="h-4 w-4" aria-hidden /></Button>
      </Card>
      <StudioToolbar c={c} set={set} panel={panel} setPanel={setPanel} />
      <PublishPanel c={c} onChange={set} />
      {c.feedback && (
        <Card className="flex flex-wrap items-center gap-4 py-3 text-sm">
          <span className="flex items-center gap-1 font-semibold"><Star className="h-4 w-4 fill-yellow-400 text-yellow-500" /> {t("studio.courseRating", { avg: c.feedback.avg, count: c.feedback.n })}</span>
          <span className="text-muted">{t("studio.difficultySplit", { hard: c.feedback.hard, right: c.feedback.right, easy: c.feedback.easy })}</span>
          <span className="text-muted">{t("studio.lessonsRated", { count: c.feedback.lessons_rated })}</span>
        </Card>
      )}
      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <Card className="space-y-4 lg:sticky lg:top-20 lg:max-h-[80vh] lg:self-start lg:overflow-y-auto">
          {sections.map((s, si) => (
            <div key={s.id} className={cn("space-y-1", s.archived && "opacity-60")}>
              <div className="group flex items-center gap-1">
                {s.archived && <Archive className="h-3.5 w-3.5 shrink-0 text-muted" aria-label={t("studio.archived")} />}
                <input defaultValue={s.title} key={s.title} onBlur={(e) => e.target.value !== s.title && void lab.patchSection(s.id, { title: e.target.value }).then(set)} className="min-w-0 flex-1 bg-transparent font-display font-bold outline-none" aria-label={t("lab.section")} />
                <button disabled={si === 0} onClick={() => moveSection(si, -1)} aria-label={t("lab.up")} className="opacity-40 hover:opacity-100 disabled:invisible"><ArrowUp className="h-4 w-4" /></button>
                <button disabled={si === sections.length - 1} onClick={() => moveSection(si, 1)} aria-label={t("lab.down")} className="opacity-40 hover:opacity-100 disabled:invisible"><ArrowDown className="h-4 w-4" /></button>
                <button onClick={() => void lab.patchSection(s.id, { archived: !s.archived }).then(set)} aria-label={s.archived ? t("studio.unarchive") : t("studio.archive")} title={s.archived ? t("studio.unarchive") : t("studio.archiveHint")}
                  className="opacity-0 group-hover:opacity-100">{s.archived ? <ArchiveRestore className="h-4 w-4 text-muted" /> : <Archive className="h-4 w-4 text-muted" />}</button>
                <button onClick={async () => { if (await confirmDialog(t("lab.confirmDeleteSection", { title: s.title }), { danger: true })) void lab.deleteSection(s.id).then(set); }} aria-label={t("lab.delete")} className="opacity-0 group-hover:opacity-100"><Trash2 className="h-4 w-4 text-muted" /></button>
              </div>
              {s.subsections.map((b, bi) => (
                <div key={b.id} className={cn("group flex items-center gap-1 rounded-xl px-2 py-1.5", selected === b.id ? "bg-accent/15" : "hover:bg-surface-2", b.archived && "opacity-50")}>
                  <button onClick={() => setSelected(b.id)} className="flex min-w-0 flex-1 items-center gap-2 text-left text-sm">
                    {b.lesson_status === "generating" ? <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-accent" /> : <span className={cn("h-2.5 w-2.5 shrink-0 rounded-full", b.lesson_status === "ready" ? "bg-good" : b.lesson_status === "failed" ? "bg-bad" : "bg-line")} />}
                    <span className={cn("truncate", b.archived && "line-through")}>{b.title}</span>
                    {b.rating ? <span className="shrink-0 text-[10px] text-muted">⭐{b.rating}</span> : null}
                  </button>
                  <button onClick={async () => { await lab.patchLesson(b.id, { archived: !b.archived }); reload(); }} aria-label={b.archived ? t("studio.unarchive") : t("studio.archive")} title={b.archived ? t("studio.unarchive") : t("studio.archiveHint")}
                    className="opacity-0 group-hover:opacity-60">{b.archived ? <ArchiveRestore className="h-3.5 w-3.5" /> : <Archive className="h-3.5 w-3.5" />}</button>
                  <button disabled={bi === 0} onClick={() => moveLesson(s.id, bi, -1)} aria-label={t("lab.up")} className="opacity-0 group-hover:opacity-60 disabled:invisible"><ArrowUp className="h-3.5 w-3.5" /></button>
                  <button disabled={bi === s.subsections.length - 1} onClick={() => moveLesson(s.id, bi, 1)} aria-label={t("lab.down")} className="opacity-0 group-hover:opacity-60 disabled:invisible"><ArrowDown className="h-3.5 w-3.5" /></button>
                  <button onClick={async () => { if (!(await confirmDialog(t("lab.confirmDeleteLesson", { title: b.title }), { danger: true }))) return; await lab.deleteLesson(b.id); if (selected === b.id) setSelected(null); reload(); }} aria-label={t("lab.delete")} className="opacity-0 group-hover:opacity-60"><Trash2 className="h-3.5 w-3.5" /></button>
                </div>
              ))}
              <div className="flex flex-wrap gap-3 px-2">
                <button onClick={async () => { const title = await promptDialog(t("lab.lessonTitle")); if (title) void lab.addLesson(s.id, title).then(set); }} className="flex items-center gap-1 text-xs font-semibold text-accent"><Plus className="h-3.5 w-3.5" /> {t("lab.addLesson")}</button>
                <button onClick={() => setPicker(picker === s.id ? null : s.id)} aria-expanded={picker === s.id} className="flex items-center gap-1 text-xs font-semibold text-accent"><Copy className="h-3.5 w-3.5" /> {t("studio.picker.reuse")}</button>
              </div>
              {picker === s.id && <LessonPicker sectionId={s.id} onDone={(x) => { set(x); setPicker(null); }} />}
            </div>
          ))}
          <Button variant="outline" className="w-full py-1.5 text-sm" onClick={async () => { const title = await promptDialog(t("lab.sectionTitle")); if (title) void lab.addSection(cid, title).then(set); }}><Plus className="h-4 w-4" /> {t("lab.addSection")}</Button>
        </Card>
        <div className="space-y-4">
          {panel === "kili" && <KiliChat c={c} set={set} />}
          {panel === "grounding" && <Grounding c={c} set={set} />}
          {selected ? <LessonPanel key={selected} id={selected} courseId={cid} onChanged={reload} /> : (
            <Card className="flex flex-col items-center gap-2 py-16 text-center text-muted"><Kili mood="wave" size={110} /><p>{t("lab.pickLesson")}</p></Card>
          )}
        </div>
      </div>
    </div>
  );
}
