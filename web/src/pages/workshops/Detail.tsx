import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Award, CalendarPlus, CheckCircle2, ClipboardList, ListOrdered } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { Md } from "@/components/Md";
import { PageError } from "@/components/PageState";
import { Button, Card } from "@/components/ui";
import { ProctorNotice } from "@/components/workshop/ProctorNotice";
import { Countdown, PriceBadge, RunMeta } from "@/components/workshop/RunBits";
import { ApiError } from "@/lib/api";
import { rupees } from "@/lib/billing";
import { canEnrol, downloadIcs, isEnrolled, joinPhase, payForWorkshop, runKey, useNow, useRunTime, workshops, type RunDetail } from "@/lib/workshops";
import { mascot } from "@/mascot/store";

import { useOpenSession } from "./useOpenSession";

/** Why enrolling failed: the server's code (workshop or billing), else what the checkout promise rejected with. */
function failCode(e: unknown): string {
  return e instanceof ApiError ? String(e.data?.code ?? e.data?.detail ?? "generic") : (e as Error).message;
}

function EnrolBox({ run, now }: { run: RunDetail; now: number }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const when = useRunTime();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const { open, busy: opening, err: openErr } = useOpenSession();
  const phase = joinPhase(run, now);
  const status = canEnrol(run, now);
  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: runKey(run.id) }), qc.invalidateQueries({ queryKey: ["workshop-runs"] })]);

  async function enrol() {
    setBusy(true);
    setMsg(null);
    try {
      if (run.price_paise === 0) await workshops.enroll(run.id);
      else {
        const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#f97316";
        await payForWorkshop(run.id, accent);
      }
      mascot.react("celebrate");
      await refresh();
    } catch (e) {
      const code = failCode(e);
      if (code === "payment_pending") {
        // Paid; the server is still confirming with Razorpay. Say so, and look again shortly.
        setMsg({ ok: true, text: t("workshop.pub.paidPending") });
        setTimeout(() => void refresh(), 15_000);
      } else if (code === "paid_no_seat") {
        // Money taken, no seat: the server flags it for a refund. Say so plainly.
        setMsg({ ok: false, text: t("workshop.pub.err.paid_no_seat") });
        void refresh();
      } else if (code !== "dismissed") {
        const listCodes = ["run_full", "run_closed", "run_cancelled", "too_late"];
        const ownCodes = ["already_enrolled", "not_paid", "bad_gst_details", "promo_invalid"];
        setMsg({
          ok: false,
          text: listCodes.includes(code) ? t(`workshop.list.err.${code}`) : ownCodes.includes(code) ? t(`workshop.pub.err.${code}`) : t(`billing.errors.${code}`, { defaultValue: t("billing.errors.generic") }),
        });
        if (code === "already_enrolled") void refresh();
      }
    } finally {
      setBusy(false);
    }
  }

  if (isEnrolled(run)) {
    return (
      <Card className="space-y-3 border-2 border-good/40">
        <p className="flex items-center gap-2 font-display text-xl font-bold text-good"><CheckCircle2 className="h-6 w-6" aria-hidden /> {t("workshop.pub.enrolled")}</p>
        {phase === "before_lobby" && (
          <>
            <p className="text-lg">{t("workshop.pub.startsIn")} <Countdown to={run.starts_at} now={now} className="font-bold" /></p>
            <p className="text-sm text-muted">{t("workshop.pub.enrolledSub")}</p>
            {run.lobby_opens_at && <p className="text-sm text-muted">{t("workshop.pub.lobbyAt", { time: when.full(run.lobby_opens_at) })}</p>}
          </>
        )}
        <div className="flex flex-wrap gap-2">
          {run.session_id || phase === "open" || phase === "anytime" ? (
            <Button loading={opening} onClick={() => void open(run)}>{run.session_id ? t("workshop.list.continue") : t("workshop.pub.joinNow")} <ArrowRight className="h-4 w-4" /></Button>
          ) : phase === "lobby" ? (
            <Link to={`/workshops/${run.id}/lobby`} className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2.5 font-semibold text-accent-ink shadow-sm hover:brightness-105">{t("workshop.pub.toLobby")} <ArrowRight className="h-4 w-4" aria-hidden /></Link>
          ) : null}
          {(phase === "before_lobby" || phase === "lobby") && (
            <Button variant="outline" onClick={() => downloadIcs(run, `${location.origin}/workshops/${run.id}`)}><CalendarPlus className="h-4 w-4" /> {t("workshop.pub.addCal")}</Button>
          )}
        </div>
        {phase === "closed" && !run.session_id && <p className="text-sm text-muted">{t("workshop.pub.lobby.closedSub")}</p>}
        {openErr && <p role="alert" className="text-sm text-bad">{openErr}</p>}
      </Card>
    );
  }

  if (run.my_status === "paid_pending") {
    return <Card role="status" className="border-2 border-accent/40 text-lg">{t("workshop.pub.paidPending")}</Card>;
  }

  return (
    <Card className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-semibold text-muted">{t("workshop.pub.price")}</span>
        <PriceBadge paise={run.price_paise} className="text-base" />
      </div>
      {status === "ok" ? (
        <>
          <Button className="w-full py-3 text-lg" loading={busy} onClick={() => void enrol()}>
            {run.price_paise === 0 ? t("workshop.list.enrol") : t("workshop.pub.pay", { amount: rupees(run.price_paise) })}
          </Button>
          {run.price_paise > 0 && <p className="text-center text-xs text-muted">{t("workshop.pub.payNote")}</p>}
          {phase !== "anytime" && <p className="text-center text-sm">{t("workshop.pub.startsIn")} <Countdown to={run.starts_at} now={now} className="font-semibold" /></p>}
        </>
      ) : (
        <p className="font-semibold text-muted">{t(`workshop.pub.no.${status}`)}</p>
      )}
      {msg && <p role={msg.ok ? "status" : "alert"} className={msg.ok ? "text-sm text-good" : "text-sm text-bad"}>{msg.text}</p>}
    </Card>
  );
}

/** One public run: what it covers, what to set up, what's tracked, and enrol (free) or pay and enrol. */
export default function WorkshopDetailPage() {
  const { t } = useTranslation();
  const { runId } = useParams();
  const id = Number(runId);
  const now = useNow(1000);
  const { data: run, error, refetch } = useQuery({
    queryKey: runKey(id), queryFn: () => workshops.run(id), enabled: id > 0,
    // While a payment is being confirmed, look again every few seconds.
    refetchInterval: (q) => (q.state.data?.my_status === "paid_pending" ? 5000 : false),
  });

  if (!(id > 0)) return <PageError notFound />;
  if (error) return <PageError error={error} onRetry={() => void refetch()} />;
  if (!run) return <p className="p-8 text-muted">{t("common.loading")}</p>;
  const agenda = run.agenda ?? [];
  const prereqs = run.prerequisites ?? [];
  const mode = run.proctoring ?? "off";

  return (
    <div className="mx-auto max-w-5xl space-y-5 px-4 py-6 md:py-8">
      <Link to="/workshops" className="inline-flex items-center gap-1 text-sm font-semibold text-accent hover:underline"><ArrowLeft className="h-4 w-4" aria-hidden /> {t("workshop.pub.back")}</Link>
      <header className="space-y-2">
        <h1 className="break-words font-display text-3xl font-extrabold md:text-4xl">{run.workshop.title}</h1>
        <p className="break-words text-lg text-muted">{run.workshop.summary}</p>
        <RunMeta run={run} />
        {run.status === "cancelled" && <p role="status" className="rounded-xl bg-bad/10 px-3 py-2 font-semibold text-bad">{t("workshop.pub.no.cancelled")}</p>}
      </header>
      {/* The enrol box comes first in the DOM, as it does on screen on a phone; on desktop it sits in the right column. */}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <aside className="min-w-0 lg:sticky lg:top-16 lg:col-start-2 lg:row-start-1 lg:self-start"><EnrolBox run={run} now={now} /></aside>
        <div className="min-w-0 space-y-5 lg:col-start-1 lg:row-start-1">
          {!!agenda.length && (
            <Card className="space-y-3">
              <h2 className="flex items-center gap-2 font-display text-xl font-bold"><ListOrdered className="h-5 w-5 text-accent" aria-hidden /> {t("workshop.pub.agenda")}</h2>
              <ol className="space-y-2" aria-label={t("workshop.pub.agenda")}>
                {agenda.map((a, i) => (
                  <li key={i} className="flex items-center gap-3 rounded-xl border border-line px-3 py-2">
                    <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-surface-2 text-sm font-bold">{i + 1}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block break-words font-semibold">{a.title}</span>
                      {a.kind && <span className="block text-xs text-muted">{t(`workshop.kind.${a.kind}`)}</span>}
                    </span>
                    <span className="shrink-0 text-sm tabular-nums text-muted">{t("workshop.list.minutes", { count: a.minutes })}</span>
                  </li>
                ))}
              </ol>
            </Card>
          )}
          <Card className="space-y-3">
            <h2 className="flex items-center gap-2 font-display text-xl font-bold"><ClipboardList className="h-5 w-5 text-accent" aria-hidden /> {t("workshop.pub.prereqs")}</h2>
            {prereqs.length ? (
              <ul className="space-y-2">
                {prereqs.map((p) => (
                  <li key={p.key} className="rounded-xl border border-line px-3 py-2">
                    <p className="break-words font-semibold">{p.label}</p>
                    {p.how_to_md && (
                      <details className="mt-1">
                        <summary className="cursor-pointer text-sm font-semibold text-accent">{t("workshop.prereq.how")}</summary>
                        <div className="prose-chat mt-1 text-base"><Md>{p.how_to_md}</Md></div>
                      </details>
                    )}
                  </li>
                ))}
              </ul>
            ) : <p className="text-muted">{t("workshop.pub.prereqsNone")}</p>}
          </Card>
          <ProctorNotice as="h2" mode={mode} org={run.audience === "org"} tracked={run.tracked} />
          {run.certificate && (
            <Card className="flex gap-3">
              <Award className="h-6 w-6 shrink-0 text-accent" aria-hidden />
              <p>{t("workshop.pub.certificate")}</p>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
