import { useQuery } from "@tanstack/react-query";
import { Check, FileText, Send, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { confirmDialog } from "@/lib/dialog";
import { Button } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { orgs, type ChatChange, type SurveyDraftBody } from "@/lib/orgs";
import { applyChange, type Draft } from "@/lib/surveyChat";

type Pending = ChatChange & { state: "pending" | "accepted" | "rejected" };
interface Msg { role: "user" | "assistant"; content: string; changes?: Pending[] }

const input = "w-full rounded-lg border-2 border-line bg-surface px-2 py-1.5 text-sm outline-none focus:border-accent";

/** Multi-turn "write it with Kili": the manager chats, Kili proposes edits, each edit is applied to the draft only when
 *  the manager accepts it (nothing is saved until they press Save). Also: draft a survey/test from a document. */
export function SurveyChat({ slug, draft, kind, update, replace }: {
  slug: string;
  draft: Draft;
  kind: "survey" | "test";
  update: (fn: (d: Draft) => Draft) => void;
  replace: (d: SurveyDraftBody) => void;
}) {
  const { t } = useTranslation();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<"" | "chat" | "doc">("");
  const [err, setErr] = useState("");
  const [showDoc, setShowDoc] = useState(false);
  const [doc, setDoc] = useState<number | "">("");
  const [focus, setFocus] = useState("");
  const docs = useQuery({ queryKey: ["survey-ai-docs", slug], queryFn: () => orgs.aiDocs(slug), enabled: showDoc });

  const fail = (e: unknown) => setErr(e instanceof ApiError && e.status === 429 ? t("paths.budget") : t("mentor.errors.generic"));

  async function send() {
    const content = text.trim();
    if (content.length < 2) return;
    const next: Msg[] = [...msgs, { role: "user", content }];
    setMsgs(next);
    setText("");
    setBusy("chat");
    setErr("");
    try {
      const r = await orgs.aiChat(slug, next.map(({ role, content: c }) => ({ role, content: c })), { ...draft, kind });
      setMsgs([...next, { role: "assistant", content: r.reply, changes: r.changes.map((c) => ({ ...c, state: "pending" as const })) }]);
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  }

  function decide(mi: number, ids: string[], accept: boolean) {
    const m = msgs[mi];
    const chosen = (m.changes ?? []).filter((c) => ids.includes(c.id) && c.state === "pending");
    if (accept) update((d) => chosen.reduce(applyChange, d));
    setMsgs(msgs.map((x, i) => (i !== mi ? x : { ...x, changes: x.changes?.map((c) => (chosen.some((k) => k.id === c.id) ? { ...c, state: accept ? "accepted" : "rejected" } : c)) })));
  }

  async function fromDoc() {
    if (doc === "") return;
    if (draft.questions.some((q) => q.text.trim()) && !(await confirmDialog(t("credSurvey.doc.replaceConfirm")))) return;
    setBusy("doc");
    setErr("");
    try {
      replace(await orgs.aiFromDoc(slug, doc, kind, focus));
      setShowDoc(false);
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-2 rounded-xl bg-accent/5 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 font-semibold"><Sparkles className="h-4 w-4 text-accent" /> {t("credSurvey.chat.title")}</p>
        <button type="button" className="flex items-center gap-1 text-sm font-semibold text-accent" onClick={() => setShowDoc(!showDoc)}>
          <FileText className="h-4 w-4" /> {t("credSurvey.doc.title")}
        </button>
      </div>
      {showDoc && (
        <div className="space-y-2 rounded-lg border-2 border-dashed border-accent/40 p-2">
          {docs.data && !docs.data.length ? <p className="text-sm text-muted">{t("credSurvey.doc.none")}</p> : (
            <>
              <select value={doc} onChange={(e) => setDoc(e.target.value ? Number(e.target.value) : "")} aria-label={t("credSurvey.doc.pick")} className={input}>
                <option value="">{t("credSurvey.doc.pick")}</option>
                {docs.data?.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
              </select>
              <input value={focus} onChange={(e) => setFocus(e.target.value)} maxLength={300} placeholder={t("credSurvey.doc.focus")} aria-label={t("credSurvey.doc.focus")} className={input} />
              <Button variant="outline" className="py-1.5 text-sm" loading={busy === "doc"} disabled={doc === ""} onClick={() => void fromDoc()}>
                <Sparkles className="h-4 w-4" /> {kind === "test" ? t("credSurvey.doc.makeTest") : t("credSurvey.doc.makeSurvey")}
              </Button>
            </>
          )}
        </div>
      )}
      {!msgs.length && <p className="text-xs text-muted">{t("credSurvey.chat.hint")}</p>}
      <div className="max-h-96 space-y-2 overflow-y-auto" aria-live="polite">
        {msgs.map((m, mi) => (
          <div key={mi} className={cn("rounded-lg px-3 py-2 text-sm", m.role === "user" ? "ml-8 bg-surface-2" : "mr-8 border border-line bg-surface")}>
            <p className="mb-0.5 text-xs font-semibold text-muted">{m.role === "user" ? t("credSurvey.chat.you") : t("credSurvey.chat.kili")}</p>
            <p className="whitespace-pre-wrap">{m.content}</p>
            {m.role === "assistant" && m.changes && (
              m.changes.length === 0 ? <p className="mt-1 text-xs text-muted">{t("credSurvey.chat.noChanges")}</p> : (
                <ul className="mt-2 space-y-1">
                  {m.changes.map((c) => (
                    <li key={c.id} className={cn("flex flex-wrap items-center gap-2 rounded-lg border px-2 py-1", c.state === "accepted" ? "border-good/50 bg-good/5" : c.state === "rejected" ? "border-line opacity-60" : "border-line")}>
                      <span className="rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold">{t(`credSurvey.op.${c.op}`)}</span>
                      <span className="min-w-0 flex-1">{c.summary}{c.question && <span className="block text-xs text-muted">{c.question.section ? `${c.question.section} · ` : ""}{c.question.text}</span>}</span>
                      {c.state === "pending" ? (
                        <span className="flex gap-1">
                          <button type="button" onClick={() => decide(mi, [c.id], true)} className="flex items-center gap-0.5 rounded-lg bg-accent px-2 py-0.5 text-xs font-semibold text-accent-ink"><Check className="h-3.5 w-3.5" /> {t("credSurvey.chat.accept")}</button>
                          <button type="button" onClick={() => decide(mi, [c.id], false)} className="flex items-center gap-0.5 rounded-lg border border-line px-2 py-0.5 text-xs"><X className="h-3.5 w-3.5" /> {t("credSurvey.chat.reject")}</button>
                        </span>
                      ) : <span className="text-xs text-muted">{c.state === "accepted" ? t("credSurvey.chat.accepted") : t("credSurvey.chat.rejected")}</span>}
                    </li>
                  ))}
                  {m.changes.filter((c) => c.state === "pending").length > 1 && (
                    <li><button type="button" className="text-xs font-semibold text-accent" onClick={() => decide(mi, m.changes!.map((c) => c.id), true)}>{t("credSurvey.chat.acceptAll")}</button></li>
                  )}
                </ul>
              )
            )}
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} maxLength={1500} placeholder={t("credSurvey.chat.ph")} aria-label={t("credSurvey.chat.ph")}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }} className={cn(input, "min-w-0 flex-1")} />
        <Button className="self-end py-1.5 text-sm" loading={busy === "chat"} disabled={text.trim().length < 2} onClick={() => void send()} aria-label={t("credSurvey.chat.send")}><Send className="h-4 w-4" /></Button>
      </div>
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
    </div>
  );
}
