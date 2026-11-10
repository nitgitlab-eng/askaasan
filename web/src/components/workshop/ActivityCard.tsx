import { CheckCircle2, ChevronDown, Circle } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card } from "@/components/ui";
import { cn } from "@/lib/cn";
import { isBuildTask, isDiy, type FinalResult, type Session, type Stage } from "@/lib/workshops";

import { AgentBuilder } from "./AgentBuilder";
import { BuildTaskCard } from "./BuildTask";
import { FinalForm } from "./FinalForm";
import { HelpPanel } from "./HelpPanel";

/** Hands-on steps: the current one has a big "I've done this"; the server owns where the learner is. */
function Steps({ stage, onDone }: { stage: Stage; onDone: (i: number) => void }) {
  const { t } = useTranslation();
  const current = stage.cursor ?? stage.steps.findIndex((x) => !x.done);
  return (
    <ul className="space-y-2" aria-label={t("workshop.steps")}>
      {stage.steps.map((x, i) => (
        <li key={i} className={cn("flex flex-wrap items-center gap-3 rounded-xl px-3 py-2.5 text-lg", i === current ? "bg-accent/10 font-semibold" : "text-muted")}>
          {x.done ? <CheckCircle2 className="h-5 w-5 shrink-0 text-good" aria-label={t("workshop.done")} /> : <Circle className={cn("h-5 w-5 shrink-0", i === current && "text-accent")} aria-hidden />}
          <span className="min-w-0 flex-1 break-words">{x.text}</span>
          {i === current && !x.done && <Button className="min-h-11 shrink-0" onClick={() => onDone(i)}>{t("workshop.stepDone")}</Button>}
        </li>
      ))}
    </ul>
  );
}

/** "Show my screen or paste the error": the help panel, folded away until the learner asks for it. */
function StuckHelp({ sessionId }: { sessionId: number }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}
        className="flex min-h-11 w-full items-center justify-center gap-2 rounded-xl px-3 text-base font-semibold text-accent hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/40">
        {t("workshop.live.stuckHelp")} <ChevronDown className={cn("h-5 w-5 transition", open && "rotate-180")} aria-hidden />
      </button>
      {open && <HelpPanel sessionId={sessionId} className="mt-2" />}
    </div>
  );
}

/**
 * What the learner works on, only when the stage needs it: DIY steps (+ help), the build task, the agent builder or
 * the final. Teach and check stages have none: the conversation is the activity.
 */
export function ActivityCard({ session, stage, onStepDone, onSession, onResult }: {
  session: Session; stage: Stage; onStepDone: (i: number) => void; onSession: (s: Session) => void; onResult: (r: FinalResult) => void;
}) {
  if (stage.kind === "assessment") {
    return <FinalForm sessionId={session.id} final={session.final} passMark={session.workshop.pass_mark} attemptsLeft={session.attempts_left} onResult={onResult} />;
  }
  if (!isDiy(stage.kind)) return null;
  return (
    <section aria-label={stage.title} data-testid="activity" className="w-full min-w-0 space-y-3">
      {(!!stage.steps.length || stage.kind === "diy") && (
        <Card className="space-y-3">
          {!!stage.steps.length && <Steps stage={stage} onDone={onStepDone} />}
          <StuckHelp sessionId={session.id} />
        </Card>
      )}
      {stage.kind === "build" && isBuildTask(stage.task) && (
        <BuildTaskCard key={stage.key} sessionId={session.id} task={stage.task} stageTitle={stage.title} onSession={onSession} />
      )}
      {stage.kind === "agent_build" && <AgentBuilder sessionId={session.id} />}
      {!stage.steps.length && stage.kind !== "diy" && <StuckHelp sessionId={session.id} />}
    </section>
  );
}
