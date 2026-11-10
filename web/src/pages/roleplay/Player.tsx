import { useQuery, useQueryClient } from "@tanstack/react-query";
import confetti from "canvas-confetti";
import { CheckCircle2, Flag, Mic, MicOff, RotateCcw, Send, XCircle } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";

import { AnswerFeedback } from "@/components/AnswerFeedback";
import { Md } from "@/components/Md";
import { WebSources } from "@/components/WebSources";
import { PageError } from "@/components/PageState";
import { AvatarStage } from "@/components/roleplay/AvatarStage";
import { CoachReport, LiveCoachBar } from "@/components/roleplay/LiveCoach";
import { useLiveCoach } from "@/components/roleplay/useLiveCoach";
import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { badId } from "@/lib/ids";
import { celebrate, gameKey } from "@/lib/game";
import { roleplay, useRolePlaySocket, type RolePlayResult, type Session } from "@/lib/roleplay";
import type { ChatMsg } from "@/lib/useMentorSocket";
import { useMe } from "@/lib/useMe";
import { Kili } from "@/mascot/Kili";
import { FeedbackSurveyPrompt } from "@/pages/orgs/teach/FeedbackSurveyPrompt";
import { sfx } from "@/mascot/sfx";
import { mascot } from "@/mascot/store";
import { InterruptButton } from "@/voice/InterruptButton";
import { VOICE_ERRORS, useVoiceMode } from "@/voice/useVoiceMode";

function Report({ s, result }: { s: Session; result: RolePlayResult }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const ring = 2 * Math.PI * 52;
  return (
    <div className="mx-auto max-w-3xl space-y-5 px-4 py-8">
      <Card className="flex flex-col items-center gap-4 text-center sm:flex-row sm:text-left">
        <svg viewBox="0 0 120 120" className="h-32 w-32 shrink-0 -rotate-90" role="img" aria-label={`${result.overall}/100`}>
          <circle cx="60" cy="60" r="52" fill="none" stroke="var(--surface-2)" strokeWidth="12" />
          <circle cx="60" cy="60" r="52" fill="none" stroke="var(--accent)" strokeWidth="12" strokeLinecap="round" strokeDasharray={`${(ring * result.overall) / 100} ${ring}`} />
          <text x="60" y="68" textAnchor="middle" transform="rotate(90 60 60)" className="fill-[var(--text)] font-display text-[28px] font-extrabold">{result.overall}</text>
        </svg>
        <div className="space-y-1">
          <p className="text-sm text-muted">{s.scenario.emoji} {s.scenario.title}</p>
          <h1 className="font-display text-2xl font-extrabold">{t("rp.reportTitle")}</h1>
          <p>{result.summary}</p>
        </div>
      </Card>
      <Card className="space-y-4">
        <h2 className="font-display text-xl font-bold">{t("rp.skills")}</h2>
        {result.competencies.map((c) => (
          <div key={c.name} className="space-y-1">
            <div className="flex justify-between text-sm"><b>{c.name}</b><span>{"★".repeat(c.score)}{"☆".repeat(5 - c.score)}</span></div>
            <div className="h-2.5 overflow-hidden rounded-full bg-surface-2"><div className="h-full rounded-full bg-accent" style={{ width: `${c.score * 20}%` }} /></div>
            <p className="text-sm text-muted">{c.comment}</p>
            {c.evidence.map((q) => <p key={q} className="border-l-4 border-accent/50 pl-3 text-sm italic">“{q}”</p>)}
          </div>
        ))}
      </Card>
      <Card className="space-y-2">
        <h2 className="font-display text-xl font-bold">{t("rp.objectives")}</h2>
        {result.objectives.map((o) => (
          <p key={o.text} className="flex items-start gap-2">{o.met ? <CheckCircle2 className="mt-1 h-4 w-4 shrink-0 text-good" /> : <XCircle className="mt-1 h-4 w-4 shrink-0 text-bad" />}{o.text}</p>
        ))}
      </Card>
      <div className="grid gap-4 sm:grid-cols-2">
        <Card><h2 className="mb-2 font-display text-lg font-bold">💪 {t("rp.strengths")}</h2><ul className="list-disc space-y-1 pl-5 text-sm">{result.strengths.map((x) => <li key={x}>{x}</li>)}</ul></Card>
        <Card><h2 className="mb-2 font-display text-lg font-bold">🎯 {t("rp.improve")}</h2><ul className="list-disc space-y-1 pl-5 text-sm">{result.improvements.map((x) => <li key={x}>{x}</li>)}</ul></Card>
      </div>
      {!!result.better_phrasing.length && (
        <Card className="space-y-3">
          <h2 className="font-display text-xl font-bold">🗣️ {t("rp.trySaying")}</h2>
          {result.better_phrasing.map((b) => (
            <div key={b.learner_said} className="grid gap-2 sm:grid-cols-2">
              <p className="rounded-xl bg-surface-2 p-3 text-sm"><span className="text-xs font-semibold text-muted">{t("rp.youSaid")}</span><br />“{b.learner_said}”</p>
              <p className="rounded-xl bg-good/10 p-3 text-sm"><span className="text-xs font-semibold text-good">{t("rp.tryInstead")}</span><br />“{b.try_saying}”</p>
            </div>
          ))}
        </Card>
      )}
      {result.coach && <Card><CoachReport objectives={s.scenario.objectives} coach={result.coach} /></Card>}
      <FeedbackSurveyPrompt survey={s.feedback_survey} />
      <div className="flex flex-wrap gap-2">
        {s.lesson && <Button onClick={() => navigate(s.lesson!.url)}>{t("rp.backToLesson", { title: s.lesson.title })}</Button>}
        <Button variant={s.lesson ? "outline" : "primary"} onClick={async () => navigate(`/roleplay/${(await roleplay.start(s.scenario.id)).id}`)}><RotateCcw className="h-4 w-4" /> {t("rp.again")}</Button>
        <Link to="/roleplay" className="rounded-xl border-2 border-line px-4 py-2.5 font-semibold hover:border-accent">{t("rp.more")}</Link>
      </div>
    </div>
  );
}

export default function RolePlayPlayer() {
  const { t } = useTranslation();
  const { id } = useParams();
  const sid = Number(id);
  const { data: s, error, refetch } = useQuery({ queryKey: ["rp", sid], queryFn: () => roleplay.session(sid), enabled: !badId(sid) });
  if (badId(sid)) return <PageError notFound />;
  if (error && !s) return <PageError error={error} onRetry={() => void refetch()} />;
  if (!s) return <p className="p-8 text-muted">{t("common.loading")}</p>;
  if (s.status === "completed" && s.result) return <Report s={s} result={s.result} />;
  return <Conversation key={sid} s={s} />;
}

function Conversation({ s }: { s: Session }) {
  const { t } = useTranslation();
  const sid = s.id;
  const qc = useQueryClient();
  const { data: me } = useMe();
  const initial = useMemo<ChatMsg[]>(() => (s.turns ?? []).map((x) => ({ id: x.id, role: x.role === "learner" ? "user" : "assistant", content: x.text })), [s.turns]);
  const chat = useRolePlaySocket(sid, initial);
  const voice = useVoiceMode({ messages: chat.messages, send: chat.send, cancel: chat.cancel, lang: s?.language === "ta" || s?.language === "tanglish" ? "ta" : "en", mode: "conversation", busy: chat.busy, feature: "roleplay", fillers: "think" } as never);
  const [text, setText] = useState("");
  const [ending, setEnding] = useState(false);
  const [endError, setEndError] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [chat.messages]);

  const learnerTurns = chat.messages.filter((m) => m.role === "user").length;
  const left = chat.turnsLeft ?? s.scenario.max_turns - learnerTurns;
  const tooShort = learnerTurns < 2; // the server needs 2 learner replies before it can give feedback
  const coach = useLiveCoach(sid, s.coach, learnerTurns, chat.busy);
  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (text.trim() && chat.send(text.trim())) setText("");
  };
  async function end() {
    voice.stop();
    setEnding(true);
    setEndError("");
    mascot.react("thinking", 0);
    try {
      const r = await roleplay.end(sid);
      qc.setQueryData(["rp", sid], { ...s, status: "completed", result: r.result, feedback_survey: r.feedback_survey ?? null });
      celebrate(r.reward, { invalidate: () => void qc.invalidateQueries({ queryKey: gameKey }) });
      if (r.result.overall >= 70) {
        sfx("levelup");
        mascot.react("celebrate");
        if (!me?.preferences.appearance.reduced_motion) void confetti({ particleCount: 120, spread: 80, origin: { y: 0.6 } });
      } else mascot.react("cheer");
    } catch (e) {
      mascot.react("hmm");
      setEndError(e instanceof ApiError && e.data?.code === "too_short" ? t("rp.tooShort") : t("mentor.errors.generic"));
    } finally {
      setEnding(false);
    }
  }

  return (
    <div className="mx-auto flex h-[calc(100dvh-110px)] max-w-3xl flex-col px-4 md:h-[calc(100dvh-56px)]">
      <header className="flex items-center gap-3 py-3">
        <span className="flex h-12 w-12 items-center justify-center rounded-full bg-accent/15 text-2xl">{s.scenario.emoji}</span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-display text-lg font-bold">{s.scenario.character.name}</p>
          <p className="truncate text-xs text-muted">{t("rp.youAre")}: {s.scenario.learner_role}</p>
        </div>
        <span className="rounded-full bg-surface-2 px-3 py-1 text-xs font-semibold">{t("rp.turnsLeft", { count: Math.max(0, left) })}</span>
        <Button variant="outline" className="py-1.5 text-sm" onClick={end} loading={ending} disabled={tooShort || chat.busy}
          title={tooShort ? t("rp.tooShort") : undefined} aria-describedby={tooShort ? "rp-finish-hint" : undefined}><Flag className="h-4 w-4" /> {t("rp.finish")}</Button>
      </header>
      {tooShort && <p id="rp-finish-hint" className="-mt-1 mb-2 text-right text-xs text-muted">{t("rp.tooShort")}</p>}
      <details className="mb-2 rounded-xl bg-surface-2 px-3 py-2 text-sm">
        <summary className="cursor-pointer font-semibold">🎯 {t("rp.yourGoals")}</summary>
        <p className="mt-1 text-muted">{s.scenario.setting}</p>
        <ul className="mt-1 list-disc pl-5">{s.scenario.objectives.map((o) => <li key={o}>{o}</li>)}</ul>
      </details>
      <LiveCoachBar coach={coach} disabled={ending} />
      <AvatarStage scenario={s.scenario} messages={chat.messages} busy={chat.busy} voiceState={voice.state} interim={voice.interim}>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pb-3" aria-live="polite">
        {chat.messages.map((m) => (
          <div key={m.id} className={cn("flex gap-2", m.role === "user" ? "justify-end" : "justify-start")}>
            {m.role === "assistant" && <span className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent/15">{s.scenario.emoji}</span>}
            <div className="max-w-[80%]">
              {m.role === "user" || !m.content ? (
                <p className={cn("whitespace-pre-wrap rounded-2xl px-4 py-2.5", m.role === "user" ? "rounded-br-sm bg-accent text-accent-ink" : "rounded-bl-sm border border-line bg-surface")}>
                  {m.content || "…"}
                </p>
              ) : (
                <div className="prose-chat rounded-2xl rounded-bl-sm border border-line bg-surface px-4 py-2.5"><Md ai>{m.content}</Md></div>
              )}
              {m.role === "assistant" && !m.streaming && <WebSources citations={m.citations} />}
              {m.role === "assistant" && !m.streaming && m.content && <AnswerFeedback kind="roleplay" id={m.id} />}
            </div>
          </div>
        ))}
        {endError && <p role="alert" className="text-center text-sm text-bad">{endError}</p>}
        {voice.error && (
          <p role="alert" className="text-center text-sm text-bad">
            {t(`mentor.voice.errors.${VOICE_ERRORS.includes(voice.error) ? voice.error : "generic"}`)}
          </p>
        )}
        {chat.error === "turn_limit" && <p className="text-center text-sm text-muted">{t("rp.limitReached")}</p>}
        <div ref={endRef} />
      </div>
      </AvatarStage>
      {ending ? (
        <div className="mb-24 flex items-center justify-center gap-3 py-4 md:mb-6"><Kili mood="thinking" size={60} /><p className="text-muted">{t("rp.evaluating")}</p></div>
      ) : (
        <form onSubmit={submit} className="mb-24 flex items-end gap-2 rounded-2xl border-2 border-line bg-surface p-2 focus-within:border-accent md:mb-6 md:mr-32">
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={1} disabled={left <= 0}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
            placeholder={left > 0 ? t("rp.replyAs", { role: s.scenario.learner_role.split(" ").slice(0, 4).join(" ") }) : t("rp.limitReached")}
            aria-label={t("rp.reply")} className="max-h-32 min-h-11 flex-1 resize-none bg-transparent px-2 py-2 outline-none" />
          <InterruptButton voice={voice} busy={chat.busy} className="min-h-11" />
          <button type="button" onClick={() => (voice.active ? voice.stop() : void voice.start())} disabled={!chat.ready || left <= 0}
            className={cn("rounded-xl p-3", voice.active ? "bg-bad text-white" : "border-2 border-line hover:border-accent")} aria-label={voice.active ? t("mentor.voice.stop") : t("mentor.voice.start")} aria-pressed={voice.active}>
            {voice.active ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
          </button>
          <button type="submit" disabled={!text.trim() || !chat.ready || chat.busy || left <= 0} className="rounded-xl bg-accent p-3 text-accent-ink disabled:opacity-50" aria-label={t("mentor.send")}><Send className="h-4 w-4" /></button>
        </form>
      )}
    </div>
  );
}
