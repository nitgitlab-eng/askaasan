import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { ArrowLeft, ArrowRight, ClipboardList, MessageCircle, Sparkles } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { CompanionPicker } from "@/components/CompanionPicker";
import { KiliInterview } from "@/components/paths/KiliInterview";
import { QuizRunner } from "@/components/paths/QuizRunner";
import { LanguageSelect } from "@/components/LanguageSelect";
import { WorkRoleStep } from "@/components/paths/WorkRoleStep";
import { SkillPicker } from "@/components/paths/SkillPicker";
import { Button, Card, Segmented, Toggle } from "@/components/ui";
import { setLanguage } from "@/i18n";
import { cn } from "@/lib/cn";
import { createCourse } from "@/lib/learn";
import { DOMAIN_SKILLS, paths, type OnboardProfile, type QuizQ } from "@/lib/paths";
import type { Preferences } from "@/lib/types";
import { useMe, useUpdatePreferences, useUpdateProfile } from "@/lib/useMe";
import { effectiveColor, swatchesFor } from "@/mascot/companions";
import { Kili } from "@/mascot/Kili";
import type { MascotMood } from "@/mascot/store";

const COLORS = ["#22c55e", "#0ea5e9", "#a855f7", "#f43f5e", "#f59e0b", "#14b8a6"];
const DOMAINS = ["ai", "python", "data", "web", "prompting", "career"] as const;
const STEP_MOOD: MascotMood[] = ["wave", "watching", "talking", "thinking", "talking", "watching", "cheer", "celebrate"];
type Level = "beginner" | "intermediate" | "advanced";

/**
 * Friendly steps: companion → language → (chat with Kili | questions: goal → skills → level/placement) → ready.
 * Ends by saving followed skills and generating the learner's first course.
 */
export default function OnboardingPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const updatePrefs = useUpdatePreferences();
  const updateProfile = useUpdateProfile();
  const [step, setStep] = useState(0);
  const [domain, setDomain] = useState<string>(me?.profile.domain || "ai");
  const [goal, setGoal] = useState("");
  const [level, setLevel] = useState<Level>("beginner");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [chat, setChat] = useState(false);
  const [viaChat, setViaChat] = useState(false);
  const [skills, setSkills] = useState<Record<string, number> | null>(null);
  const [quiz, setQuiz] = useState<{ id: number; questions: QuizQ[] } | null>(null);
  const [placed, setPlaced] = useState<{ level: Level; score: number } | null>(null);
  const [quizBusy, setQuizBusy] = useState(false);
  const [quizErr, setQuizErr] = useState("");
  const [params] = useSearchParams();
  // Redo (from Personalize): same steps, nothing is lost, and no new course unless the learner asks for one.
  const [redo] = useState(() => params.get("redo") === "1" || !!me?.profile.onboarding_completed);
  const [buildNew, setBuildNew] = useState(false);
  if (!me) return null;
  const p = me.preferences;

  const domainGoal = (d: string) => t(`onboarding.goals.${d}`);
  const pickedSkills = skills ?? Object.fromEntries((DOMAIN_SKILLS[domain] ?? []).map((s) => [s, 0]));

  async function startPlacement() {
    setQuizBusy(true);
    setQuizErr("");
    try {
      setQuiz(await paths.placement(goal.trim() || domainGoal(domain)));
    } catch {
      setQuizErr(t("paths.placementFailed"));
    } finally {
      setQuizBusy(false);
    }
  }
  async function submitPlacement(answers: Record<string, number>) {
    if (!quiz) return;
    setQuizBusy(true);
    try {
      const r = await paths.submitPlacement(quiz.id, answers);
      setLevel(r.level);
      setPlaced(r);
      setQuiz(null);
    } catch {
      setQuizErr(t("paths.placementFailed"));
    } finally {
      setQuizBusy(false);
    }
  }
  async function interviewDone(profile: OnboardProfile) {
    setBusy(true);
    try {
      await paths.applyInterview(profile);
      if (profile.first_course_goal) setGoal(profile.first_course_goal.slice(0, 300));
      if (["beginner", "intermediate", "advanced"].includes(profile.level_guess)) setLevel(profile.level_guess as Level);
      if (profile.background) setNotes(profile.background.slice(0, 1000));
      setSkills({}); // the interview already followed matching skills
      setChat(false);
      setViaChat(true);
      setStep(7);
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    setBusy(true);
    try {
      const finalGoal = goal.trim() || domainGoal(domain);
      const chosen = Object.entries(pickedSkills).map(([slug, self_rating]) => ({ slug, self_rating }));
      if (chosen.length) await paths.bulk(chosen).catch(() => undefined); // never block the first course on this
      await updateProfile.mutateAsync({ domain, level, goals: [finalGoal], onboarding_completed: true });
      let joined: string | null = null;
      try {
        joined = sessionStorage.getItem("aasan-joined-course");
        sessionStorage.removeItem("aasan-joined-course");
      } catch {
        /* ignore */
      }
      if (joined) {
        // They came from a shared course link — take them back to it instead of building a new one.
        navigate(`/learn/${joined}`, { replace: true });
        return;
      }
      if (redo && !buildNew) {
        navigate("/learn", { replace: true });
        return;
      }
      const course = await createCourse({ goal: finalGoal, level, domain, notes: notes.trim() });
      void qc.invalidateQueries({ queryKey: ["courses"] });
      navigate(`/learn/${course.id}`, { replace: true });
    } finally {
      setBusy(false);
    }
  }

  const steps = [
    // 0 — meet your companion
    <div key="0" className="space-y-4">
      <h1 className="font-display text-3xl font-extrabold">{t("onboarding.hello")}</h1>
      <p className="text-muted">{t("onboarding.helloSub")}</p>
      <div className="space-y-1">
        <span className="text-sm font-medium">{t("personalize.companion")}</span>
        <CompanionPicker prefs={p.mascot} onPick={(patch) => updatePrefs.mutate({ mascot: patch })} size={56} />
      </div>
      <label className="block space-y-1">
        <span className="text-sm font-medium">{t("personalize.mascotName")}</span>
        <input
          key={p.mascot.name}
          defaultValue={p.mascot.name}
          maxLength={24}
          onBlur={(e) => e.target.value.trim() && updatePrefs.mutate({ mascot: { name: e.target.value.trim() } })}
          className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2.5 outline-none focus:border-accent"
        />
      </label>
      <div className="flex flex-wrap gap-2">
        {swatchesFor(p.mascot.character, COLORS).map((c) => {
          const on = effectiveColor(p.mascot.character, p.mascot.color) === c;
          return (
            <button key={c} onClick={() => updatePrefs.mutate({ mascot: { color: c } })} aria-label={c} aria-pressed={on}
              className={cn("h-10 w-10 rounded-full border-4", on ? "border-ink" : "border-transparent")} style={{ background: c }} />
          );
        })}
      </div>
    </div>,
    // 1 — language
    <div key="1" className="space-y-4">
      <h1 className="font-display text-3xl font-extrabold">{t("onboarding.language")}</h1>
      <LanguageSelect
        value={me.profile.language}
        onChange={(v) => {
          setLanguage(v);
          updateProfile.mutate({ language: v });
        }}
      />
      <p className="text-sm font-medium text-muted">{t("personalize.replyLanguage")}</p>
      <Segmented
        label={t("personalize.replyLanguage")}
        value={p.mentor.reply_language}
        onChange={(v) => updatePrefs.mutate({ mentor: { reply_language: v } })}
        options={Object.entries(t("personalize.opts.replyLanguage", { returnObjects: true }) as Record<string, string>).map(([value, label]) => ({ value: value as Preferences["mentor"]["reply_language"], label }))}
      />
      <p className="text-xs text-muted">{t("personalize.replyLanguageHint")}</p>
    </div>,
    // 2 — how to set up
    <div key="2" className="space-y-4">
      <h1 className="font-display text-3xl font-extrabold">{t("paths.setupHow")}</h1>
      {chat ? <KiliInterview onDone={(pr) => void interviewDone(pr)} /> : (
        <div className="grid gap-2">
          <button onClick={() => setChat(true)} className="flex items-start gap-3 rounded-2xl border-2 border-line bg-surface p-4 text-left hover:border-accent">
            <MessageCircle className="mt-0.5 h-5 w-5 shrink-0 text-accent" />
            <span><span className="block font-display text-lg font-bold">{t("paths.setupChat", { name: p.mascot.name })}</span><span className="text-sm text-muted">{t("paths.setupChatSub")}</span></span>
          </button>
          <button onClick={() => { setViaChat(false); setStep(3); }} className="flex items-start gap-3 rounded-2xl border-2 border-line bg-surface p-4 text-left hover:border-accent">
            <ClipboardList className="mt-0.5 h-5 w-5 shrink-0 text-accent" />
            <span><span className="block font-display text-lg font-bold">{t("paths.setupForm")}</span><span className="text-sm text-muted">{t("paths.setupFormSub")}</span></span>
          </button>
        </div>
      )}
      {busy && <p className="text-sm text-muted">{t("common.loading")}</p>}
    </div>,
    // 3 — what to learn
    <div key="3" className="space-y-4">
      <h1 className="font-display text-3xl font-extrabold">{t("onboarding.what")}</h1>
      <div className="grid gap-2 sm:grid-cols-2">
        {DOMAINS.map((d) => (
          <button key={d} onClick={() => { setDomain(d); setSkills(null); }} aria-pressed={domain === d}
            className={cn("rounded-2xl border-2 p-4 text-left transition", domain === d ? "border-accent bg-accent/10" : "border-line bg-surface hover:border-accent")}>
            <p className="font-display text-lg font-bold">{t(`onboarding.domains.${d}`)}</p>
            <p className="text-sm text-muted">{domainGoal(d)}</p>
          </button>
        ))}
      </div>
      <input value={goal} onChange={(e) => setGoal(e.target.value)} maxLength={300} placeholder={t("onboarding.customGoal")}
        className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2.5 outline-none focus:border-accent" />
    </div>,
    // 4 — where you work/study + your role (optional; pre-selects skills)
    <WorkRoleStep key="4w" onSkills={(slugs) => setSkills((prev) => ({ ...(prev ?? pickedSkills), ...Object.fromEntries(slugs.map((x) => [x, (prev ?? pickedSkills)[x] ?? 0])) }))} />,
    // 5 — skills + self-rating
    <div key="4" className="space-y-3">
      <h1 className="font-display text-3xl font-extrabold">{t("paths.pickSkills")}</h1>
      <p className="text-sm text-muted">{t("paths.pickSkillsSub")}</p>
      <SkillPicker value={pickedSkills} onChange={setSkills} />
    </div>,
    // 6 — level (or placement check) + about you
    <div key="5" className="space-y-4">
      <h1 className="font-display text-3xl font-extrabold">{t("onboarding.level")}</h1>
      {quiz ? <QuizRunner questions={quiz.questions} onDone={(a) => void submitPlacement(a)} busy={quizBusy} /> : (
        <>
          <Segmented label={t("learn.level")} value={level} onChange={setLevel} options={(["beginner", "intermediate", "advanced"] as const).map((v) => ({ value: v, label: t(`learn.levels.${v}`) }))} />
          {placed ? <p role="status" className="rounded-xl bg-good/10 px-3 py-2 text-sm">{t("paths.placed", { level: t(`learn.levels.${placed.level}`), score: Math.round(placed.score * 100) })}</p>
            : <Button variant="ghost" loading={quizBusy} onClick={() => void startPlacement()}>{t("paths.takePlacement")}</Button>}
        </>
      )}
      {quizErr && <p role="alert" className="text-sm text-bad">{quizErr}</p>}
      <label className="block space-y-1">
        <span className="text-sm font-medium">{t("onboarding.about")}</span>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} maxLength={1000} placeholder={t("onboarding.aboutPlaceholder")}
          className="w-full rounded-xl border-2 border-line bg-surface p-3 outline-none focus:border-accent" />
      </label>
    </div>,
    // 7 — ready
    <div key="6" className="space-y-4 text-center">
      <h1 className="font-display text-3xl font-extrabold">{t("onboarding.ready", { name: p.mascot.name })}</h1>
      <p className="text-muted">{goal.trim() || domainGoal(domain)} · {t(`learn.levels.${level}`)}</p>
      {redo && (
        <div className="space-y-1 text-left">
          <Toggle label={t("lj.redo.newCourse")} checked={buildNew} onChange={setBuildNew} />
          <p className="text-xs text-muted">{t("lj.redo.kept")}</p>
        </div>
      )}
      <Button onClick={finish} loading={busy} className="mx-auto">
        <Sparkles className="h-4 w-4" /> {redo && !buildNew ? t("lj.redo.save") : t("onboarding.build")}
      </Button>
    </div>,
  ];

  return (
    <main className="mx-auto flex min-h-dvh max-w-4xl flex-col items-center justify-center gap-6 px-4 py-10 md:flex-row">
      <div className="shrink-0">
        <Kili character={p.mascot.character} mood={STEP_MOOD[step]} size={200} color={p.mascot.color} accessories={p.mascot.accessories} outfit={p.mascot.outfit} />
      </div>
      <Card className="w-full max-w-lg">
        {redo && <Link to="/" className="mb-3 inline-block text-sm font-semibold text-muted hover:text-accent">← {t("lj.redo.exit")}</Link>}
        <div className="mb-4 flex gap-1.5" aria-label={t("onboarding.step", { n: step + 1, total: steps.length })}>
          {steps.map((_, i) => <span key={i} className={cn("h-2 flex-1 rounded-full", i <= step ? "bg-accent" : "bg-surface-2")} />)}
        </div>
        <AnimatePresence mode="wait">
          <motion.div key={step} initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }}>
            {steps[step]}
          </motion.div>
        </AnimatePresence>
        {step < steps.length - 1 && step !== 2 && (
          <div className="mt-6 flex justify-between">
            <Button variant="ghost" onClick={() => setStep(step - 1)} disabled={step === 0}><ArrowLeft className="h-4 w-4" /> {t("common.back")}</Button>
            <Button onClick={() => setStep(step + 1)} disabled={step === 6 && !!quiz}>{t("onboarding.next")} <ArrowRight className="h-4 w-4" /></Button>
          </div>
        )}
        {step === steps.length - 1 && (
          <button onClick={() => { if (viaChat) { setViaChat(false); setSkills(null); setStep(2); } else setStep(step - 1); }} className="mt-4 text-sm text-muted hover:text-accent">{t("common.back")}</button>
        )}
      </Card>
    </main>
  );
}
