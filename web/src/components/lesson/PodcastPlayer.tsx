import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Mic } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { heardTracker, hostRoles, journey, TURN_GAP_MS, podcastErrorKey, podcastStuck, type PodcastTurn, type WarmupQ } from "@/lib/journey";

import { NarrationControls } from "./Narration";
import { useNarrator } from "./narration-hooks";

/** 🎙️ Lesson podcast: two hosts (curious learner + friendly expert) talk the lesson through. Cached per lesson + language. */
export function PodcastPlayer({ lessonId, lang, onListened }: { lessonId: number; lang: string; onListened?: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const key = ["podcast", lessonId, lang];
  const { data, error } = useQuery({ queryKey: key, queryFn: () => journey.podcast(lessonId, lang),
    // Poll while it's being made; stop once the server (or the clock) says the job is stuck.
    refetchInterval: (q) => (q.state.data?.status === "generating" && !podcastStuck(q.state.data) ? 2500 : false) });
  const [err, setErr] = useState("");
  const make = async () => {
    setErr("");
    try { qc.setQueryData(key, await journey.makePodcast(lessonId, lang)); }
    catch (e) { setErr(e instanceof ApiError && e.data?.code ? t(podcastErrorKey(e.data.code)) : t("mentor.errors.generic")); }
  };
  const ready = data?.status === "ready" && !!data.turns?.length;
  const stuck = podcastStuck(data);
  const generating = data?.status === "generating" && !stuck;
  const failed = data?.status === "failed" || stuck;
  const loadErr = !data && error instanceof ApiError && error.data?.code ? t(podcastErrorKey(error.data.code)) : "";
  return (
    <div className="rounded-2xl border-2 border-line p-3">
      <p className="flex items-center gap-2 font-semibold"><Mic className="h-5 w-5 text-accent" /> {t("lj.podcast.title")}</p>
      {ready ? (
        <Episode turns={data.turns!} title={data.title ?? ""} hosts={data.hosts ?? {}} lang={lang} lessonId={lessonId} onListened={onListened} />
      ) : (
        <div className="mt-2 space-y-2">
          {failed ? (
            <p role="alert" className="text-sm text-bad">{t(stuck ? "lj.podcast.stuck" : podcastErrorKey(data?.error))}</p>
          ) : (
            <p className="text-sm text-muted">{generating ? t("lj.podcast.making") : loadErr || t("lj.podcast.sub")}</p>
          )}
          {!generating && !loadErr && <Button variant="outline" onClick={make}>{t(failed ? "common.retry" : "lj.podcast.make")}</Button>}
          {generating && !!data?.warmup.length && <Warmup questions={data.warmup} />}
        </div>
      )}
      {data?.outdated && <Button variant="outline" className="mt-2" onClick={make}>{t("lj.podcast.refresh")}</Button>}
      {err && <p role="alert" className="mt-2 text-sm text-bad">{err}</p>}
    </div>
  );
}

function Episode({ turns, title, hosts, lang, lessonId, onListened }: {
  turns: PodcastTurn[]; title: string; hosts: { A?: string; B?: string }; lang: string; lessonId: number; onListened?: () => void;
}) {
  const { t } = useTranslation();
  const roles = useMemo(() => hostRoles(turns), [turns]);
  const onPartDone = useMemo(() => heardTracker((parts) => {
    void journey.heard(lessonId, "podcast", parts, lang).then((r) => { if (r.listened) onListened?.(); }).catch(() => {});
  }, turns.length), [lessonId, lang, turns.length, onListened]);
  const { st, n } = useNarrator(turns.map((x) => x.text), lang, { roles, onPartDone, turnGapMs: TURN_GAP_MS });
  const name = (s: "A" | "B") => t(s === "A" ? "lj.podcast.hostA" : "lj.podcast.hostB", { name: hosts[s] || s });
  return (
    <div className="mt-3 space-y-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</p>
      <NarrationControls st={st} n={n} count={turns.length} labels={turns.map((x) => hosts[x.speaker] || x.speaker)} />
      <p className="text-sm font-semibold">{t("lj.podcast.transcript")} <span className="font-normal text-muted">· {t("lj.podcast.tapLine")}</span></p>
      <ol className="max-h-80 space-y-1.5 overflow-y-auto rounded-xl bg-surface-2 p-2">
        {turns.map((x, i) => (
          <li key={i}>
            <button type="button" onClick={() => n.current.goTo(i)} aria-current={i === st.part ? "true" : undefined}
              className={cn("w-full rounded-lg px-2 py-1.5 text-left text-sm", i === st.part ? "bg-accent/15 ring-2 ring-accent/40" : "hover:bg-surface")}>
              <span className={cn("mr-1 font-semibold", x.speaker === "A" ? "text-accent" : "text-violet-700 dark:text-violet-300")}>{name(x.speaker)}:</span>
              {x.text}
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Quick 'fill the missing word' warm-up from the lesson's key points, shown while the episode is generated. */
export function Warmup({ questions }: { questions: WarmupQ[] }) {
  const { t } = useTranslation();
  const [picked, setPicked] = useState<Record<number, number>>({});
  const right = questions.filter((q, i) => picked[i] === q.answer).length;
  const done = Object.keys(picked).length === questions.length;
  return (
    <div className="space-y-3 rounded-xl bg-surface-2 p-3">
      <p className="font-semibold">{t("lj.warmup.title")} <span className="text-sm font-normal text-muted">· {t("lj.warmup.sub")}</span></p>
      {questions.map((q, i) => (
        <fieldset key={i} className="space-y-1.5">
          <legend className="text-sm">{q.prompt}</legend>
          <div className="flex flex-wrap gap-1.5">
            {q.options.map((o, j) => (
              <button key={j} type="button" disabled={picked[i] !== undefined} aria-pressed={picked[i] === j}
                onClick={() => setPicked((p) => ({ ...p, [i]: j }))}
                className={cn("rounded-full border-2 px-3 py-1 text-sm",
                  picked[i] === undefined ? "border-line hover:border-accent" : j === q.answer ? "border-good bg-good/10" : picked[i] === j ? "border-bad bg-bad/10" : "border-line opacity-60")}>
                {o}
              </button>
            ))}
          </div>
          {picked[i] !== undefined && (
            <p role="status" className={cn("text-xs", picked[i] === q.answer ? "text-good" : "text-bad")}>
              {picked[i] === q.answer ? t("lj.warmup.right") : t("lj.warmup.wrong", { answer: q.options[q.answer] })}
            </p>
          )}
        </fieldset>
      ))}
      {done && <p className="text-sm font-semibold">{t("lj.warmup.done", { n: right, total: questions.length })}</p>}
    </div>
  );
}
