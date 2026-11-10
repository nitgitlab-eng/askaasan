import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ChevronDown, Mic, Play } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useNavigate, useParams } from "react-router-dom";

import { Md } from "@/components/Md";
import { PageError } from "@/components/PageState";
import { Button, Card } from "@/components/ui";
import { HelpPanel } from "@/components/workshop/HelpPanel";
import { LiveStage, type Sock } from "@/components/workshop/LiveStage";
import { ProctorNotice } from "@/components/workshop/ProctorNotice";
import { StaffNudges } from "@/components/workshop/StaffNudge";
import { cn } from "@/lib/cn";
import { useMe, useUpdatePreferences } from "@/lib/useMe";
import { currentStage, errorCode, isDiy, useProctoring, useWorkshopSocket, workshops, type Session } from "@/lib/workshops";
import { Kili } from "@/mascot/Kili";
import { BrowserRecognition, fetchVoiceConfig, unlockAudio, type Lang } from "@/voice/engines";
import { listenOnce } from "@/voice/oneShot";
import { useVoiceMode, type VoiceMode } from "@/voice/useVoiceMode";

const sessionKey = (id: number) => ["workshop-session", id] as const;
const MIC_OK_KEY = "aasan-ws-mic-ok";

const readMicOk = () => {
  try {
    return localStorage.getItem(MIC_OK_KEY) === "1";
  } catch {
    return false;
  }
};

/** "Say hello to <companion>": a one-time mic check that also unlocks audio for the session (it runs in the tap). */
function MicCheck({ lang }: { lang: Lang }) {
  const { t } = useTranslation();
  const [state, setState] = useState<"idle" | "listening" | "heard" | "none" | "denied" | "unsupported">(() => (readMicOk() ? "heard" : "idle"));
  const [text, setText] = useState("");

  async function check() {
    unlockAudio(); // inside the tap, before any await
    setState("listening");
    try {
      const cfg = await fetchVoiceConfig().catch(() => null);
      if ((!cfg || cfg.stt.engine === "browser") && !BrowserRecognition) return setState("unsupported");
      const heard = await listenOnce(lang, 6000);
      setText(heard);
      setState(heard ? "heard" : "none");
      if (heard) {
        try {
          localStorage.setItem(MIC_OK_KEY, "1");
        } catch {
          /* storage unavailable */
        }
      }
    } catch (e) {
      const msg = (e as Error).message;
      setState((e as Error).name === "NotAllowedError" || msg === "not-allowed" || msg === "service-not-allowed" ? "denied" : "none");
    }
  }

  return (
    <div className="space-y-2 rounded-2xl border-2 border-line p-4" data-testid="mic-check">
      <h2 className="font-display text-lg font-bold">{t("workshop.mic.title")}</h2>
      <p className="text-sm text-muted">{t("workshop.mic.sub")}</p>
      {state === "heard" ? (
        <p role="status" className="flex items-start gap-2 font-semibold text-good">
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0" aria-hidden /> {text ? t("workshop.mic.heard", { text }) : t("workshop.mic.say")}
        </p>
      ) : (
        <Button variant="outline" className="min-h-11 w-full" onClick={() => void check()} disabled={state === "listening" || state === "unsupported"}>
          <Mic className="h-5 w-5" aria-hidden /> {state === "listening" ? t("workshop.mic.listening") : t("workshop.mic.say")}
        </Button>
      )}
      {(state === "none" || state === "denied" || state === "unsupported") && <p role="status" className="text-sm text-muted">{t(`workshop.mic.${state}`)}</p>}
    </div>
  );
}

/** Step 1: tick every prerequisite, check the mic once (optional), then one big "I'm ready, start". */
function Prereqs({ session, sock, lang, onStart }: { session: Session; sock: Sock; lang: Lang; onStart: () => Promise<void> }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [pending, setPending] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [problem, setProblem] = useState("");
  const [help, setHelp] = useState(false);
  const done = session.prerequisites.filter((p) => p.done).length;
  const allDone = done === session.prerequisites.length;

  async function toggle(key: string, value: boolean) {
    setPending(key);
    setProblem("");
    try {
      qc.setQueryData(sessionKey(session.id), await workshops.prereq(session.id, key, value));
    } catch (e) {
      setProblem(t(`workshop.prereq.err.${errorCode(e)}`, { defaultValue: t("mentor.errors.generic") }));
    } finally {
      setPending(null);
    }
  }

  async function start() {
    setStarting(true);
    setProblem("");
    try {
      await onStart();
    } catch (e) {
      setProblem(t(`workshop.prereq.err.${errorCode(e)}`, { defaultValue: t("mentor.errors.generic") }));
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-2xl min-w-0 space-y-5 px-4 py-6 md:py-8">
      <header className="flex items-center gap-4">
        <Kili mood="wave" size={84} />
        <div className="min-w-0">
          <p className="break-words text-sm font-semibold uppercase tracking-wide text-accent">{session.workshop.title}</p>
          <h1 className="break-words font-display text-3xl font-extrabold">{t("workshop.prereq.title")}</h1>
          <p className="text-lg text-muted">{t("workshop.prereq.sub")}</p>
        </div>
      </header>
      <StaffNudges nudges={sock.nudges} onDismiss={sock.dismissNudge} />
      <Card className="space-y-4">
        <p className="text-sm font-semibold text-muted">{t("workshop.prereq.count", { done, total: session.prerequisites.length })}</p>
        <ul className="space-y-3">
          {session.prerequisites.map((p) => (
            <li key={p.key} className={cn("rounded-2xl border-2 p-4 transition", p.done ? "border-good/40 bg-good/5" : "border-line")}>
              <label className="flex min-h-11 cursor-pointer items-start gap-3">
                <input type="checkbox" checked={p.done} disabled={pending === p.key} onChange={(e) => void toggle(p.key, e.target.checked)} className="mt-1.5 h-6 w-6 shrink-0 accent-[var(--accent)]" />
                <span className="min-w-0 break-words text-lg font-semibold">{p.label}</span>
              </label>
              {p.how_to_md && (
                <details className="mt-2 pl-9" open={!p.done}>
                  <summary className="cursor-pointer text-sm font-semibold text-accent">{t("workshop.prereq.how")}</summary>
                  <div className="prose-chat mt-1 text-base"><Md>{p.how_to_md}</Md></div>
                </details>
              )}
            </li>
          ))}
        </ul>
        <MicCheck lang={lang} />
        <ProctorNotice as="h2" mode={session.proctoring} org={session.audience === "org" || !!session.institution_notice} attention={session.institution_sees?.includes("attention")} />
        {problem && <p role="alert" className="text-sm text-bad">{problem}</p>}
        <Button className="min-h-14 w-full py-3 text-xl" disabled={!allDone} loading={starting} onClick={() => void start()}>
          <Play className="h-6 w-6" aria-hidden /> {t("workshop.prereq.start")}
        </Button>
        {!allDone && <p className="text-center text-sm text-muted">{t("workshop.prereq.startHint")}</p>}
      </Card>
      <div>
        <button type="button" aria-expanded={help} onClick={() => setHelp((h) => !h)}
          className="flex min-h-11 w-full items-center justify-center gap-2 rounded-xl font-semibold text-accent hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/40">
          {t("workshop.prereq.stuck")} <ChevronDown className={cn("h-5 w-5 transition", help && "rotate-180")} aria-hidden />
        </button>
        {help && <HelpPanel sessionId={session.id} className="mt-2" />}
      </div>
    </div>
  );
}

export default function WorkshopSessionPage() {
  const { id } = useParams();
  const sid = Number(id);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data: me } = useMe();
  const updatePrefs = useUpdatePreferences();
  const { data: session, error, refetch } = useQuery({ queryKey: sessionKey(sid), queryFn: () => workshops.session(sid), enabled: sid > 0 });
  const setSession = useCallback((s: Session) => qc.setQueryData(sessionKey(sid), s), [qc, sid]);
  const sock = useWorkshopSocket(sid, setSession);
  const replyLang = me?.preferences.mentor.reply_language;
  const lang: Lang = session?.language === "ta" || replyLang === "ta" || replyLang === "tanglish" || (replyLang === "auto" && me?.profile.language === "ta") ? "ta" : "en";
  // Hands-free is a live conversation: answer by just talking, and the host's own voice never counts as an answer.
  const handsFree = me?.preferences.voice?.workshop_mode === "handsfree";
  const mode: VoiceMode = handsFree ? "conversation" : "tap";
  const voice = useVoiceMode({ messages: sock.messages, send: sock.say, cancel: sock.cancel, lang, mode, busy: sock.busy, feature: "workshop", fillers: "think" });
  const stage = session ? currentStage(session) : undefined;
  const started = !!session && session.status !== "prereq" && session.status !== "submitted";
  useProctoring({ mode: session?.proctoring ?? "off", enabled: started && !!stage && !isDiy(stage.kind), send: sock.attention });

  const { stop: stopVoice } = voice;
  useEffect(() => () => stopVoice(), [stopVoice]);

  if (!(sid > 0)) return <PageError notFound />;
  if (error) return <PageError error={error} onRetry={() => void refetch()} />;
  if (!session) return <div className="p-8 text-muted">…</div>;
  if (session.status === "submitted") return <Navigate to={`/workshops/session/${sid}/result`} replace />;

  if (session.status === "prereq") {
    return (
      <Prereqs
        session={session}
        sock={sock}
        lang={lang}
        onStart={async () => {
          // Full screen and audio both need the tap itself, so ask before the request goes out.
          if (session.proctoring === "strict") void document.documentElement.requestFullscreen?.()?.catch(() => {});
          void voice.start(); // the host's voice (tap-to-talk keeps the mic closed until a tap)
          try {
            setSession(await workshops.start(sid));
            void sock.sync(); // the socket opened before Start: ask the host to begin now
          } catch (e) {
            voice.stop();
            if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
            throw e;
          }
        }}
      />
    );
  }
  if (!stage) return <Navigate to={`/workshops/session/${session.id}/result`} replace />;
  return (
    <LiveStage
      session={session}
      sock={sock}
      voice={voice}
      handsFree={handsFree}
      onHandsFree={(v) => updatePrefs.mutate({ voice: { workshop_mode: v ? "handsfree" : "tap" } })}
      onSession={setSession}
      onResult={(r) => {
        void qc.invalidateQueries({ queryKey: sessionKey(session.id) });
        navigate(`/workshops/session/${session.id}/result`, { state: { result: r } });
      }}
    />
  );
}
