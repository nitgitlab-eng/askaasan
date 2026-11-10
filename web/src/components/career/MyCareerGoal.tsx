import { FileUp, Target } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { createCourse } from "@/lib/learn";
import { learner } from "@/lib/learner";

type Cv = Awaited<ReturnType<typeof learner.cv>>;
type Plan = Awaited<ReturnType<typeof learner.targetRole>>;

/** CV upload → what you already have; "I want to become …" → the gaps, followed as skills, plus course ideas to start. */
export function MyCareerGoal() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const file = useRef<HTMLInputElement>(null);
  const [cv, setCv] = useState<Cv | null>(null);
  const [role, setRole] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState<"" | "cv" | "plan" | "course">("");
  const [err, setErr] = useState("");
  const fail = (e: unknown) => setErr(e instanceof ApiError && e.status === 429 ? t("careerPlus.limit") : e instanceof ApiError && e.status === 400 ? t("careerPlus.badFile") : t("mentor.errors.generic"));

  return (
    <Card className="space-y-4">
      <h2 className="flex items-center gap-2 font-display text-xl font-bold"><Target className="h-5 w-5 text-accent" /> {t("careerPlus.title")}</h2>
      <div className="space-y-2">
        <p className="text-sm text-muted">{t("careerPlus.cvSub")}</p>
        <input ref={file} type="file" accept=".pdf,.docx,.txt" className="hidden" onChange={async (e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (!f) return;
          setErr(""); setBusy("cv");
          try { setCv(await learner.cv(f)); } catch (x) { fail(x); } finally { setBusy(""); }
        }} />
        <Button variant="outline" loading={busy === "cv"} onClick={() => file.current?.click()}><FileUp className="h-4 w-4" /> {t("careerPlus.upload")}</Button>
        <p className="text-xs text-muted">{t("careerPlus.privacy")}</p>
        {cv && (
          <div className="rounded-xl bg-surface-2 p-3 text-sm">
            <p className="font-semibold">{cv.current_role}{cv.years_experience ? ` · ${t("careerPlus.years", { count: cv.years_experience })}` : ""}</p>
            <p className="text-muted">{cv.summary}</p>
            <p className="mt-1">{cv.skills.join(" · ")}</p>
          </div>
        )}
      </div>
      <form className="flex flex-wrap gap-2" onSubmit={async (e) => {
        e.preventDefault();
        if (role.trim().length < 2) return;
        setErr(""); setBusy("plan");
        try { setPlan(await learner.targetRole(role.trim())); } catch (x) { fail(x); } finally { setBusy(""); }
      }}>
        <input value={role} onChange={(e) => setRole(e.target.value)} maxLength={120} placeholder={t("careerPlus.rolePh")} aria-label={t("careerPlus.role")}
          className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2" />
        <Button type="submit" loading={busy === "plan"} disabled={role.trim().length < 2}>{t("careerPlus.plan")}</Button>
      </form>
      {plan && (
        <div className="space-y-3">
          <p className="text-sm"><b>{t("careerPlus.needs")}</b> {plan.required.join(" · ")}</p>
          <p className="text-sm"><b>{t("careerPlus.missing")}</b> {plan.missing.join(" · ") || "—"}</p>
          {plan.missing_matched.length > 0 && <p className="text-xs text-muted">{t("careerPlus.followed", { names: plan.missing_matched.map((s) => (i18n.language === "ta" && s.name_ta ? s.name_ta : s.name)).join(", ") })}</p>}
          <ol className="space-y-2">
            {plan.courses.map((g, i) => (
              <li key={g} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line p-2">
                <span><b>{i + 1}.</b> {g}</span>
                <Button variant="outline" loading={busy === "course"} onClick={async () => {
                  setBusy("course");
                  try { const c = await createCourse({ goal: g, level: "beginner" }); navigate(`/learn/${c.id}`); } catch (x) { fail(x); } finally { setBusy(""); }
                }}>{t("careerPlus.start")}</Button>
              </li>
            ))}
          </ol>
        </div>
      )}
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
    </Card>
  );
}
