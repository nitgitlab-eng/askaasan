import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, Trash2, Upload } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card, Segmented } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { mmss, parseMmss, studio, type Lecture, type Segment } from "@/lib/studio";

const input = "rounded-lg border-2 border-line bg-surface px-2 py-1 text-sm outline-none focus:border-accent";

function mediaDuration(file: File): Promise<number> {
  return new Promise((resolve) => {
    const el = document.createElement(file.type.startsWith("audio") ? "audio" : "video");
    el.preload = "metadata";
    el.onloadedmetadata = () => { resolve(Number.isFinite(el.duration) ? el.duration : 0); URL.revokeObjectURL(el.src); };
    el.onerror = () => resolve(0);
    el.src = URL.createObjectURL(file);
  });
}

/** P3 lecture video: upload (→ speech-to-text) or YouTube + transcript → AI segments → accept / re-trim → video activities. */
export function LectureTool({ lessonId, onBuilt }: { lessonId: number; onBuilt: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"upload" | "youtube">("upload");
  const [url, setUrl] = useState("");
  const [transcript, setTranscript] = useState("");
  const [minutes, setMinutes] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const { data: list } = useQuery({
    queryKey: ["lectures", lessonId], queryFn: () => studio.lectures(lessonId), enabled: open,
    refetchInterval: (q) => (q.state.data?.some((l) => l.status === "transcribing" || l.status === "segmenting") ? 2500 : false),
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["lectures", lessonId] });
  const fail = (e: unknown) => {
    const code = (e as { data?: { code?: string } })?.data?.code ?? (e instanceof ApiError ? String(e.data?.code ?? "") : "");
    setErr(t(`studio.lecture.err.${code}`, { defaultValue: t("mentor.errors.generic") }));
  };

  async function upload(file: File) {
    setBusy(true);
    setErr("");
    try {
      await studio.uploadLecture(lessonId, file, await mediaDuration(file));
      refresh();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function addYoutube() {
    setBusy(true);
    setErr("");
    try {
      await studio.addYoutube(lessonId, { youtube_url: url, transcript, duration: Math.round(Number(minutes || 0) * 60) });
      setUrl("");
      setTranscript("");
      refresh();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  if (!open) return <Button variant="outline" onClick={() => setOpen(true)}><Clapperboard className="h-4 w-4" /> {t("studio.lecture.open")}</Button>;
  return (
    <Card className="space-y-3">
      <div className="flex items-center justify-between"><h4 className="font-display text-lg font-bold">{t("studio.lecture.title")}</h4>
        <button onClick={() => setOpen(false)} className="text-sm text-muted">{t("common.close")}</button></div>
      <Segmented label={t("studio.lecture.source")} value={mode} onChange={setMode}
        options={[{ value: "upload" as const, label: t("studio.lecture.upload") }, { value: "youtube" as const, label: "YouTube" }]} />
      {mode === "upload" ? (
        <label className={cn("flex cursor-pointer items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-line p-5 text-sm font-semibold hover:border-accent", busy && "pointer-events-none opacity-60")}>
          <Upload className="h-5 w-5" /> {busy ? t("studio.lecture.uploading") : t("studio.lecture.pick")}
          <input type="file" accept="video/mp4,video/webm,audio/mpeg,audio/mp4,audio/wav,audio/ogg,.m4a" className="sr-only" onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = ""; }} />
        </label>
      ) : (
        <div className="space-y-2">
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://www.youtube.com/watch?v=…" className={cn(input, "w-full")} aria-label="YouTube URL" />
          <textarea value={transcript} onChange={(e) => setTranscript(e.target.value)} rows={5} placeholder={t("studio.lecture.transcriptPh")} className={cn(input, "w-full font-mono text-xs")} aria-label={t("studio.lecture.transcript")} />
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1 text-sm">{t("studio.lecture.length")}<input value={minutes} onChange={(e) => setMinutes(e.target.value)} inputMode="decimal" className={cn(input, "w-20")} /></label>
            <Button loading={busy} disabled={!url || transcript.length < 40} onClick={() => void addYoutube()}>{t("studio.lecture.segment")}</Button>
          </div>
        </div>
      )}
      <p className="text-xs text-muted">{t("studio.lecture.hint")}</p>
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
      {list?.map((lv) => <LectureReview key={lv.id} lv={lv} onDone={() => { refresh(); onBuilt(); }} />)}
    </Card>
  );
}

function LectureReview({ lv, onDone }: { lv: Lecture; onDone: () => void }) {
  const { t } = useTranslation();
  const [segs, setSegs] = useState<(Segment & { keep: boolean })[]>(() => lv.segments.map((s) => ({ ...s, keep: true })));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const qc = useQueryClient();
  if (lv.status === "transcribing" || lv.status === "segmenting") return <p role="status" className="rounded-xl bg-surface-2 p-3 text-sm">⏳ {t(`studio.lecture.${lv.status}`)} — {lv.title || lv.video_id}</p>;
  if (lv.status === "failed") {
    return (
      <div className="flex items-center justify-between rounded-xl bg-bad/10 p-3 text-sm text-bad">
        <span>{t(`studio.lecture.err.${lv.error}`, { defaultValue: t("studio.lecture.failed") })}</span>
        <button onClick={async () => { await studio.deleteLecture(lv.id); void qc.invalidateQueries({ queryKey: ["lectures"] }); }} aria-label={t("lab.delete")}><Trash2 className="h-4 w-4" /></button>
      </div>
    );
  }
  const upd = (i: number, patch: Partial<Segment & { keep: boolean }>) => setSegs(segs.map((s, k) => (k === i ? { ...s, ...patch } : s)));
  async function build() {
    setBusy(true);
    setMsg("");
    try {
      const keep = segs.filter((s) => s.keep).map(({ keep: _k, ...s }) => ({ ...s, checkpoints: s.checkpoints.map((c) => ({ ...c, at: Math.min(Math.max(c.at, s.start), s.end || c.at) })) }));
      const r = await studio.buildLecture(lv.id, keep);
      setMsg(t("studio.lecture.built", { n: r.built }) + (r.errors.length ? ` · ${t("studio.lecture.skippedN", { n: r.errors.length })}` : ""));
      onDone();
    } catch (e) {
      setMsg(e instanceof ApiError ? String(e.data?.errors ? t("studio.lecture.checkSegments") : e.data?.code) : t("mentor.errors.generic"));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-2 rounded-2xl border-2 border-line p-3">
      <p className="text-sm font-semibold">{lv.title || `YouTube ${lv.video_id}`} · {mmss(lv.duration)}</p>
      {lv.src && <video src={lv.src} controls preload="metadata" className="max-h-48 w-full rounded-xl bg-black" />}
      <ol className="space-y-2">
        {segs.map((s, i) => (
          <li key={i} className={cn("space-y-1 rounded-xl border px-3 py-2 text-sm", s.keep ? "border-accent/50" : "border-line opacity-60")}>
            <div className="flex flex-wrap items-center gap-2">
              <input type="checkbox" checked={s.keep} onChange={() => upd(i, { keep: !s.keep })} aria-label={t("studio.lecture.keep")} />
              <input value={s.title} onChange={(e) => upd(i, { title: e.target.value })} className={cn(input, "min-w-0 flex-1 font-semibold")} aria-label={t("lab.f.title")} />
              <input defaultValue={mmss(s.start)} onBlur={(e) => { const v = parseMmss(e.target.value); if (v !== null) upd(i, { start: v }); }} className={cn(input, "w-16 tabular-nums")} aria-label={t("studio.lecture.start")} />
              <span>–</span>
              <input defaultValue={mmss(s.end)} onBlur={(e) => { const v = parseMmss(e.target.value); if (v !== null) upd(i, { end: v }); }} className={cn(input, "w-16 tabular-nums")} aria-label={t("studio.lecture.end")} />
            </div>
            <p className="text-xs text-muted">{s.summary}</p>
            {s.checkpoints.map((c, k) => (
              <div key={k} className="rounded-lg bg-surface-2 px-2 py-1 text-xs">
                <input value={c.question} onChange={(e) => upd(i, { checkpoints: s.checkpoints.map((x, j) => (j === k ? { ...x, question: e.target.value } : x)) })} className="w-full bg-transparent font-medium outline-none" aria-label={t("studio.lecture.question")} />
                <span className="text-muted">{c.options.map((o, j) => (c.correct.includes(j) ? `✓ ${o}` : o)).join(" · ")}</span>
              </div>
            ))}
          </li>
        ))}
      </ol>
      <div className="flex flex-wrap items-center gap-2">
        <Button loading={busy} disabled={!segs.some((s) => s.keep)} onClick={() => void build()}>{t("studio.lecture.build", { n: segs.filter((s) => s.keep).length })}</Button>
        {msg && <span role="status" className="text-sm">{msg}</span>}
      </div>
    </div>
  );
}
