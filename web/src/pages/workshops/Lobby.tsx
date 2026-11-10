import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Circle, DoorClosed, Play } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { PageError } from "@/components/PageState";
import { Button, Card } from "@/components/ui";
import { ProctorNotice } from "@/components/workshop/ProctorNotice";
import { Countdown } from "@/components/workshop/RunBits";
import { isEnrolled, joinPhase, runKey, useNow, useRunTime, workshops } from "@/lib/workshops";
import { Kili } from "@/mascot/Kili";

import { useOpenSession } from "./useOpenSession";

/**
 * The waiting room. It opens `lobby_opens_minutes` before the start: a countdown and the setup list, with prep allowed
 * early. At the start time Join opens the session; after the join window it says joining has closed.
 */
export default function WorkshopLobbyPage() {
  const { t } = useTranslation();
  const { runId } = useParams();
  const id = Number(runId);
  const now = useNow(1000);
  const when = useRunTime();
  const { open, busy, err } = useOpenSession();
  const { data: run, error, refetch } = useQuery({ queryKey: runKey(id), queryFn: () => workshops.run(id), enabled: id > 0 });

  if (!(id > 0)) return <PageError notFound />;
  if (error) return <PageError error={error} onRetry={() => void refetch()} />;
  if (!run) return <p className="p-8 text-muted">{t("common.loading")}</p>;
  const phase = joinPhase(run, now);
  const prereqs = run.prerequisites ?? [];
  const toDetail = (
    <Link to={`/workshops/${run.id}`} className="inline-flex items-center gap-1 rounded-xl border-2 border-line bg-surface px-4 py-2 font-semibold hover:border-accent">
      {t("workshop.pub.lobby.toDetail")} <ArrowRight className="h-4 w-4" aria-hidden />
    </Link>
  );

  let body;
  if (!isEnrolled(run)) {
    body = <Card className="space-y-3 text-center"><p className="text-lg">{t("workshop.pub.lobby.notEnrolled")}</p><div>{toDetail}</div></Card>;
  } else if (run.session_id) {
    body = (
      <Card className="space-y-3 text-center">
        <p className="text-lg">{t("workshop.pub.lobby.inProgress")}</p>
        <Button className="py-3 text-lg" loading={busy} onClick={() => void open(run)}>{t("workshop.list.continue")} <ArrowRight className="h-5 w-5" /></Button>
      </Card>
    );
  } else if (phase === "cancelled" || phase === "closed") {
    body = (
      <Card className="space-y-3 text-center">
        <DoorClosed className="mx-auto h-10 w-10 text-muted" aria-hidden />
        <p className="font-display text-2xl font-bold">{phase === "cancelled" ? t("workshop.pub.no.cancelled") : t("workshop.pub.lobby.closed")}</p>
        {phase === "closed" && <p className="text-muted">{t("workshop.pub.lobby.closedSub")}</p>}
        <Link to="/workshops" className="font-semibold text-accent hover:underline">{t("workshop.pub.back")}</Link>
      </Card>
    );
  } else if (phase === "before_lobby") {
    body = (
      <Card className="space-y-3 text-center">
        <p className="text-lg">{t("workshop.pub.lobbyAt", { time: when.full(run.lobby_opens_at ?? run.join_opens_at ?? run.starts_at) })}</p>
        <p className="text-muted">{t("workshop.pub.lobby.opensIn")} <Countdown to={run.lobby_opens_at ?? run.join_opens_at ?? run.starts_at} now={now} className="font-semibold" /></p>
        <div>{toDetail}</div>
      </Card>
    );
  } else {
    const live = phase === "open" || phase === "anytime";
    body = (
      <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_320px]">
        <Card className="min-w-0 space-y-4 text-center">
          {live ? (
            <p className="font-display text-3xl font-extrabold text-accent">{t("workshop.pub.lobby.live")}</p>
          ) : (
            <>
              <p className="text-sm font-semibold uppercase tracking-wide text-muted">{t("workshop.pub.startsIn")}</p>
              <Countdown to={run.starts_at} now={now} className="block font-display text-4xl font-extrabold md:text-5xl" />
              <p className="text-muted">{t("workshop.pub.lobby.wait")}</p>
            </>
          )}
          {live ? (
            <Button className="w-full py-3 text-lg" loading={busy} onClick={() => void open(run)}><Play className="h-5 w-5" /> {t("workshop.pub.joinNow")}</Button>
          ) : (
            <Button variant="outline" className="w-full py-3 text-lg" loading={busy} onClick={() => void open(run)}>{t("workshop.pub.lobby.prep")}</Button>
          )}
          {live && run.join_closes_at && <p className="text-sm text-muted">{t("workshop.pub.lobby.closesAt", { time: when.time(run.join_closes_at) })}</p>}
          {err && <p role="alert" className="text-sm text-bad">{err}</p>}
        </Card>
        <div className="min-w-0 space-y-5">
          <Card className="space-y-3">
            <h2 className="font-display text-lg font-bold">{t("workshop.pub.lobby.prepTitle")}</h2>
            {prereqs.length ? (
              <ul className="space-y-2">{prereqs.map((p) => <li key={p.key} className="flex items-start gap-2"><Circle className="mt-1 h-4 w-4 shrink-0 text-muted" aria-hidden /> <span className="min-w-0 break-words">{p.label}</span></li>)}</ul>
            ) : <p className="text-muted">{t("workshop.pub.prereqsNone")}</p>}
            <p className="text-sm text-muted">{t("workshop.pub.lobby.prepSub")}</p>
          </Card>
          {/* Same "what we track" wording as the run page and the prerequisites screen, before the learner joins. */}
          <ProctorNotice as="h2" mode={run.proctoring ?? "off"} org={run.audience === "org"} tracked={run.tracked} />
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-5 px-4 py-6 md:py-8">
      <Link to={`/workshops/${run.id}`} className="inline-flex items-center gap-1 text-sm font-semibold text-accent hover:underline"><ArrowLeft className="h-4 w-4 shrink-0" aria-hidden /> <span className="min-w-0 break-words">{run.workshop.title}</span></Link>
      <header className="flex items-center gap-4">
        <Kili mood="wave" size={72} />
        <div className="min-w-0">
          <p className="text-sm font-semibold uppercase tracking-wide text-accent">{t("workshop.pub.lobby.title")}</p>
          <h1 className="break-words font-display text-2xl font-extrabold md:text-3xl">{run.workshop.title}</h1>
          <p className="text-muted">{when.date(run.starts_at)} · {when.time(run.starts_at)}</p>
        </div>
      </header>
      {body}
    </div>
  );
}
