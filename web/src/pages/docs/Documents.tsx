import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Loader2, Send, Sparkles, Trash2, Upload } from "lucide-react";
import { useRef, useState, type DragEvent, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import Markdown from "react-markdown";
import { Link, useNavigate, useParams } from "react-router-dom";
import remarkGfm from "remark-gfm";

import { ClickToLoadImg } from "@/components/ClickToLoadImg";
import { Button, Card } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { orgs } from "@/lib/orgs";
import { AnswerFeedback } from "@/components/AnswerFeedback";
import { cn } from "@/lib/cn";
import { createCourse } from "@/lib/learn";
import { isWebSource, type DocCitation } from "@/lib/citations";
import { useMentorSocket } from "@/lib/useMentorSocket";
import { WebSources } from "@/components/WebSources";
import { useAuth } from "@/stores/auth";
import { Kili } from "@/mascot/Kili";
import { mascot } from "@/mascot/store";

interface Doc {
  id: number;
  title: string;
  filename: string;
  kind: string;
  pages: number;
  chars: number;
}

async function uploadFile(file: File): Promise<Doc> {
  const form = new FormData();
  form.append("file", file);
  const send = () => fetch("/api/docs/", { method: "POST", body: form, headers: { Authorization: `Bearer ${useAuth.getState().access}` } });
  let res = await send();
  if (res.status === 401) {
    await api("/api/users/me/").catch(() => {});
    res = await send();
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

function DocChat({ doc }: { doc: Doc }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [convId, setConvId] = useState<number | null>(null);
  const [text, setText] = useState("");
  const [open, setOpen] = useState<DocCitation | null>(null);
  const [building, setBuilding] = useState(false);
  const chat = useMentorSocket({ conversationId: convId, onConversation: setConvId, documentId: doc.id });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim() && chat.send(text.trim())) setText("");
  };
  async function buildCourse() {
    setBuilding(true);
    try {
      const c = await createCourse({ goal: t("docs.courseGoal", { title: doc.title }), level: "beginner", document_id: doc.id });
      mascot.react("thinking", 0);
      navigate(`/learn/${c.id}`);
    } finally {
      setBuilding(false);
    }
  }
  // Render [n] markers as clickable source chips.
  const withChips = (content: string) => content.replace(/\[(\d{1,2})\]/g, "[`$1`](#src-$1)");

  return (
    <Card className="flex min-h-[60vh] flex-col gap-3">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="font-display text-xl font-bold">{doc.title}</h2>
          <p className="text-xs text-muted">{doc.kind.toUpperCase()} · {doc.pages ? t("docs.pages", { count: doc.pages }) : t("docs.chars", { n: doc.chars.toLocaleString() })}</p>
        </div>
        <Button onClick={buildCourse} loading={building}><Sparkles className="h-4 w-4" /> {t("docs.buildCourse")}</Button>
      </header>
      <div className="flex-1 space-y-3 overflow-y-auto" aria-live="polite">
        {chat.messages.length === 0 && (
          <div className="flex flex-col items-center gap-2 py-8 text-center text-muted">
            <Kili mood="watching" size={90} />
            <p>{t("docs.askHint")}</p>
          </div>
        )}
        {chat.messages.map((m) => {
          const cites = (m.citations ?? []).filter((c): c is DocCitation => !isWebSource(c));
          return (
          <div key={m.id} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
            <div className={cn("max-w-[88%] rounded-2xl px-4 py-2.5", m.role === "user" ? "bg-accent text-accent-ink" : "border border-line bg-surface")}>
              {m.role === "assistant" ? (
                <>
                  <div className="prose-chat">
                    <Markdown remarkPlugins={[remarkGfm]} components={{
                      img: ClickToLoadImg, // AI reply over (possibly org-shared) documents: no auto-loading external images
                      a: ({ href, children }) => {
                        const n = Number(href?.replace("#src-", ""));
                        const c = cites.find((x) => x.n === n);
                        return c ? <button onClick={() => setOpen(c)} className="mx-0.5 rounded bg-accent/15 px-1.5 text-xs font-bold text-accent">{n}</button> : <>{children}</>;
                      },
                    }}>{m.content ? withChips(m.content) : t(chat.activity === "searching" ? "mentor.web.searching" : "mentor.thinking")}</Markdown>
                  </div>
                  {!m.streaming && m.content && <AnswerFeedback kind="message" id={m.id} initial={m.my_rating} />}
                  {!!cites.length && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {cites.map((c) => (
                        <button key={c.n} onClick={() => setOpen(c)} className="rounded-full border border-line px-2 py-0.5 text-xs hover:border-accent">
                          [{c.n}] {c.page ? t("docs.page", { n: c.page }) : t("docs.source")}
                        </button>
                      ))}
                    </div>
                  )}
                  <WebSources citations={m.citations} />
                </>
              ) : <p className="whitespace-pre-wrap">{m.content}</p>}
            </div>
          </div>
          );
        })}
      </div>
      {open && (
        <div className="rounded-xl border-l-4 border-accent bg-surface-2 p-3 text-sm">
          <p className="mb-1 font-semibold">[{open.n}] {open.page ? t("docs.page", { n: open.page }) : t("docs.source")} <button onClick={() => setOpen(null)} className="float-right text-muted">✕</button></p>
          <p className="whitespace-pre-wrap">{open.snippet}…</p>
        </div>
      )}
      <form onSubmit={submit} className="flex gap-2">
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder={t("docs.askPlaceholder")} aria-label={t("docs.askPlaceholder")}
          className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2.5 outline-none focus:border-accent" />
        <button disabled={!text.trim() || chat.status !== "ready" || chat.busy} className="rounded-xl bg-accent px-4 text-accent-ink disabled:opacity-50" aria-label={t("mentor.send")}>
          {chat.busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}
        </button>
      </form>
    </Card>
  );
}

export default function DocumentsPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState("");
  const { data: docs } = useQuery({ queryKey: ["docs"], queryFn: () => api<Doc[]>("/api/docs/") });
  const upload = useMutation({
    mutationFn: uploadFile,
    onSuccess: (d) => {
      setError("");
      mascot.react("cheer");
      void qc.invalidateQueries({ queryKey: ["docs"] });
      navigate(`/documents/${d.id}`);
    },
    onError: (e) => {
      mascot.react("hmm");
      const code = e instanceof ApiError ? (e.data?.code as string) : "";
      setError(t(`docs.errors.${code}`, { defaultValue: t("mentor.errors.generic") }));
    },
  });
  const remove = useMutation({
    mutationFn: (docId: number) => api(`/api/docs/${docId}/`, { method: "DELETE" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["docs"] });
      navigate("/documents");
    },
  });
  const { data: shared } = useQuery({ queryKey: ["shared-docs"], queryFn: orgs.sharedWithMe });
  const sharedDocs = (shared ?? []).filter((s) => !docs?.some((d) => d.id === s.document_id))
    .map((s) => ({ id: s.document_id, title: s.title, pages: s.pages, org: s.org }) as unknown as Doc & { org: string });
  const current = docs?.find((d) => d.id === Number(id)) ?? sharedDocs.find((d) => d.id === Number(id));
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer.files[0];
    if (f) upload.mutate(f);
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("docs.title")}</h1>
        <p className="text-muted">{t("docs.sub")}</p>
      </header>
      <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
        <div className="space-y-3">
          <div
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={onDrop}
            className={cn("flex flex-col items-center gap-2 rounded-2xl border-2 border-dashed p-5 text-center transition", drag ? "border-accent bg-accent/10" : "border-line bg-surface")}
          >
            {upload.isPending ? <Loader2 className="h-8 w-8 animate-spin text-accent" /> : <Upload className="h-8 w-8 text-accent" />}
            <p className="text-sm">{t("docs.drop")}</p>
            <Button variant="outline" onClick={() => input.current?.click()} disabled={upload.isPending} className="py-1.5 text-sm">{t("docs.choose")}</Button>
            <input ref={input} type="file" hidden accept=".pdf,.docx,.txt,.md" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
            <p className="text-xs text-muted">{t("docs.limits")}</p>
          </div>
          {error && <p role="alert" className="text-sm text-bad">{error}</p>}
          <ul className="space-y-1">
            {docs?.map((d) => (
              <li key={d.id} className={cn("group flex items-center gap-2 rounded-xl px-3 py-2", d.id === Number(id) ? "bg-accent/15" : "hover:bg-surface-2")}>
                <FileText className="h-4 w-4 shrink-0 text-accent" />
                <Link to={`/documents/${d.id}`} className="min-w-0 flex-1 truncate font-medium">{d.title}</Link>
                <button onClick={() => remove.mutate(d.id)} aria-label={t("docs.delete")} className="opacity-0 transition group-hover:opacity-100"><Trash2 className="h-4 w-4 text-muted hover:text-bad" /></button>
              </li>
            ))}
          </ul>
          {!!sharedDocs.length && (
            <div className="space-y-1">
              <p className="px-1 text-xs font-semibold uppercase tracking-wide text-muted">{t("orgx.sharedWithYou")}</p>
              <ul className="space-y-1">
                {sharedDocs.map((d) => (
                  <li key={d.id} className={cn("flex items-center gap-2 rounded-xl px-3 py-2", d.id === Number(id) ? "bg-accent/15" : "hover:bg-surface-2")}>
                    <FileText className="h-4 w-4 shrink-0 text-accent" />
                    <Link to={`/documents/${d.id}`} className="min-w-0 flex-1 truncate font-medium">{d.title}</Link>
                    <span className="truncate text-[10px] text-muted">{d.org}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        {current ? <DocChat key={current.id} doc={current} /> : (
          <Card className="flex flex-col items-center justify-center gap-3 py-16 text-center text-muted">
            <Kili mood="wave" size={120} />
            <p>{docs?.length ? t("docs.pick") : t("docs.empty")}</p>
          </Card>
        )}
      </div>
    </div>
  );
}
