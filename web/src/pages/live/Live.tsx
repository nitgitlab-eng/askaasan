import { useQuery } from "@tanstack/react-query";
import { BookOpen, Camera, CameraOff, Eye, History, Mic, MicOff, MonitorUp, PhoneOff, RefreshCw, Send, ShieldCheck, Video, Volume2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { Button, Card } from "@/components/ui";
import { api } from "@/lib/api";
import { AnswerFeedback } from "@/components/AnswerFeedback";
import { WebSources } from "@/components/WebSources";
import { cn } from "@/lib/cn";
import type { Lesson } from "@/lib/learn";
import { useMe } from "@/lib/useMe";
import { snapshot, watchChanges, type Detector } from "@/live/vision";
import { useLiveSocket, type LiveMode, type LiveSummary } from "@/live/useLiveSocket";
import { Kili } from "@/mascot/Kili";
import { useMascot } from "@/mascot/store";
import { InterruptButton } from "@/voice/InterruptButton";
import { useVoiceMode } from "@/voice/useVoiceMode";

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export function SummaryCard({ s }: { s: LiveSummary }) {
  const { t } = useTranslation();
  const list = (k: "covered" | "mistakes" | "next_steps") =>
    s[k].length > 0 && (
      <div>
        <p className="font-semibold">{t(`live.sum.${k}`)}</p>
        <ul className="list-disc space-y-1 pl-5 text-sm">{s[k].map((x) => <li key={x}>{x}</li>)}</ul>
      </div>
    );
  return (
    <Card className="space-y-3">
      <h2 className="font-display text-xl font-bold">{s.title}</h2>
      {list("covered")}
      {list("mistakes")}
      {list("next_steps")}
    </Card>
  );
}

function Setup({ onStart, lesson, busy, err }: { onStart: (mode: LiveMode, topic: string) => void; lesson: Lesson | undefined; busy: boolean; err: string | null }) {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const [topic, setTopic] = useState(params.get("topic") ?? "");
  const [mode, setMode] = useState<LiveMode>("camera");
  const { data: past } = useQuery({ queryKey: ["live-sessions"], queryFn: () => api<{ id: number; title: string; minutes: number; started_at: string }[]>("/api/live/sessions/") });
  const canScreen = typeof navigator.mediaDevices?.getDisplayMedia === "function";
  const modes: { k: LiveMode; icon: typeof Camera; disabled?: boolean }[] = [
    { k: "camera", icon: Camera },
    { k: "screen", icon: MonitorUp, disabled: !canScreen },
    { k: "none", icon: Volume2 },
  ];
  return (
    <div className="mx-auto max-w-3xl space-y-5 px-4 py-8">
      <header className="flex items-center gap-4">
        <Kili mood="wave" size={84} />
        <div>
          <h1 className="font-display text-3xl font-extrabold">{t("live.title")}</h1>
          <p className="text-muted">{t("live.sub")}</p>
        </div>
      </header>
      <Card className="space-y-4">
        {lesson ? (
          <p className="flex items-center gap-2 rounded-xl bg-accent/10 px-3 py-2 font-semibold"><BookOpen className="h-5 w-5 text-accent" /> {lesson.title}</p>
        ) : (
          <label className="block">
            <span className="text-sm font-medium">{t("live.topicQ")}</span>
            <input value={topic} onChange={(e) => setTopic(e.target.value)} maxLength={300} placeholder={t("live.topicPh")} className="mt-1 w-full rounded-xl border-2 border-line bg-surface px-3 py-2.5 outline-none focus:border-accent" />
          </label>
        )}
        <div role="radiogroup" aria-label={t("live.modeQ")} className="grid gap-2 sm:grid-cols-3">
          {modes.map(({ k, icon: Icon, disabled }) => (
            <button key={k} type="button" role="radio" aria-checked={mode === k} disabled={disabled} onClick={() => setMode(k)}
              className={cn("rounded-2xl border-2 p-3 text-left transition disabled:opacity-40", mode === k ? "border-accent bg-accent/10" : "border-line hover:border-accent")}>
              <Icon className="mb-1 h-6 w-6 text-accent" />
              <p className="font-semibold">{t(`live.mode.${k}`)}</p>
              <p className="text-xs text-muted">{t(`live.modeSub.${k}`)}</p>
            </button>
          ))}
        </div>
        <div className="flex gap-2 rounded-xl bg-surface-2 p-3 text-sm">
          <ShieldCheck className="h-5 w-5 shrink-0 text-good" />
          <p>{mode === "none" ? t("live.privacyVoice") : t("live.privacy")}</p>
        </div>
        {err && <p role="alert" className="text-sm text-bad">{t(`live.err.${err}`, { defaultValue: t("mentor.errors.generic") })}</p>}
        <Button className="w-full py-3 text-lg" loading={busy} onClick={() => onStart(mode, topic)}><Video className="h-5 w-5" /> {t("live.start")}</Button>
      </Card>
      {!!past?.length && (
        <Card>
          <h2 className="mb-2 flex items-center gap-2 font-display text-lg font-bold"><History className="h-5 w-5" /> {t("live.past")}</h2>
          <ul className="divide-y divide-line">
            {past.slice(0, 8).map((s) => (
              <li key={s.id}><Link to={`/live/${s.id}`} className="flex justify-between gap-3 py-2 hover:text-accent"><span className="truncate">{s.title || t("live.untitled")}</span><span className="shrink-0 text-sm text-muted">{new Date(s.started_at).toLocaleDateString()} · {t("live.mins", { n: s.minutes })}</span></Link></li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

export default function LivePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const lessonId = Number(params.get("lesson")) || undefined;
  const { data: lesson } = useQuery({ queryKey: ["live-lesson", lessonId], queryFn: () => api<Lesson>(`/api/learn/subsections/${lessonId}/`), enabled: !!lessonId });
  const { data: me } = useMe();
  const live = useLiveSocket();
  const [mode, setMode] = useState<LiveMode>("camera");
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [paused, setPaused] = useState(false);
  const [facing, setFacing] = useState<"environment" | "user">("environment");
  const [setupErr, setSetupErr] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [typed, setTyped] = useState("");
  const [now, setNow] = useState(() => Date.now());
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement>(document.createElement("canvas"));
  const detector = useRef<Detector | null>(null);
  const pausedRef = useRef(paused);
  const pending = useRef<MediaStream | null>(null);
  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  const stopMedia = useCallback(() => {
    detector.current?.stop();
    stream?.getTracks().forEach((tr) => tr.stop());
  }, [stream]);
  useEffect(() => () => stopMedia(), [stopMedia]);

  useEffect(() => {
    if (live.status !== "live") return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [live.status]);

  async function getMedia(m: LiveMode, face = facing): Promise<MediaStream | null> {
    if (m === "none") return null;
    return m === "screen"
      ? navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 5 }, audio: false })
      : navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: face }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
  }

  const attach = useCallback((s: MediaStream | null) => {
    setStream(s);
    if (!s || !video.current) return;
    video.current.srcObject = s;
    void video.current.play();
    s.getVideoTracks()[0]?.addEventListener("ended", () => setPaused(true)); // "Stop sharing" in the browser bar
    detector.current?.stop();
    detector.current = watchChanges(video.current, () => {
      if (pausedRef.current || !video.current) return;
      const img = snapshot(video.current, canvas.current);
      if (img) live.sendFrame(img, "change");
    });
  }, [live]);

  // The <video> only mounts once the server confirms the class, so attach the camera then.
  useEffect(() => {
    if (live.status === "live" && pending.current) {
      attach(pending.current);
      pending.current = null;
    }
  }, [live.status, attach]);
  // Server refused to start (plan limit, no vision key…): release the camera straight away.
  useEffect(() => {
    if (live.error && live.status === "ready" && pending.current) {
      pending.current.getTracks().forEach((tr) => tr.stop());
      pending.current = null;
    }
  }, [live.error, live.status]);

  async function begin(m: LiveMode, topic: string) {
    setSetupErr(null);
    setStarting(true);
    try {
      const s = await getMedia(m);
      setMode(m);
      pending.current = s;
      if (!live.start({ mode: m, topic, lesson_id: lessonId })) {
        s?.getTracks().forEach((tr) => tr.stop());
        throw new Error("offline");
      }
    } catch (e) {
      const name = (e as Error).name;
      setSetupErr(name === "NotAllowedError" ? "media_denied" : name === "NotFoundError" ? "no_camera" : (e as Error).message === "offline" ? "offline" : "generic");
    } finally {
      setStarting(false);
    }
  }

  // Each time the learner speaks, Kili also gets a fresh look at the page.
  const sayWithLook = useCallback((text: string) => {
    if (mode !== "none" && !pausedRef.current && video.current) {
      const img = snapshot(video.current, canvas.current);
      if (img) {
        live.sendFrame(img, "snapshot");
        detector.current?.markSent();
      }
    }
    return live.say(text);
  }, [live, mode]);

  const replyLang = me?.preferences.mentor.reply_language;
  const voice = useVoiceMode({
    messages: live.messages,
    send: sayWithLook,
    cancel: live.cancel,
    lang: replyLang === "ta" || replyLang === "tanglish" || (replyLang === "auto" && me?.profile.language === "ta") ? "ta" : "en",
    mode: "conversation",
    busy: live.busy,
    feature: "live",
    activity: live.activity,
  });
  const mouth = useMascot((s) => s.mouth);
  const mood = useMascot((s) => s.mood);

  // Start listening as soon as the class starts: a live conversation by default.
  const autoVoice = useRef(false);
  useEffect(() => {
    if (live.status === "live" && !autoVoice.current) {
      autoVoice.current = true;
      void voice.start();
    }
    if (live.status === "ended" || live.status === "offline") {
      voice.stop();
      stopMedia();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live.status]);

  async function flip() {
    const next = facing === "environment" ? "user" : "environment";
    stream?.getTracks().forEach((tr) => tr.stop());
    setFacing(next);
    try {
      attach(await getMedia("camera", next));
    } catch {
      setPaused(true);
    }
  }

  function lookNow() {
    sayWithLook(t("live.lookPrompt"));
  }

  if (live.status === "ended" && live.summary !== undefined) {
    return (
      <div className="mx-auto max-w-3xl space-y-5 px-4 py-8">
        <div className="flex items-center gap-4"><Kili mood="celebrate" size={96} /><div><h1 className="font-display text-3xl font-extrabold">{t("live.doneTitle")}</h1><p className="text-muted">{t("live.doneSub", { mins: Math.max(1, Math.round((Date.now() - (live.session?.startedAt ?? Date.now())) / 60000)) })}</p></div></div>
        {live.summary ? <SummaryCard s={live.summary} /> : <Card className="text-muted">{t("live.noSummary")}</Card>}
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => location.reload()}>{t("live.again")}</Button>
          {lesson && <Button variant="outline" onClick={() => navigate(-1)}>{t("live.backLesson")}</Button>}
          <Button variant="ghost" onClick={() => navigate("/")}>{t("common.back")}</Button>
        </div>
      </div>
    );
  }

  if (live.status !== "live" && live.status !== "ended") {
    if (live.status === "offline" && live.session) {
      return <div className="mx-auto max-w-xl space-y-3 px-4 py-16 text-center"><Kili mood="confused" size={96} /><p className="font-semibold">{t("live.dropped")}</p><Button onClick={() => location.reload()}>{t("live.again")}</Button></div>;
    }
    return <Setup onStart={begin} lesson={lesson} busy={starting || live.status === "connecting"} err={setupErr ?? live.error} />;
  }

  const elapsed = live.session ? (now - live.session.startedAt) / 1000 : 0;
  const left = live.session?.minutesLeft != null ? Math.max(0, live.session.minutesLeft * 60 - elapsed) : null;
  const lastKili = [...live.messages].reverse().find((m) => m.role === "assistant");
  const lastMe = [...live.messages].reverse().find((m) => m.role === "user");

  return (
    <div className="flex min-h-[calc(100dvh-57px)] flex-col gap-3 px-3 py-3 md:min-h-dvh md:px-6">
      <header className="flex flex-wrap items-center gap-2">
        <span className="flex items-center gap-1.5 rounded-full bg-bad/15 px-3 py-1 text-sm font-bold text-bad"><span className="h-2 w-2 animate-pulse rounded-full bg-bad" /> LIVE</span>
        {mode !== "none" && !paused && <span className="rounded-full bg-surface-2 px-3 py-1 text-xs font-semibold">{mode === "camera" ? t("live.cameraOn") : t("live.screenOn")} · {t("live.looksN", { count: live.frames })}</span>}
        <span className="truncate font-display font-bold">{lesson?.title ?? ""}</span>
        <span className="ml-auto tabular-nums text-sm text-muted">{fmt(elapsed)}{left !== null && ` · ${t("live.left", { t: fmt(left) })}`}</span>
        <Button variant="outline" className="border-bad py-1.5 text-sm text-bad" onClick={() => { voice.stop(); live.end(); }}><PhoneOff className="h-4 w-4" /> {t("live.end")}</Button>
      </header>

      <div className="grid flex-1 gap-3 lg:grid-cols-[1fr_380px]">
        <div className="relative min-h-[240px] overflow-hidden rounded-3xl bg-ink">
          {mode === "none" ? (
            <div className="flex h-full items-center justify-center"><Kili mood={mood} size={220} mouth={mouth} color={me?.preferences.mascot.color} /></div>
          ) : (
            <>
              <video ref={video} muted playsInline className={cn("h-full max-h-[70dvh] w-full object-contain", facing === "user" && mode === "camera" && "-scale-x-100", paused && "opacity-30")} />
              {paused && <p className="absolute inset-0 flex items-center justify-center font-semibold text-white">{t("live.paused")}</p>}
              <div className="absolute bottom-3 right-3 rounded-2xl bg-surface/90 p-1 shadow-lg backdrop-blur"><Kili mood={mood} size={96} mouth={mouth} color={me?.preferences.mascot.color} /></div>
            </>
          )}
        </div>

        <Card className="flex max-h-[70dvh] flex-col gap-3">
          <div aria-live="polite" className="min-h-[96px] rounded-2xl bg-accent/10 p-3">
            <p className="text-xs font-semibold text-accent">{me?.preferences.mascot.name ?? "Kili"}{lastKili?.saw && <Eye className="ml-1 inline h-3.5 w-3.5" aria-label={t("live.saw")} />}</p>
            <p className="text-lg leading-snug">{lastKili?.content || (live.busy ? t(live.activity === "searching" ? "mentor.web.searching" : "mentor.thinking") : "…")}</p>
            {lastKili && !lastKili.streaming && <WebSources citations={lastKili.citations} />}
            {lastKili && !lastKili.streaming && <AnswerFeedback key={String(lastKili.id)} kind="live" id={lastKili.id} />}
          </div>
          <div className="min-h-[48px] rounded-2xl bg-surface-2 p-3 text-sm">
            <p className="text-xs font-semibold text-muted">{t("live.you")}</p>
            <p className="italic">{voice.interim || lastMe?.content || (voice.active ? t("live.speakNow") : t("live.typeOrMic"))}</p>
          </div>
          <details className="min-h-0 flex-1 overflow-y-auto text-sm">
            <summary className="cursor-pointer text-muted">{t("live.transcript")} ({live.messages.length})</summary>
            <ul className="mt-2 space-y-1.5">{live.messages.map((m) => <li key={m.id} className={m.role === "user" ? "text-right" : ""}><span className={cn("inline-block rounded-xl px-2.5 py-1", m.role === "user" ? "bg-accent text-accent-ink" : "bg-surface-2")}>{m.content}</span></li>)}</ul>
          </details>
          {live.error && live.error !== "plan_limit" && <p role="alert" className="text-sm text-bad">{t(`live.err.${live.error}`, { defaultValue: t("mentor.errors.generic") })}</p>}
          {voice.error && <p role="alert" className="text-sm text-bad">{t(`mentor.voice.errors.${voice.error}`, { defaultValue: t("mentor.errors.generic") })}</p>}
          <form onSubmit={(e: FormEvent) => { e.preventDefault(); if (typed.trim() && sayWithLook(typed.trim())) setTyped(""); }} className="flex gap-2">
            <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={t("live.typePh")} aria-label={t("live.typePh")} className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2 outline-none focus:border-accent" />
            <button className="rounded-xl bg-accent p-2.5 text-accent-ink disabled:opacity-50" disabled={!typed.trim() || live.busy} aria-label={t("mentor.send")}><Send className="h-4 w-4" /></button>
          </form>
        </Card>
      </div>

      <div className="flex flex-wrap items-center justify-center gap-2 pb-24 md:pb-2">
        <Button className={cn("min-w-36", voice.active ? "bg-bad text-white" : "")} onClick={() => (voice.active ? voice.stop() : void voice.start())} aria-pressed={voice.active}>
          {voice.active ? <MicOff className="h-5 w-5" /> : <Mic className="h-5 w-5" />} {voice.active ? t("live.mute") : t("live.unmute")}
        </Button>
        <InterruptButton voice={voice} busy={live.busy} className="min-h-11" />
        {mode !== "none" && (
          <>
            <Button variant="outline" disabled={paused || live.busy} onClick={lookNow}><Eye className="h-5 w-5" /> {t("live.look")}</Button>
            <Button variant="outline" onClick={() => setPaused((p) => !p)} aria-pressed={paused}>{paused ? <Camera className="h-5 w-5" /> : <CameraOff className="h-5 w-5" />} {paused ? t("live.resume") : t("live.pause")}</Button>
            {mode === "camera" && <Button variant="ghost" onClick={flip} title={t("live.flip")}><RefreshCw className="h-5 w-5" /></Button>}
          </>
        )}
      </div>
    </div>
  );
}
