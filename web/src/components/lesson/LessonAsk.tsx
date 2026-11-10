import { ExternalLink, Send, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Md } from "@/components/Md";
import { WebSources } from "@/components/WebSources";
import { Button, Card } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useMentorSocket } from "@/lib/useMentorSocket";

/** "Ask Aasan about this", answered right inside the lesson so the learner doesn't lose their place. */
export function LessonAsk({ question, onClose }: { question: string; onClose: () => void }) {
  const { t } = useTranslation();
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [text, setText] = useState("");
  const asked = useRef(false);
  const chat = useMentorSocket({ conversationId, onConversation: setConversationId });

  useEffect(() => {
    if (chat.status === "ready" && !asked.current && chat.send(question)) asked.current = true;
  }, [chat, question]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim() && chat.send(text.trim())) setText("");
  };
  const errorText = chat.error ? t(`mentor.errors.${["rate_limited", "provider_not_configured", "plan_limit"].includes(chat.error) ? chat.error : "generic"}`) : null;

  return (
    <Card className="mt-4 space-y-3 border-2 border-accent/40" role="region" aria-label={t("lesson.ask")}>
      <div className="flex items-center justify-between gap-2">
        <p className="font-semibold">{t("lesson.ask")}</p>
        <div className="flex items-center gap-1">
          {conversationId && (
            <Link to={`/mentor/${conversationId}`} className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold text-accent hover:bg-surface-2">
              <ExternalLink className="h-3.5 w-3.5" /> {t("lesson.askOpenFull")}
            </Link>
          )}
          <button onClick={onClose} aria-label={t("common.close")} className="rounded-lg p-1 text-muted hover:bg-surface-2"><X className="h-4 w-4" /></button>
        </div>
      </div>
      <div className="max-h-96 space-y-2 overflow-y-auto" aria-live="polite">
        {chat.messages.map((m) => (
          <div key={m.id} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
            <div className={cn("max-w-[85%] rounded-2xl px-3 py-2 text-sm", m.role === "user" ? "bg-accent text-accent-ink" : "bg-surface-2")}>
              {m.role === "assistant" ? (m.content ? <><div className="prose-chat"><Md ai>{m.content}</Md></div>{!m.streaming && <WebSources citations={m.citations} />}</> : (chat.activity === "searching" ? <span className="text-muted">{t("mentor.web.searching")}</span> : "…")) : <p className="whitespace-pre-wrap">{m.content}</p>}
            </div>
          </div>
        ))}
        {!chat.messages.length && <p role="status" className="text-sm text-muted">{t("common.loading")}</p>}
        {errorText && <p role="alert" className="text-sm text-bad">{errorText}</p>}
      </div>
      <form onSubmit={submit} className="flex gap-2">
        <input value={text} onChange={(e) => setText(e.target.value)} maxLength={2000} placeholder={t("mentor.placeholder")} aria-label={t("mentor.placeholder")}
          className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent" />
        <Button type="submit" disabled={!text.trim() || chat.busy || chat.status !== "ready"} aria-label={t("mentor.send")}><Send className="h-4 w-4" /></Button>
      </form>
    </Card>
  );
}
