import { Plus, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";

import { mmss, toSec, youtubeId } from "./creatorKit";
import { ImageField } from "./MediaPicker";

const input = "w-full rounded-xl border-2 border-line bg-surface px-3 py-2 outline-none focus:border-accent";
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Src = Record<string, any>;

/** Video + timed checkpoint questions. AI can draft questions from the teacher's notes/transcript. */
export function VideoForm({ src, setSrc, lessonId }: { src: Src; setSrc: (s: Src) => void; lessonId: number }) {
  const { t } = useTranslation();
  const [url, setUrl] = useState(src.video_id ? `https://youtu.be/${src.video_id}` : "");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const set = (k: string, v: unknown) => setSrc({ ...src, [k]: v });
  const cps = src.checkpoints as { at: number; question: string; options: string[]; correct: number[] }[];
  const setCp = (i: number, patch: object) => set("checkpoints", cps.map((c, k) => (k === i ? { ...c, ...patch } : c)));
  async function draft() {
    setBusy(true);
    setErr("");
    try {
      const r = await api<{ checkpoints: typeof cps }>(`/api/lab/subsections/${lessonId}/video-questions/`, { method: "POST", json: { notes, start: src.start, end: src.end } });
      set("checkpoints", [...cps, ...r.checkpoints]);
    } catch (e) {
      setErr(e instanceof ApiError ? String(e.data?.code) : t("mentor.errors.generic"));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-3">
      <label className="block space-y-1 text-sm font-medium">{t("lab.video.url")}
        <input className={input} value={url} placeholder="https://www.youtube.com/watch?v=…" onChange={(e) => { setUrl(e.target.value); set("video_id", youtubeId(e.target.value)); }} />
        {url && !src.video_id && <span className="text-xs text-bad">{t("lab.video.badUrl")}</span>}
      </label>
      {src.video_id && <img src={`https://i.ytimg.com/vi/${src.video_id}/mqdefault.jpg`} alt="" className="h-28 rounded-xl" />}
      <div className="grid grid-cols-2 gap-2">
        <label className="text-sm font-medium">{t("lab.video.start")}<input className={input} defaultValue={mmss(src.start)} onBlur={(e) => set("start", toSec(e.target.value))} /></label>
        <label className="text-sm font-medium">{t("lab.video.end")}<input className={input} defaultValue={src.end ? mmss(src.end) : ""} placeholder={t("lab.video.toEnd")} onBlur={(e) => set("end", e.target.value.trim() ? toSec(e.target.value) : 0)} /></label>
      </div>
      <div className="space-y-2 rounded-xl bg-surface-2 p-3">
        <p className="text-sm font-semibold">{t("lab.video.draftTitle")}</p>
        <textarea className={input} rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder={t("lab.video.notesPh")} />
        <Button variant="outline" className="py-1.5 text-sm" loading={busy} disabled={notes.trim().length < 20} onClick={draft}><Sparkles className="h-4 w-4" /> {t("lab.video.draft")}</Button>
        {err && <p className="text-sm text-bad">{err}</p>}
      </div>
      {cps.map((c, i) => (
        <div key={i} className="space-y-2 rounded-xl border-2 border-line p-3">
          <div className="flex items-center gap-2">
            <input className={cn(input, "w-24")} defaultValue={mmss(c.at)} aria-label={t("lab.video.at")} onBlur={(e) => setCp(i, { at: toSec(e.target.value) })} />
            <input className={input} value={c.question} placeholder={t("lab.video.question")} onChange={(e) => setCp(i, { question: e.target.value })} />
            <button onClick={() => set("checkpoints", cps.filter((_, k) => k !== i))} aria-label={t("lab.remove")}><Trash2 className="h-4 w-4 text-muted" /></button>
          </div>
          {c.options.map((o, k) => (
            <div key={k} className="flex items-center gap-2 pl-4">
              <input type="checkbox" checked={c.correct.includes(k)} aria-label={t("lab.f.correct")} onChange={(e) => setCp(i, { correct: e.target.checked ? [...c.correct, k].sort() : c.correct.filter((x) => x !== k) })} />
              <input className={input} value={o} onChange={(e) => setCp(i, { options: c.options.map((x, j) => (j === k ? e.target.value : x)) })} />
            </div>
          ))}
          <button className="pl-4 text-sm font-semibold text-accent" onClick={() => setCp(i, { options: [...c.options, ""] })}>+ {t("lab.f.addOption")}</button>
        </div>
      ))}
      <button className="flex items-center gap-1 text-sm font-semibold text-accent" onClick={() => set("checkpoints", [...cps, { at: src.start || 0, question: "", options: ["", ""], correct: [] }])}><Plus className="h-4 w-4" /> {t("lab.video.addQ")}</button>
    </div>
  );
}

/** Image + labels the learner must place. Click the picture to set where the selected label belongs. */
export function HotspotForm({ src, setSrc }: { src: Src; setSrc: (s: Src) => void }) {
  const { t } = useTranslation();
  const [active, setActive] = useState(0);
  const targets = src.targets as { label: string; x: number; y: number; r: number }[];
  const set = (k: string, v: unknown) => setSrc({ ...src, [k]: v });
  const setT = (i: number, patch: object) => set("targets", targets.map((x, k) => (k === i ? { ...x, ...patch } : x)));
  return (
    <div className="space-y-3">
      <ImageField value={src.image} onChange={(u) => set("image", u)} />
      {src.image && (
        <>
          <p className="text-sm text-muted">{t("lab.hotspot.help")}</p>
          <div className="relative cursor-crosshair overflow-hidden rounded-2xl border-2 border-line" onClick={(e) => {
            if (!targets[active]) return;
            const r = e.currentTarget.getBoundingClientRect();
            setT(active, { x: Math.round(((e.clientX - r.left) / r.width) * 1000) / 10, y: Math.round(((e.clientY - r.top) / r.height) * 1000) / 10 });
          }}>
            <img src={src.image} alt="" className="block w-full" draggable={false} />
            {targets.map((tg, i) => (
              <span key={i} className={cn("absolute -translate-x-1/2 -translate-y-1/2 rounded-full border-2", i === active ? "border-orange-500 bg-orange-400/25" : "border-blue-600 bg-blue-500/20")}
                style={{ left: `${tg.x}%`, top: `${tg.y}%`, width: `${tg.r * 2}%`, aspectRatio: "1" }}>
                <span className="absolute -top-5 left-1/2 -translate-x-1/2 whitespace-nowrap rounded bg-ink px-1 text-[10px] text-bg">{i + 1}. {tg.label}</span>
              </span>
            ))}
          </div>
          {targets.map((tg, i) => (
            <div key={i} className={cn("flex items-center gap-2 rounded-xl p-1", i === active && "bg-accent/10")} onClick={() => setActive(i)}>
              <span className="w-6 text-center font-bold">{i + 1}</span>
              <input className={input} value={tg.label} placeholder={t("lab.hotspot.label")} onChange={(e) => setT(i, { label: e.target.value })} />
              <label className="flex items-center gap-1 text-xs text-muted">{t("lab.hotspot.size")}<input type="range" min={3} max={20} value={tg.r} onChange={(e) => setT(i, { r: Number(e.target.value) })} /></label>
              <button onClick={(e) => { e.stopPropagation(); set("targets", targets.filter((_, k) => k !== i)); }} aria-label={t("lab.remove")}><Trash2 className="h-4 w-4 text-muted" /></button>
            </div>
          ))}
          <button className="flex items-center gap-1 text-sm font-semibold text-accent" onClick={() => { set("targets", [...targets, { label: "", x: 50, y: 50, r: 8 }]); setActive(targets.length); }}><Plus className="h-4 w-4" /> {t("lab.hotspot.add")}</button>
        </>
      )}
    </div>
  );
}
