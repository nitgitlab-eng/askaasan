import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, RotateCcw, Send } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Md } from "@/components/Md";
import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { lx, type TutorState } from "@/lib/lx";
import { Kili } from "@/mascot/Kili";

function errorKey(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 429) return "lx.tutor.budget";
    if (e.data?.code === "feature_off") return "lx.tutor.off";
    if (e.data?.code === "guardian_consent_required") return "guardian.locked";
  }
  return "lx.tutor.error";
}

/** "Learn with <your companion>" (Kili, Mayil, Yaanai or their custom name): the lesson taught in a chat, one idea at a time, with a quick check after each. */
export function TutorChat({ lessonId, lang, onHandOver }: { lessonId: number; lang?: string; onHandOver: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const key = ["lx-tutor", lessonId];
  const { data } = useQuery({ queryKey: key, queryFn: () => lx.tutor(lessonId) });
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const n = data?.messages?.length ?? 0;
  useEffect(() => {
    if (n) endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
  }, [n, busy]);

  const run = async (fn: () => Promise<TutorState>) => {
    setErr("");
    setBusy(true);
    try {
      qc.setQueryData(key, await fn());
      return true;
    } catch (e) {
      setErr(t(errorKey(e)));
      return false;
    } finally {
      setBusy(false);
    }
  };
  const send = async (e: FormEvent) => {
    e.preventDefault();
    const msg = text.trim();
    if (!msg || busy) return;
    if (await run(() => lx.replyTutor(lessonId, msg, lang))) setText("");
  };

  if (!data) return <Card><p className="text-muted">{t("lx.tutor.thinking")}</p></Card>;
  if (data.status === "none") {
    return (
      <Card className="flex flex-col items-center gap-3 text-center">
        <Kili mood="wave" size={110} />
        <p className="max-w-md text-muted">{t("lx.tutor.sub")}</p>
        <Button onClick={() => void run(() => lx.startTutor(lessonId, false, lang))} loading={busy}>{t("lx.tutor.start")}</Button>
        {err && <p role="alert" className="text-sm text-bad">{err}</p>}
      </Card>
    );
  }
  const total = data.total ?? 0;
  const done = data.status === "done";
  const covered = done ? total : (data.current ?? 0);
  return (
    <Card className="space-y-4">
      <div className="space-y-1">
        <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-muted">
          <span>{done ? t("lx.tutor.progress") : t("lx.tutor.idea", { n: Math.min(covered + 1, total), total })}</span>
          <span>{covered}/{total}</span>
        </div>
        <div className="flex gap-1" aria-hidden>
          {(data.chunks ?? []).map((c, i) => (
            <span key={i} title={c.title} className={cn("h-2 flex-1 rounded-full", i < covered ? ((c.mastery ?? 0) >= 0.7 ? "bg-good" : "bg-amber-400") : i === covered ? "bg-accent/50" : "bg-line")} />
          ))}
        </div>
      </div>
      <div className="max-h-[32rem] space-y-3 overflow-y-auto pr-1" aria-live="polite">
        {(data.messages ?? []).map((m, i) => (
          <div key={i} className={cn("flex", m.role === "me" ? "justify-end" : "justify-start")}>
            <div className={cn("max-w-[85%] rounded-2xl px-4 py-2.5", m.role === "me" ? "bg-accent text-accent-ink" : "bg-surface-2")}>
              <p className="sr-only">{t(m.role === "me" ? "lx.tutor.you" : "lx.tutor.kili")}:</p>
              {m.role === "kili" ? <div className="prose-chat"><Md ai>{m.text}</Md></div> : <p className="whitespace-pre-wrap">{m.text}</p>}
              {m.role === "kili" && m.question && <p className="mt-2 font-semibold">❓ {m.question}</p>}
            </div>
          </div>
        ))}
        {busy && <p role="status" className="text-sm text-muted">{t("lx.tutor.thinking")}</p>}
        <div ref={endRef} />
      </div>
      {done ? (
        <div className="space-y-3 rounded-xl bg-good/10 p-3">
          <p className="font-semibold">{t("lx.tutor.done")}</p>
          <div className="flex flex-wrap gap-2">
            <Button onClick={onHandOver}><ArrowDown className="h-4 w-4" /> {t("lx.tutor.toActivities")}</Button>
            <Button variant="outline" onClick={() => void run(() => lx.startTutor(lessonId, true, lang))} loading={busy}><RotateCcw className="h-4 w-4" /> {t("lx.tutor.restart")}</Button>
          </div>
        </div>
      ) : (
        <form onSubmit={send} className="flex gap-2">
          <input value={text} onChange={(e) => setText(e.target.value)} maxLength={1000} placeholder={t("lx.tutor.placeholder")} aria-label={t("lx.tutor.placeholder")}
            className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2 outline-none focus:border-accent" disabled={busy} />
          <Button type="submit" loading={busy} disabled={!text.trim()} aria-label={t("lx.tutor.send")}><Send className="h-4 w-4" /></Button>
        </form>
      )}
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
    </Card>
  );
}
