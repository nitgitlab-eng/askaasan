import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle, Hand, Send, X } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { cn } from "@/lib/cn";
import { NUDGE_MAX, orgWorkshops, pctText, type Tile } from "@/lib/orgWorkshops";
import { useRunTime } from "@/lib/workshops";

import { StatusPill } from "./MonitorGrid";
import { useDialogFocus } from "./useDialogFocus";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-bold uppercase tracking-wide text-muted">{title}</h3>
      {children}
    </section>
  );
}

/**
 * One learner's drill-down beside the grid: a nudge box, "acknowledge hand", and the timeline from the REST endpoint.
 * Names, answers, help summaries, nudges and the transcript are learner or AI text: shown as plain text, never HTML.
 */
export function LearnerDrawer({ slug, runId, tile, onClose, nudge, ackHand }: {
  slug: string; runId: number; tile: Tile; onClose: () => void;
  nudge: (sessionId: number, text: string) => boolean; ackHand: (sessionId: number) => boolean;
}) {
  const { t } = useTranslation();
  const when = useRunTime();
  const [text, setText] = useState("");
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const { data, error } = useQuery({ queryKey: ["org-ws-learner", runId, tile.session_id], queryFn: () => orgWorkshops.learner(slug, runId, tile.session_id) });

  const panel = useRef<HTMLDivElement>(null);
  useDialogFocus(panel, onClose);

  function send() {
    const msg = text.trim();
    if (!msg) return;
    if (nudge(tile.session_id, msg)) {
      setText("");
      setNote({ ok: true, text: t("orgWs.drawer.sent") });
    } else setNote({ ok: false, text: t("orgWs.drawer.offline") });
  }
  function ack() {
    setNote(ackHand(tile.session_id) ? { ok: true, text: t("orgWs.drawer.acked") } : { ok: false, text: t("orgWs.drawer.offline") });
  }

  const time = (iso?: string | null) => (iso ? when.time(iso) : "");
  const help = data?.help ?? (tile.help_summaries ?? []).map((summary) => ({ summary, at: undefined }));

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={onClose}>
      <div ref={panel} role="dialog" aria-modal="true" aria-label={tile.learner.name} className="flex h-full w-full max-w-xl flex-col bg-bg shadow-xl" onClick={(e) => e.stopPropagation()}>
        <header className="flex items-start gap-2 border-b border-line p-4">
          <div className="min-w-0 flex-1">
            <p className="break-words font-display text-xl font-bold">{tile.learner.name}</p>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
              <StatusPill status={tile.status} />
              {tile.learner.roll_no && <span>{tile.learner.roll_no}</span>}
              {tile.stage && <span>{t("orgWs.tile.stage", { n: tile.stage.index + 1, title: tile.stage.title })}</span>}
              <span>{t("orgWs.tile.score")}: {pctText(tile.final_score ?? tile.score_so_far)}</span>
            </div>
          </div>
          <Button variant="ghost" className="px-2.5" onClick={onClose} aria-label={t("common.close")}><X className="h-5 w-5" aria-hidden /></Button>
        </header>

        <div className="flex-1 space-y-5 overflow-y-auto p-4">
          <div className="space-y-3 rounded-2xl border border-line bg-surface p-3">
            {tile.raised_hand && (
              <div className="flex flex-wrap items-center gap-2 rounded-xl bg-bad/10 p-2.5">
                <Hand className="h-5 w-5 text-bad" aria-hidden />
                <span className="flex-1 text-sm font-semibold">{t("orgWs.drawer.handUp")}</span>
                <Button className="py-1.5 text-sm" onClick={ack}>{t("orgWs.drawer.ack")}</Button>
              </div>
            )}
            <label htmlFor="nudge-text" className="block text-sm font-semibold">{t("orgWs.drawer.nudge")}</label>
            <textarea id="nudge-text" value={text} maxLength={NUDGE_MAX} rows={3} onChange={(e) => setText(e.target.value)} placeholder={t("orgWs.drawer.nudgePh")}
              className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2 outline-none focus:border-accent" />
            <div className="flex flex-wrap items-center gap-2">
              <Button className="py-2" disabled={!text.trim()} onClick={send}><Send className="h-4 w-4" aria-hidden /> {t("orgWs.drawer.send")}</Button>
              <span className="text-xs tabular-nums text-muted">{text.length} / {NUDGE_MAX}</span>
              {note && <span role={note.ok ? "status" : "alert"} className={cn("text-sm", note.ok ? "text-good" : "text-bad")}>{note.text}</span>}
            </div>
            <p className="text-xs text-muted">{t("orgWs.drawer.nudgeHint")}</p>
          </div>

          {error ? <p role="alert" className="text-sm text-bad">{t("orgWs.drawer.loadFailed")}</p> : !data ? <p className="text-sm text-muted">{t("common.loading")}</p> : (
            <>
              {!!data.stages?.length && (
                <Section title={t("orgWs.drawer.stages")}>
                  <ol className="space-y-1.5">
                    {data.stages.map((s) => (
                      <li key={s.index} className="flex items-center gap-2 text-sm">
                        {s.status === "done" ? <CheckCircle2 className="h-4 w-4 shrink-0 text-good" aria-hidden /> : <Circle className="h-4 w-4 shrink-0 text-muted" aria-hidden />}
                        <span className="min-w-0 flex-1 break-words">{s.index + 1}. {s.title}</span>
                        {s.minutes != null && <span className="text-xs text-muted">{t("workshop.list.minutes", { count: Math.round(s.minutes) })}</span>}
                        {s.score != null && <span className="text-xs font-semibold tabular-nums">{pctText(s.score)}</span>}
                      </li>
                    ))}
                  </ol>
                </Section>
              )}
              {!!data.answers?.length && (
                <Section title={t("orgWs.drawer.answers")}>
                  <ul className="space-y-2">
                    {data.answers.map((a, i) => (
                      <li key={i} className="rounded-xl bg-surface-2 p-2.5 text-sm">
                        <p className="break-words font-semibold">{a.question}</p>
                        <p className="whitespace-pre-wrap break-words">{a.answer}</p>
                        <p className="text-xs text-muted">{[a.stage, a.score != null ? pctText(a.score) : "", time(a.at)].filter(Boolean).join(" · ")}</p>
                      </li>
                    ))}
                  </ul>
                </Section>
              )}
              {!!data.diy_steps?.length && (
                <Section title={t("orgWs.drawer.steps")}>
                  <ul className="space-y-1.5">
                    {data.diy_steps.map((s, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm">
                        {s.done ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-good" aria-label={t("workshop.done")} /> : <Circle className="mt-0.5 h-4 w-4 shrink-0 text-muted" aria-hidden />}
                        <span className="min-w-0 flex-1 break-words">{s.text}</span>
                        {s.at && <span className="text-xs text-muted">{time(s.at)}</span>}
                      </li>
                    ))}
                  </ul>
                </Section>
              )}
              <Section title={t("orgWs.drawer.help")}>
                {help.length ? (
                  <ul className="space-y-1.5">{help.map((h, i) => <li key={i} className="whitespace-pre-wrap break-words rounded-xl bg-surface-2 p-2.5 text-sm">{h.summary}{h.at && <span className="block text-xs text-muted">{time(h.at)}</span>}</li>)}</ul>
                ) : <p className="text-sm text-muted">{t("orgWs.drawer.noHelp")}</p>}
                <p className="text-xs text-muted">{t("orgWs.drawer.helpNote")}</p>
              </Section>
              {data.attention && (
                <Section title={t("orgWs.drawer.attention")}>
                  {data.attention.length ? (
                    <ul className="space-y-1 text-sm">
                      {data.attention.map((a, i) => <li key={i}>{time(a.at)} · {t(`orgWs.attention.${a.kind}`, { defaultValue: a.kind })}</li>)}
                    </ul>
                  ) : <p className="text-sm text-muted">{t("orgWs.drawer.noAttention")}</p>}
                </Section>
              )}
              {!!data.nudges?.length && (
                <Section title={t("orgWs.drawer.nudges")}>
                  <ul className="space-y-1.5">{data.nudges.map((n, i) => <li key={i} className="whitespace-pre-wrap break-words text-sm">{n.text}<span className="block text-xs text-muted">{[n.from, time(n.at)].filter(Boolean).join(" · ")}</span></li>)}</ul>
                </Section>
              )}
              {!!data.transcript?.length && (
                <details className="rounded-2xl border border-line p-3">
                  <summary className="cursor-pointer text-sm font-bold">{t("orgWs.drawer.transcript", { count: data.transcript.length })}</summary>
                  <ul className="mt-2 space-y-2">
                    {data.transcript.map((m, i) => (
                      <li key={i} className={cn("rounded-xl p-2 text-sm", m.role === "user" || m.role === "learner" ? "bg-accent/10" : "bg-surface-2")}>
                        <span className="block text-xs font-semibold text-muted">{m.role === "user" || m.role === "learner" ? tile.learner.name : t("workshop.companion")}</span>
                        <span className="whitespace-pre-wrap break-words">{m.text}</span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
