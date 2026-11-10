import { Headphones, Pause, Play, RotateCcw, SkipBack, SkipForward, Rewind, FastForward } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Toggle } from "@/components/ui";
import { cn } from "@/lib/cn";
import { heardTracker, journey } from "@/lib/journey";
import type { NarratorState } from "@/voice/narrator";

import { lessonParts, useNarrator, type LazyNarrator } from "./narration-hooks";

export function NarrationControls({ st, n, count, labels }: { st: NarratorState; n: LazyNarrator; count: number; labels?: string[] }) {
  const { t } = useTranslation();
  const [auto, setAuto] = useState(true);
  const [rate, setRate] = useState(1);
  const btn = "flex h-10 w-10 items-center justify-center rounded-full border-2 border-line hover:border-accent disabled:opacity-40";
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={btn} aria-label={t("listen.prev")} disabled={st.part === 0} onClick={() => n.current.goTo(st.part - 1)}><SkipBack className="h-4 w-4" /></button>
        <button type="button" className={btn} aria-label={t("listen.back10")} onClick={() => n.current.seek(-10)}><Rewind className="h-4 w-4" /></button>
        <button type="button" aria-label={st.playing ? t("listen.pause") : t("listen.play")}
          className="flex h-12 w-12 items-center justify-center rounded-full bg-accent text-accent-ink"
          onClick={() => (st.playing ? n.current.pause() : st.ended ? n.current.goTo(0) : n.current.resume())}>
          {st.playing ? <Pause className="h-5 w-5" /> : <Play className="h-5 w-5" />}
        </button>
        <button type="button" className={btn} aria-label={t("listen.fwd10")} onClick={() => n.current.seek(10)}><FastForward className="h-4 w-4" /></button>
        <button type="button" className={btn} aria-label={t("listen.next")} disabled={st.part >= count - 1} onClick={() => n.current.goTo(st.part + 1)}><SkipForward className="h-4 w-4" /></button>
        <button type="button" className={btn} aria-label={t("listen.replay")} onClick={() => n.current.replay()}><RotateCcw className="h-4 w-4" /></button>
        <select aria-label={t("listen.speed")} value={rate} onChange={(e) => { const r = Number(e.target.value); setRate(r); n.current.setRate(r); }}
          className="rounded-lg border-2 border-line bg-surface px-2 py-1 text-sm">
          {[0.75, 1, 1.25, 1.5].map((r) => <option key={r} value={r}>{r}×</option>)}
        </select>
        <span role="status" className="text-sm text-muted">
          {st.loading ? t("listen.loading") : t("listen.part", { n: st.part + 1, total: count })}{labels?.[st.part] ? ` · ${labels[st.part]}` : ""}
        </span>
      </div>
      <Toggle label={t("listen.autoplay")} checked={auto} onChange={(v) => { setAuto(v); n.current.setAutoplay(v); }} />
      {st.error && <p role="alert" className="text-sm text-bad">{t("listen.noVoice")}</p>}
    </div>
  );
}

/** 🎧 Listen mode: the lesson read aloud, section by section. */
export function ListenBar({ md, title, keyPoints, lang, lessonId, onListened }: {
  md: string; title: string; keyPoints: string[]; lang: string; lessonId?: number; onListened?: () => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const parts = lessonParts(md, title);
  if (keyPoints.length) parts.push({ label: t("lesson.keyPoints"), text: keyPoints.join(". ") });
  return (
    <div className="rounded-2xl border-2 border-line p-3">
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="flex items-center gap-2 font-semibold">
        <Headphones className="h-5 w-5 text-accent" /> {t("listen.title")}
      </button>
      {open && <ListenInner parts={parts} lang={lang} lessonId={lessonId} onListened={onListened} />}
    </div>
  );
}

function ListenInner({ parts, lang, lessonId, onListened }: { parts: { label: string; text: string }[]; lang: string; lessonId?: number; onListened?: () => void }) {
  // Listening progress: parts heard to the end are reported; ≥80% marks the explanation "listened" (never completes the lesson).
  const onPartDone = useMemo(() => (lessonId ? heardTracker((heard) => {
    void journey.heard(lessonId, "listen", heard, lang).then((r) => { if (r.listened) onListened?.(); }).catch(() => {});
  }, parts.length) : undefined), [lessonId, lang, parts.length, onListened]);
  const { st, n } = useNarrator(parts.map((p) => p.text), lang, { onPartDone });
  return (
    <div className="mt-3 space-y-3">
      <NarrationControls st={st} n={n} count={parts.length} labels={parts.map((p) => p.label)} />
      <ol className="flex flex-wrap gap-1.5">
        {parts.map((p, i) => (
          <li key={i}>
            <button type="button" onClick={() => n.current.goTo(i)}
              className={cn("rounded-full border px-2.5 py-0.5 text-xs", i === st.part ? "border-accent bg-accent/10 font-semibold" : "border-line")}>
              {p.label.slice(0, 40)}
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
