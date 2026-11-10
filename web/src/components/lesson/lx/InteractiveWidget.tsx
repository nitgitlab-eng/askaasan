import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ShieldCheck, Sparkles, XCircle } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card, Segmented } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { lx, type LessonWidget } from "@/lib/lx";

import { useLessonWidget } from "./useLessonWidget";
import { isWidgetFrameUrl, readWidgetAnswer, WIDGET_SANDBOX } from "./widgetFrame";

/** The sandboxed widget itself + its optional checkpoint (answer checked on the server). */
export function WidgetFrame({ lessonId, widget }: { lessonId: number; widget: LessonWidget }) {
  const { t } = useTranslation();
  const ref = useRef<HTMLIFrameElement>(null);
  const [verdict, setVerdict] = useState<boolean | null>(null);
  const busy = useRef(false);
  const src = isWidgetFrameUrl(widget.frame_url) ? widget.frame_url : undefined;

  useEffect(() => {
    if (!widget.has_checkpoint) return;
    const onMessage = async (e: MessageEvent) => {
      const answer = readWidgetAnswer(e, ref.current?.contentWindow);
      if (answer === null || busy.current) return;
      busy.current = true;
      try {
        setVerdict((await lx.checkWidget(lessonId, answer)).correct);
      } catch {
        setVerdict(null);
      } finally {
        busy.current = false;
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [lessonId, widget.has_checkpoint]);

  return (
    <div className="space-y-2">
      {widget.has_checkpoint && widget.checkpoint_question && (
        <p className="rounded-xl bg-accent/10 px-3 py-2 text-sm"><span className="font-semibold">{t("lx.widget.checkpoint")}:</span> {widget.checkpoint_question}</p>
      )}
      <iframe
        ref={ref}
        title={t("lx.widget.frameTitle", { title: widget.title ?? "" })}
        sandbox={WIDGET_SANDBOX}
        src={src}
        referrerPolicy="no-referrer"
        loading="lazy"
        className="h-[26rem] w-full rounded-xl border-2 border-line bg-white"
      />
      {verdict !== null && (
        <p role="status" className={verdict ? "flex items-center gap-1.5 font-semibold text-good" : "flex items-center gap-1.5 font-semibold text-bad"}>
          {verdict ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />} {t(verdict ? "lx.widget.correct" : "lx.widget.wrong")}
        </p>
      )}
      <p className="flex items-center gap-1 text-xs text-muted"><ShieldCheck className="h-3.5 w-3.5" /> {t("lx.widget.sandbox")}</p>
    </div>
  );
}

function AuthorControls({ lessonId, widget }: { lessonId: number; widget: LessonWidget }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [instr, setInstr] = useState(widget.instructions ?? "");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const make = async () => {
    setErr("");
    setBusy(true);
    try {
      qc.setQueryData(["lx-widget", lessonId], await lx.makeWidget(lessonId, instr.trim()));
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 429 ? t("lx.widget.budget") : t("mentor.errors.generic"));
    } finally {
      setBusy(false);
    }
  };
  if (widget.status === "generating") return <p role="status" className="text-sm text-muted">{t("lx.widget.making")}</p>;
  return (
    <div className="space-y-2 rounded-xl border-2 border-dashed border-accent/40 p-3">
      <p className="text-sm text-muted">{t("lx.widget.authorHint")}</p>
      {widget.status === "failed" && <p role="alert" className="text-sm text-bad">{t("lx.widget.failed")}</p>}
      <div className="flex flex-wrap gap-2">
        <input value={instr} onChange={(e) => setInstr(e.target.value)} maxLength={500} placeholder={t("lx.widget.instructionsPh")} aria-label={t("lx.widget.instructionsPh")}
          className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2" />
        <Button variant="outline" onClick={make} loading={busy}><Sparkles className="h-4 w-4" /> {t(widget.status === "ready" ? "lx.widget.regenerate" : "lx.widget.make")}</Button>
      </div>
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
    </div>
  );
}

/**
 * The lesson's explanation with an "Interactive" tab next to it. Learners only see the tab once a
 * widget is ready; course owners always see it (to create or regenerate the widget).
 */
export function LessonTabs({ lessonId, children }: { lessonId: number; children: ReactNode }) {
  const { t } = useTranslation();
  const { data: w } = useLessonWidget(lessonId);
  const [tab, setTab] = useState<"explanation" | "interactive">("explanation");
  const show = !!w && (w.status === "ready" || w.can_edit);
  if (!show) return <>{children}</>;
  return (
    <div className="space-y-3">
      <Segmented value={tab} onChange={setTab} label={t("lx.widget.tabs")}
        options={[{ value: "explanation", label: t("lx.widget.tabExplanation") }, { value: "interactive", label: `✨ ${t("lx.widget.tabInteractive")}` }]} />
      {tab === "explanation" ? children : (
        <Card className="space-y-3">
          {w.status === "ready" && w.frame_url ? <WidgetFrame key={w.frame_url} lessonId={lessonId} widget={w} /> : !w.can_edit && <p className="text-muted">{t("lx.widget.none")}</p>}
          {w.can_edit && <AuthorControls lessonId={lessonId} widget={w} />}
        </Card>
      )}
    </div>
  );
}
