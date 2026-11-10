import { CheckCircle2, Maximize2, Mic, MicOff, Send } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { AnswerFeedback } from "@/components/AnswerFeedback";
import { Button } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { roleplay, useRolePlaySocket, type RolePlayResult, type Session } from "@/lib/roleplay";
import type { ChatMsg } from "@/lib/useMentorSocket";
import { mascot } from "@/mascot/store";
import { InterruptButton } from "@/voice/InterruptButton";
import { VOICE_ERRORS, useVoiceMode } from "@/voice/useVoiceMode";

/** A short role-play that runs inside the lesson card; the coach's score comes back in place. */
export function InlineRolePlay({ session, onFinished }: { session: Session; onFinished: (r: RolePlayResult) => void }) {
  const { t } = useTranslation();
  const initial = useMemo<ChatMsg[]>(() => (session.turns ?? []).map((x) => ({ id: x.id, role: x.role === "learner" ? "user" : "assistant", content: x.text })), [session.turns]);
  const chat = useRolePlaySocket(session.id, initial);
  const voice = useVoiceMode({ messages: chat.messages, send: chat.send, cancel: chat.cancel, lang: session.language === "ta" || session.language === "tanglish" ? "ta" : "en", mode: "conversation", busy: chat.busy, feature: "roleplay", fillers: "think" } as never);
  const [text, setText] = useState("");
  const [ending, setEnding] = useState(false);
  const [err, setErr] = useState("");
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    box.current?.scrollTo({ top: box.current.scrollHeight, behavior: "smooth" });
  }, [chat.messages]);
  const learnerTurns = chat.messages.filter((m) => m.role === "user").length;
  const left = chat.turnsLeft ?? session.scenario.max_turns - learnerTurns;

  async function finish() {
    voice.stop();
    setEnding(true);
    setErr("");
    mascot.react("thinking", 0);
    try {
      const r = await roleplay.end(session.id);
      mascot.react(r.result.overall >= 70 ? "celebrate" : "cheer");
      onFinished(r.result);
    } catch (e) {
      mascot.react("hmm");
      setErr(e instanceof ApiError && e.data?.code === "too_short" ? t("rp.tooShort") : t("mentor.errors.generic"));
    } finally {
      setEnding(false);
    }
  }
  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (text.trim() && chat.send(text.trim())) setText("");
  };
  return (
    <div className="space-y-2 rounded-2xl border-2 border-accent/30 p-3">
      <div className="flex items-center gap-2 text-sm">
        <span className="text-xl">{session.scenario.emoji}</span>
        <span className="flex-1 font-semibold">{session.scenario.character.name}</span>
        <span className="text-xs text-muted">{t("act.rp.turnsLeft", { count: Math.max(0, left) })}</span>
        <Link to={`/roleplay/${session.id}`} className="text-muted hover:text-accent" title={t("act.rp.fullScreen")} aria-label={t("act.rp.fullScreen")}><Maximize2 className="h-4 w-4" /></Link>
      </div>
      <div ref={box} className="max-h-72 space-y-2 overflow-y-auto" aria-live="polite">
        {chat.messages.map((m) => (
          <div key={m.id} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
            <div className="max-w-[85%]">
              <p className={cn("whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm", m.role === "user" ? "bg-accent text-accent-ink" : "border border-line bg-surface")}>{m.content || "…"}</p>
              {m.role === "assistant" && !m.streaming && m.content && <AnswerFeedback kind="roleplay" id={m.id} />}
            </div>
          </div>
        ))}
      </div>
      {voice.active && voice.interim && <p className="text-xs italic text-muted">“{voice.interim}”</p>}
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
      {voice.error && (
        <p role="alert" className="text-sm text-bad">
          {t(`mentor.voice.errors.${VOICE_ERRORS.includes(voice.error) ? voice.error : "generic"}`)}
        </p>
      )}
      <form onSubmit={submit} className="flex gap-2">
        <input value={text} onChange={(e) => setText(e.target.value)} disabled={left <= 0} placeholder={t("rp.replyAs", { role: session.scenario.learner_role })}
          aria-label={t("rp.replyAs", { role: session.scenario.learner_role })} className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent" />
        <InterruptButton voice={voice} busy={chat.busy} className="text-sm" />
        <button type="button" onClick={() => (voice.active ? voice.stop() : void voice.start())} aria-pressed={voice.active} aria-label={voice.active ? t("mentor.voice.stop") : t("mentor.voice.start")}
          className={cn("rounded-xl p-2.5", voice.active ? "bg-bad text-white" : "border-2 border-line")}>{voice.active ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}</button>
        <button className="rounded-xl bg-accent p-2.5 text-accent-ink disabled:opacity-50" disabled={!text.trim() || chat.busy} aria-label={t("mentor.send")}><Send className="h-4 w-4" /></button>
      </form>
      <Button variant="outline" className="w-full py-1.5 text-sm" loading={ending} disabled={learnerTurns < 2} onClick={finish}><CheckCircle2 className="h-4 w-4" /> {t("act.rp.finish")}</Button>
    </div>
  );
}
