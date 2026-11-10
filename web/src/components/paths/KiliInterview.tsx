import { Send } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { cn } from "@/lib/cn";
import { paths, type OnboardProfile } from "@/lib/paths";
import { mascot } from "@/mascot/store";

type Msg = { role: "user" | "assistant"; content: string };

/** Smart onboarding: Kili asks a few friendly questions and fills in the learner's profile. */
export function KiliInterview({ onDone }: { onDone: (p: OnboardProfile) => void }) {
  const { t } = useTranslation();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [profile, setProfile] = useState<OnboardProfile | null>(null);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState("");
  const box = useRef<HTMLDivElement>(null);
  const started = useRef(false);

  async function turn(history: Msg[]) {
    setBusy(true);
    setErr("");
    mascot.react("thinking", 0);
    try {
      const r = await paths.interview(history);
      setMsgs([...history, { role: "assistant", content: r.reply }]);
      setProfile(r.profile);
      setDone(r.done);
      mascot.react("talking", 1500);
    } catch {
      setErr(t("mentor.errors.generic"));
      mascot.react("hmm");
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void turn([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    box.current?.scrollTo({ top: box.current.scrollHeight, behavior: "smooth" });
  }, [msgs]);
  const send = (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim() || busy) return;
    const h = [...msgs, { role: "user" as const, content: text.trim() }];
    setMsgs(h);
    setText("");
    void turn(h);
  };
  return (
    <div className="space-y-3">
      <div ref={box} className="max-h-72 space-y-2 overflow-y-auto" aria-live="polite">
        {msgs.map((m, i) => (
          <p key={i} className={cn("w-fit max-w-[90%] rounded-2xl px-3 py-2 text-sm", m.role === "user" ? "ml-auto bg-accent text-accent-ink" : "border border-line bg-surface")}>{m.content}</p>
        ))}
        {busy && <p className="text-sm text-muted">{t("mentor.thinking")}</p>}
      </div>
      {err && <p className="text-sm text-bad">{err}</p>}
      {!done && (
        <form onSubmit={send} className="flex gap-2">
          <input value={text} onChange={(e) => setText(e.target.value)} disabled={busy} placeholder={t("paths.interviewPh")} aria-label={t("paths.interviewPh")}
            className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2 outline-none focus:border-accent" />
          <button className="rounded-xl bg-accent p-2.5 text-accent-ink disabled:opacity-50" disabled={!text.trim() || busy} aria-label={t("mentor.send")}><Send className="h-4 w-4" /></button>
        </form>
      )}
      {profile && (done || msgs.filter((m) => m.role === "user").length >= 2) && (
        <Button className="w-full" onClick={() => onDone(profile)}>{done ? t("paths.interviewDone") : t("paths.interviewEnough")}</Button>
      )}
    </div>
  );
}
