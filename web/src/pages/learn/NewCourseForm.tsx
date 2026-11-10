import { useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { GoalWizard } from "@/components/adaptive/GoalWizard";
import { Button, Labelled, Segmented } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { createCourse, type CourseOptions } from "@/lib/learn";
import { cn } from "@/lib/cn";
import { mascot } from "@/mascot/store";

/** New course: guided by default (topic → Kili suggests real uses → a course toward that goal); "I know exactly what I
 * want" opens the direct form. A prefilled goal (templates, recommendations) is already specific: direct form. */
export function NewCourseForm({ defaultGoal = "", onDone }: { defaultGoal?: string; onDone?: () => void }) {
  const { t } = useTranslation();
  const [direct, setDirect] = useState(!!defaultGoal);
  return (
    <div className="space-y-3">
      {direct ? <DirectCourseForm defaultGoal={defaultGoal} onDone={onDone} /> : <GoalWizard onDone={onDone} />}
      <button type="button" className="text-sm font-semibold text-accent underline-offset-2 hover:underline" onClick={() => setDirect((v) => !v)}>
        {t(direct ? "adaptive.useGuided" : "adaptive.useDirect")}
      </button>
    </div>
  );
}

function DirectCourseForm({ defaultGoal = "", onDone }: { defaultGoal?: string; onDone?: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [goal, setGoal] = useState(defaultGoal);
  const [level, setLevel] = useState("beginner");
  const [opts, setOpts] = useState<CourseOptions>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (goal.trim().length < 3) return;
    setBusy(true);
    setError("");
    try {
      const c = await createCourse({ goal: goal.trim(), level, ...opts });
      mascot.react("thinking", 0);
      mascot.say(t("learn.building"), { ms: 4000 });
      void qc.invalidateQueries({ queryKey: ["courses"] });
      onDone?.();
      navigate(`/learn/${c.id}`);
    } catch (e) {
      const code = e instanceof ApiError ? (e.data?.code as string | undefined) : undefined;
      setError(code === "too_many_generating" ? t("learn.tooMany") : e instanceof ApiError && e.status === 400 ? t("learn.badGoal") : t("learn.createFailed"));
      mascot.react("hmm");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <label className="block space-y-1">
        <span className="text-sm font-medium">{t("learn.goalLabel")}</span>
        <input
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder={t("learn.goalPlaceholder")}
          maxLength={300}
          className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2.5 outline-none focus:border-accent"
        />
      </label>
      <Labelled text={t("learn.level")}>
        <Segmented
          label={t("learn.level")}
          value={level}
          onChange={setLevel}
          options={["beginner", "intermediate", "advanced"].map((v) => ({ value: v, label: t(`learn.levels.${v}`) }))}
        />
      </Labelled>
      <details className="rounded-xl border border-line px-3 py-2">
        <summary className="cursor-pointer text-sm font-medium">{t("courseOpts.more")}</summary>
        <div className="mt-3 space-y-3">
          <Labelled text={t("courseOpts.tone")}>
            <Segmented label={t("courseOpts.tone")} value={opts.tone ?? "friendly"} onChange={(v) => setOpts((o) => ({ ...o, tone: v as CourseOptions["tone"] }))}
              options={(["friendly", "formal", "playful", "exam"] as const).map((v) => ({ value: v, label: t(`courseOpts.tones.${v}`) }))} />
          </Labelled>
          <Labelled text={t("courseOpts.session")}>
            <Segmented label={t("courseOpts.session")} value={String(opts.session_minutes ?? 10)} onChange={(v) => setOpts((o) => ({ ...o, session_minutes: Number(v) as 5 | 10 | 20 }))}
              options={[5, 10, 20].map((n) => ({ value: String(n), label: t("courseOpts.minutes", { n }) }))} />
          </Labelled>
          <fieldset>
            <legend className="mb-1 text-sm font-medium">{t("courseOpts.style")}</legend>
            <div className="flex flex-wrap gap-2">
              {["explanations", "exercises", "examples", "video", "roleplay"].map((st) => {
                const on = opts.styles?.includes(st) ?? false;
                return (
                  <button key={st} type="button" aria-pressed={on} onClick={() => setOpts((o) => ({ ...o, styles: on ? (o.styles ?? []).filter((x) => x !== st) : [...(o.styles ?? []), st] }))}
                    className={cn("rounded-full border-2 px-3 py-1 text-sm font-semibold", on ? "border-accent bg-accent text-accent-ink" : "border-line")}>
                    {t(`courseOpts.styles.${st}`)}
                  </button>
                );
              })}
            </div>
          </fieldset>
        </div>
      </details>
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      <Button type="submit" loading={busy} disabled={goal.trim().length < 3}>
        <Sparkles className="h-4 w-4" /> {t("learn.create")}
      </Button>
    </form>
  );
}
