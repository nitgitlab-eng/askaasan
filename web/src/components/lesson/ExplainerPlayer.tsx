import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, FileText } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { learner, type Scene } from "@/lib/learner";

import { NarrationControls } from "./Narration";
import { useNarrator } from "./narration-hooks";

/** 🎬 AI explainer video: an AI-written scene script, animated on screen in sync with narration. */
export function ExplainerPlayer({ lessonId, lang }: { lessonId: number; lang: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const key = ["explainer", lessonId, lang];
  const { data } = useQuery({ queryKey: key, queryFn: () => learner.explainer(lessonId, lang),
    refetchInterval: (q) => (q.state.data?.status === "generating" ? 2500 : false) });
  const [err, setErr] = useState("");
  const make = async () => {
    setErr("");
    try { qc.setQueryData(key, await learner.makeExplainer(lessonId, lang)); }
    catch (e) { setErr(e instanceof ApiError && e.status === 429 ? t("explainer.budget") : t("mentor.errors.generic")); }
  };
  return (
    <div className="rounded-2xl border-2 border-line p-3">
      <p className="flex items-center gap-2 font-semibold"><Clapperboard className="h-5 w-5 text-accent" /> {t("explainer.title")}</p>
      {data?.status === "ready" && data.scenes?.length ? <Player scenes={data.scenes} title={data.title ?? ""} lang={lang} /> : (
        <div className="mt-2 space-y-2">
          <p className="text-sm text-muted">{data?.status === "generating" ? t("explainer.making") : data?.status === "failed" ? t("explainer.failed") : t("explainer.sub")}</p>
          {data?.status !== "generating" && <Button variant="outline" onClick={make}>{t(data?.status === "failed" ? "common.retry" : "explainer.make")}</Button>}
        </div>
      )}
      {data?.outdated && <Button variant="outline" className="mt-2" onClick={make}>{t("explainer.refresh")}</Button>}
      {err && <p role="alert" className="mt-2 text-sm text-bad">{err}</p>}
    </div>
  );
}

function Player({ scenes, title, lang }: { scenes: Scene[]; title: string; lang: string }) {
  const { t } = useTranslation();
  const { st, n } = useNarrator(scenes.map((s) => s.narration), lang);
  const [showText, setShowText] = useState(false);
  const s = scenes[Math.min(st.part, scenes.length - 1)];
  return (
    <div className="mt-3 space-y-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</p>
      <div className="relative flex min-h-56 overflow-hidden rounded-2xl bg-gradient-to-br from-accent/25 via-surface-2 to-accent/10 px-5 pb-6 pt-5 sm:min-h-72" aria-live="polite">
        <div key={st.part} className="flex w-full animate-[fadein_.5s_ease] flex-col items-center justify-center gap-2 text-center">
          <span className={st.playing ? "animate-[float_3s_ease-in-out_infinite] text-5xl sm:text-6xl" : "text-5xl sm:text-6xl"} aria-hidden>{s.visual}</span>
          <h3 className="font-display text-xl font-extrabold leading-snug sm:text-2xl">{s.heading}</h3>
          <ul className="space-y-1">
            {s.points.map((p, i) => <li key={i} style={{ animationDelay: `${0.3 + i * 0.5}s` }} className="animate-[fadein_.6s_ease_both] text-base sm:text-lg">• {p}</li>)}
          </ul>
        </div>
        <div className="absolute inset-x-0 bottom-0 flex h-1.5 gap-0.5">
          {scenes.map((_, i) => <span key={i} className={i <= st.part ? "flex-1 bg-accent" : "flex-1 bg-line"} />)}
        </div>
      </div>
      <NarrationControls st={st} n={n} count={scenes.length} labels={scenes.map((x) => x.heading)} />
      <button type="button" className="flex items-center gap-1.5 text-sm font-semibold text-accent" aria-expanded={showText} onClick={() => setShowText((v) => !v)}>
        <FileText className="h-4 w-4" /> {t("explainer.transcript")}
      </button>
      {showText && (
        <ol className="space-y-1 rounded-xl bg-surface-2 p-2 text-sm">
          {scenes.map((x, i) => (
            <li key={i}>
              <button type="button" onClick={() => n.current.goTo(i)} aria-current={i === st.part ? "true" : undefined}
                className={cn("w-full rounded-lg px-2 py-1.5 text-left", i === st.part ? "bg-accent/15 ring-2 ring-accent/40" : "hover:bg-surface")}>
                {x.narration}
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
