import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Button, Card } from "@/components/ui";
import { localeOf } from "@/i18n/languages";
import { cn } from "@/lib/cn";
import type { MyAssignment } from "@/lib/orgs";

import { dueState, sortAssignments } from "./teachUtils";
import { useMyAssignments } from "./useMyAssignments";

/** Small chip: "Assigned · due 20 Oct", red when overdue, bold when mandatory. */
export function AssignedBadge({ a, now }: { a: MyAssignment; now: number }) {
  const { t, i18n } = useTranslation();
  const st = dueState(a, now);
  const d = a.due_at ? new Date(a.due_at).toLocaleDateString(localeOf(i18n.language), { day: "numeric", month: "short" }) : "";
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", st === "overdue" ? "bg-bad/15 text-bad" : st === "soon" ? "bg-amber-100 text-amber-800" : "bg-accent/15 text-accent")}>
        {a.due_at ? t("teach.learner.assignedDue", { d }) : t("teach.learner.assigned")}
      </span>
      {st === "overdue" && <span className="rounded-full bg-bad px-2 py-0.5 text-xs font-bold text-white">{t("teach.learner.overdue")}</span>}
      {a.mandatory && <span className="rounded-full border border-accent px-2 py-0.5 text-xs font-bold text-accent">{t("teach.learner.mandatory")}</span>}
    </span>
  );
}

const linkOf = (a: MyAssignment) => (a.kind === "scenario" ? `/roleplay?assignment=${a.id}` : `/learn/${a.course?.id}`);

/** Home: everything a teacher assigned (courses and role-plays), mandatory and overdue first. */
export function MyAssignmentsCard() {
  const { t } = useTranslation();
  const { data } = useMyAssignments();
  const [now] = useState(() => Date.now());
  const todo = sortAssignments((data ?? []).filter((a) => a.done < a.total), now);
  if (!todo.length) return null;
  return (
    <Card>
      <h2 className="mb-3 font-display text-xl font-bold">{t("org.assignedToYou")}</h2>
      <ul className="divide-y divide-line">
        {todo.slice(0, 6).map((a) => {
          const target = a.course ?? a.scenario;
          return (
            <li key={a.id} className={cn(a.mandatory && "rounded-xl border-l-4 border-accent pl-2")}>
              <Link to={linkOf(a)} className="flex items-center gap-3 py-2.5 hover:text-accent">
                <span className="text-2xl">{target?.emoji}</span>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold">{target?.title}</p>
                  <p className="truncate text-xs text-muted">{a.org}{a.note && <> · {a.note}</>}</p>
                  <AssignedBadge a={a} now={now} />
                </div>
                <span className="text-sm tabular-nums text-muted">{a.kind === "scenario" ? t(`teach.status.${a.status}`) : `${a.done}/${a.total}`}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

/** Role-play page: the scenarios a teacher assigned, with their due badges. */
export function AssignedScenarios({ onStart, busy, focus }: { onStart: (scenarioId: number, assignmentId: number) => void; busy: number | null; focus?: number }) {
  const { t } = useTranslation();
  const { data } = useMyAssignments();
  const [now] = useState(() => Date.now());
  const list = sortAssignments((data ?? []).filter((a) => a.kind === "scenario" && a.scenario), now);
  if (!list.length) return null;
  return (
    <section className="space-y-3">
      <h2 className="font-display text-xl font-bold">{t("teach.learner.assignedToYou")}</h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {list.map((a) => (
          <Card key={a.id} className={cn("flex flex-col gap-2", a.mandatory && "border-2 border-accent", focus === a.id && "ring-2 ring-accent")}>
            <div className="flex items-start justify-between gap-2">
              <span className="text-4xl">{a.scenario!.emoji}</span>
              <span className="text-xs font-semibold text-muted">{t(`teach.status.${a.status}`)}{a.best != null && ` · ${t("teach.learner.best", { n: a.best })}`}</span>
            </div>
            <h3 className="font-display text-lg font-bold leading-tight">{a.scenario!.title}</h3>
            <p className="text-xs text-muted">{a.org}{a.note && <> · {a.note}</>}</p>
            <AssignedBadge a={a} now={now} />
            <Button className="mt-1" loading={busy === a.scenario!.id} onClick={() => onStart(a.scenario!.id, a.id)}>{t("teach.learner.start")}</Button>
          </Card>
        ))}
      </div>
    </section>
  );
}
