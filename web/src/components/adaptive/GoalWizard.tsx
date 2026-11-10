import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, Sparkles, Wand2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { Button, Labelled, Segmented, Toggle } from "@/components/ui";
import { adaptive, type LearningGoal, type Scenario } from "@/lib/adaptive";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { createCourse } from "@/lib/learn";
import { mascot } from "@/mascot/store";

type Step = "topic" | "pick" | "fit";
const INPUT = "w-full rounded-xl border-2 border-line bg-surface px-3 py-2.5 outline-none focus:border-accent";

function errorText(t: (k: string) => string, e: unknown) {
  const code = e instanceof ApiError ? (e.data?.code as string | undefined) : undefined;
  if (code === "goal_ai_limit") return t("adaptive.errors.aiLimit");
  if (code === "ai_budget_exceeded") return t("adaptive.errors.budget");
  if (code === "too_many_generating") return t("learn.tooMany");
  return t("adaptive.errors.generic");
}

/** "I want to learn AI" → Kili suggests real ways to use it (or checks the learner's own idea) → a few questions about
 * time and what they already know → a course built toward that goal. */
export function GoalWizard({ onDone }: { onDone?: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("topic");
  const [topic, setTopic] = useState("");
  const [about, setAbout] = useState("");
  const [goal, setGoal] = useState<LearningGoal | null>(null);
  const [custom, setCustom] = useState("");
  const [note, setNote] = useState<{ kind: "split" | "decline"; text: string } | null>(null);
  const [prior, setPrior] = useState("");
  const [noCode, setNoCode] = useState(false);
  const [hours, setHours] = useState("3");
  const [weeks, setWeeks] = useState("");
  const [level, setLevel] = useState("beginner");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(errorText(t, e));
      mascot.react("hmm");
    } finally {
      setBusy(false);
    }
  }

  const start = (e: FormEvent) => {
    e.preventDefault();
    if (topic.trim().length < 2) return;
    void run(async () => {
      mascot.react("thinking", 0);
      setGoal(await adaptive.startGoal(topic.trim(), about.trim()));
      setNote(null);
      setStep("pick");
      mascot.say(t("adaptive.pickSay"), { ms: 4000 });
    });
  };

  const chosen = (g: LearningGoal) => {
    setGoal(g);
    setLevel((g.scenario as Scenario).level ?? "beginner");
    setStep("fit");
  };

  const pick = (index: number) => goal && void run(async () => chosen(await adaptive.choose(goal.id, { index })));

  const check = (e: FormEvent) => {
    e.preventDefault();
    if (!goal || custom.trim().length < 4) return;
    void run(async () => {
      const r = await adaptive.choose(goal.id, { custom: custom.trim() });
      if (r.verdict === "accept" || r.verdict === "chosen") {
        mascot.react("cheer");
        chosen(r);
        return;
      }
      setGoal(r);
      setNote({ kind: r.verdict, text: r.reason ?? "" });
      mascot.react("hmm");
    });
  };

  const build = () =>
    goal &&
    void run(async () => {
      await adaptive.constraints(goal.id, {
        prior: prior.split(",").map((p) => p.trim()).filter(Boolean).slice(0, 10),
        no_code: noCode,
        hours_week: Number(hours),
        deadline_weeks: weeks ? Number(weeks) : null,
        level,
      });
      const c = await createCourse({ goal_id: goal.id });
      mascot.react("thinking", 0);
      mascot.say(t("learn.building"), { ms: 4000 });
      void qc.invalidateQueries({ queryKey: ["courses"] });
      onDone?.();
      navigate(`/learn/${c.id}`);
    });

  if (step === "topic") {
    return (
      <form onSubmit={start} className="space-y-3">
        <label className="block space-y-1">
          <span className="text-sm font-medium">{t("adaptive.topicLabel")}</span>
          <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder={t("adaptive.topicPlaceholder")} maxLength={200} className={INPUT} />
        </label>
        <label className="block space-y-1">
          <span className="text-sm font-medium">{t("adaptive.aboutLabel")}</span>
          <input value={about} onChange={(e) => setAbout(e.target.value)} placeholder={t("adaptive.aboutPlaceholder")} maxLength={300} className={INPUT} />
        </label>
        {error && <p role="alert" className="text-sm text-bad">{error}</p>}
        <Button type="submit" loading={busy} disabled={topic.trim().length < 2}>
          <Wand2 className="h-4 w-4" /> {t("adaptive.showWays")}
        </Button>
      </form>
    );
  }

  if (step === "pick" && goal) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-muted">{t("adaptive.pickIntro", { topic: goal.topic })}</p>
        {note && (
          <p role="status" className={cn("rounded-xl px-3 py-2 text-sm", note.kind === "split" ? "bg-accent/10" : "bg-bad/10")}>
            {note.text || t(note.kind === "split" ? "adaptive.splitNote" : "adaptive.declineNote")}
          </p>
        )}
        <ul className="grid gap-2 sm:grid-cols-2">
          {goal.suggestions.map((s, i) => (
            <li key={`${s.title}-${i}`}>
              <button type="button" disabled={busy} onClick={() => pick(i)}
                className={cn("h-full w-full rounded-xl border-2 p-3 text-left transition hover:border-accent disabled:opacity-60", s.foundations ? "border-dashed border-line" : "border-line")}>
                <span className="block font-semibold leading-tight">{s.title}</span>
                <span className="mt-1 block text-sm text-muted">{s.deliverable}</span>
                <span className="mt-2 block text-xs font-medium text-muted">
                  {s.foundations ? t("adaptive.foundations") + " · " : ""}{t(`learn.levels.${s.level}`)} · {t("adaptive.weeks", { count: s.weeks })}
                </span>
              </button>
            </li>
          ))}
        </ul>
        <form onSubmit={check} className="space-y-2 rounded-xl border border-line p-3">
          <label className="block space-y-1">
            <span className="text-sm font-medium">{t("adaptive.ownLabel")}</span>
            <textarea value={custom} onChange={(e) => setCustom(e.target.value)} placeholder={t("adaptive.ownPlaceholder")} maxLength={300} rows={2} className={INPUT} />
          </label>
          <Button type="submit" variant="outline" loading={busy} disabled={custom.trim().length < 4 || goal.ai_left < 1}>
            <Check className="h-4 w-4" /> {t("adaptive.checkIdea")}
          </Button>
          {goal.ai_left < 1 && <p className="text-xs text-muted">{t("adaptive.errors.aiLimit")}</p>}
        </form>
        {error && <p role="alert" className="text-sm text-bad">{error}</p>}
        <button type="button" className="text-sm font-semibold text-muted hover:text-accent" onClick={() => setStep("topic")}>
          <ArrowLeft className="mr-1 inline h-3 w-3" />{t("adaptive.back")}
        </button>
      </div>
    );
  }

  const sc = goal?.scenario as Scenario | undefined;
  return (
    <div className="space-y-4">
      {sc?.title && (
        <div className="rounded-xl bg-accent/10 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">{t("adaptive.yourGoal")}</p>
          <p className="font-semibold">{sc.title}</p>
          <p className="text-sm text-muted">{sc.deliverable}</p>
        </div>
      )}
      <label className="block space-y-1">
        <span className="text-sm font-medium">{t("adaptive.priorLabel")}</span>
        <input value={prior} onChange={(e) => setPrior(e.target.value)} placeholder={t("adaptive.priorPlaceholder")} maxLength={300} className={INPUT} />
      </label>
      <Toggle checked={noCode} onChange={setNoCode} label={t("adaptive.noCode")} />
      <Labelled text={t("adaptive.hours")}>
        <Segmented label={t("adaptive.hours")} value={hours} onChange={setHours}
          options={["1", "3", "5", "10"].map((v) => ({ value: v, label: t("adaptive.hoursN", { count: Number(v) }) }))} />
      </Labelled>
      <Labelled text={t("adaptive.deadline")}>
        <Segmented label={t("adaptive.deadline")} value={weeks} onChange={setWeeks}
          options={["", "2", "4", "8", "12"].map((v) => ({ value: v, label: v ? t("adaptive.weeks", { count: Number(v) }) : t("adaptive.noDeadline") }))} />
      </Labelled>
      <Labelled text={t("learn.level")}>
        <Segmented label={t("learn.level")} value={level} onChange={setLevel}
          options={["beginner", "intermediate", "advanced"].map((v) => ({ value: v, label: t(`learn.levels.${v}`) }))} />
      </Labelled>
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={build} loading={busy}><Sparkles className="h-4 w-4" /> {t("adaptive.build")}</Button>
        <button type="button" className="text-sm font-semibold text-muted hover:text-accent" onClick={() => setStep("pick")}>
          <ArrowLeft className="mr-1 inline h-3 w-3" />{t("adaptive.back")}
        </button>
      </div>
    </div>
  );
}
