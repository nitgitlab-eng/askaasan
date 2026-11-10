import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import confetti from "canvas-confetti";
import { ArrowLeft, ArrowRight, MessageCircleHeart, PartyPopper, Video } from "lucide-react";
import { Fragment, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Md } from "@/components/Md";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ActivityCard } from "@/activities/ActivityCard";
import { LessonFeedbackCard } from "@/components/LessonFeedbackCard";
import { AboutQuestion } from "@/components/lesson/AboutQuestion";
import { FastTrack } from "@/components/lesson/FastTrack";
import { LessonAsk } from "@/components/lesson/LessonAsk";
import { LessonMedia } from "@/components/lesson/LessonMedia";
import { PulseCard } from "@/components/lesson/PulseCard";
import { ExplainSelection } from "@/components/study/ExplainSelection";
import { Button, Card, Toggle } from "@/components/ui";
import { LessonTabs } from "@/components/lesson/lx/InteractiveWidget";
import { TutorChat } from "@/components/lesson/lx/TutorChat";
import { ApiError, api } from "@/lib/api";
import { celebrate, gameKey } from "@/lib/game";
import { offerPushAfterFirstLesson } from "@/lib/push";
import type { Lesson, Recap } from "@/lib/learn";
import { FeedbackSurveyPrompt } from "@/pages/orgs/teach/FeedbackSurveyPrompt";
import { roleplay } from "@/lib/roleplay";
import { isOfflineError, offlineQueue } from "@/lib/offline";
import { LANG_NAMES } from "@/lib/study";
import { useMe, useUpdatePreferences } from "@/lib/useMe";
import { Kili } from "@/mascot/Kili";
import { COMPANION_EMOJI } from "@/mascot/name";
import { sfx } from "@/mascot/sfx";
import { mascot } from "@/mascot/store";

function LessonView() {
  const { t } = useTranslation();
  const { courseId, lessonId } = useParams();
  const [search] = useSearchParams();
  const fastParam = search.get("fast") === "1"; // an adaptive "quick check" step opens the fast-track at once
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data: me } = useMe();
  const [recap, setRecap] = useState<Recap | null>(null);
  // "Learn with Kili": chat-paced teaching instead of reading the whole explanation (remembered per browser).
  const [kili, setKiliState] = useState(() => {
    try { return localStorage.getItem("aasan-learn-with-kili") === "1"; } catch { return false; }
  });
  const setKili = (v: boolean) => {
    setKiliState(v);
    try { localStorage.setItem("aasan-learn-with-kili", v ? "1" : "0"); } catch { /* private mode */ }
  };
  const [graded, setGraded] = useState(0);
  const [asking, setAsking] = useState(false);
  const [listened, setListened] = useState(false);
  const onListened = useCallback(() => {
    setListened(true);
    void qc.invalidateQueries({ queryKey: ["course-listened", Number(courseId)] });
  }, [qc, courseId]);
  const updatePrefs = useUpdatePreferences();
  const lang = me?.preferences.learning.lesson_language ?? "";

  // POST start (generates on first open), then poll GET while generating or translating.
  const lesson = useQuery({
    queryKey: ["lesson", lessonId, lang],
    queryFn: async () => {
      const q = lang ? `?lang=${lang}` : "";
      const prev = qc.getQueryData<Lesson>(["lesson", lessonId, lang]) ?? qc.getQueryData<Lesson>(["lesson", lessonId, ""]);
      const read = () => api<Lesson>(`/api/learn/subsections/${lessonId}/${q}`);
      if ((prev && prev.lesson_status !== "failed") || !navigator.onLine) return read(); // offline: the saved copy only
      try {
        return await api<Lesson>(`/api/learn/subsections/${lessonId}/start/${q}`, { method: "POST" });
      } catch (e) {
        if (isOfflineError(e) || (e instanceof ApiError && e.status >= 500)) return read(); // server unreachable → the saved copy
        throw e;
      }
    },
    placeholderData: (prev) => prev,
    refetchInterval: (q) => (q.state.data?.lesson_status === "generating" || q.state.data?.translation?.status === "translating" ? 2000 : false),
  });
  const l = lesson.data;
  const notPublished = lesson.error instanceof ApiError && lesson.error.data?.code === "lesson_not_ready";

  useEffect(() => {
    if (l?.lesson_status === "ready") mascot.react("wave");
  }, [l?.lesson_status]);

  const [finishQueued, setFinishQueued] = useState(false);
  const pulseKey = `aasan-pulse-${lessonId}`;
  const [pulseOff, setPulseOff] = useState(() => {
    try { return sessionStorage.getItem(pulseKey) === "1"; } catch { return false; }
  });
  const closePulse = () => {
    setPulseOff(true);
    try { sessionStorage.setItem(pulseKey, "1"); } catch { /* private mode */ }
  };
  const complete = useMutation({
    mutationFn: () => api<Recap>(`/api/learn/subsections/${lessonId}/complete/`, { method: "POST" }),
    onError: (e) => {
      if (isOfflineError(e)) {
        offlineQueue.add({ key: `complete:${lessonId}`, url: `/api/learn/subsections/${lessonId}/complete/`, json: {} });
        setFinishQueued(true);
      }
    },
    onSuccess: (r) => {
      setRecap(r);
      celebrate(r.reward, { reducedMotion: me?.preferences.appearance.reduced_motion, invalidate: () => void qc.invalidateQueries({ queryKey: gameKey }) });
      void qc.invalidateQueries({ queryKey: ["course", Number(courseId)] });
      void qc.invalidateQueries({ queryKey: ["courses"] });
      void qc.invalidateQueries({ queryKey: ["adaptive-path", Number(courseId)] });
      if (r.passed === false) {
        mascot.react("hmm");
        mascot.say(t("adaptive.gate.say"), { ms: 5000 });
      } else if (r.score !== null && r.score >= 0.7) {
        sfx("levelup");
        mascot.react("celebrate");
        if (!me?.preferences.appearance.reduced_motion) void confetti({ particleCount: 140, spread: 80, origin: { y: 0.7 } });
      } else {
        mascot.react("cheer");
      }
      if (r.reward?.badges?.includes("first_lesson")) void offerPushAfterFirstLesson();
      window.scrollTo({ top: 0, behavior: "smooth" });
    },
  });

  if (notPublished) {
    return (
      <div className="flex flex-col items-center gap-4 px-4 py-20 text-center">
        <Kili mood="sleepy" size={130} />
        <p className="max-w-md">{t("lesson.notPublished")}</p>
        <Link to={`/learn/${courseId}`} className="font-semibold text-accent">{t("lesson.backToPath")}</Link>
      </div>
    );
  }
  if (!l || l.lesson_status === "generating" || l.lesson_status === "empty") {
    return (
      <div className="flex flex-col items-center gap-4 px-4 py-20 text-center">
        <Kili mood="thinking" size={150} color={me?.preferences.mascot.color} accessories={me?.preferences.mascot.accessories} outfit={me?.preferences.mascot.outfit} />
        <h1 className="font-display text-2xl font-bold">{t("lesson.preparing")}</h1>
        <p className="text-muted">{l?.title}</p>
      </div>
    );
  }
  if (l.lesson_status === "failed") {
    return (
      <div className="flex flex-col items-center gap-4 px-4 py-20 text-center">
        <Kili mood="confused" size={130} />
        <p>{t("lesson.failed")}</p>
        <Button onClick={() => void qc.resetQueries({ queryKey: ["lesson", lessonId] })}>{t("common.retry")}</Button>
      </div>
    );
  }

  if (recap?.passed === false) {
    // Adaptive course, below the pass mark: a short practice first, then finish this lesson.
    return (
      <div className="mx-auto max-w-2xl space-y-6 px-4 py-10">
        <Card className="flex flex-col items-center gap-3 text-center">
          <Kili mood="cheer" size={130} color={me?.preferences.mascot.color} accessories={me?.preferences.mascot.accessories} outfit={me?.preferences.mascot.outfit} />
          <h1 className="font-display text-2xl font-extrabold">{t("adaptive.gate.title")}</h1>
          {recap.score !== null && <p className="text-muted">{t("lesson.recapScore", { correct: recap.correct, count: recap.total })}</p>}
          <p className="max-w-md">{t("adaptive.gate.body")}</p>
        </Card>
        <div className="flex flex-wrap gap-3">
          <Button onClick={() => navigate(`/learn/${courseId}/lesson/${lessonId}/practice`)}>{t("adaptive.gate.practise")} <ArrowRight className="h-4 w-4" /></Button>
          <Button variant="outline" onClick={() => setRecap(null)}>{t("adaptive.gate.reread")}</Button>
          <Button variant="outline" onClick={() => navigate(`/learn/${courseId}`)}><ArrowLeft className="h-4 w-4" /> {t("lesson.backToPath")}</Button>
        </div>
      </div>
    );
  }

  if (recap) {
    // A reading-only lesson has no score (null): its recap shows no percentage instead of 0% or NaN.
    return (
      <div className="mx-auto max-w-2xl space-y-6 px-4 py-10">
        <Card className="flex flex-col items-center gap-3 text-center">
          <Kili mood={recap.score !== null && recap.score >= 0.7 ? "celebrate" : "cheer"} size={150} color={me?.preferences.mascot.color} accessories={me?.preferences.mascot.accessories} outfit={me?.preferences.mascot.outfit} />
          <PartyPopper className="h-8 w-8 text-accent" />
          <h1 className="font-display text-3xl font-extrabold">{t("lesson.recapTitle")}</h1>
          {recap.score !== null && <p className="font-display text-5xl font-extrabold text-accent">{Math.round(recap.score * 100)}%</p>}
          {recap.score !== null && <p className="text-muted">{t("lesson.recapScore", { correct: recap.correct, count: recap.total })}</p>}
        </Card>
        <Card>
          <h2 className="mb-2 font-display text-xl font-bold">{t("lesson.keyPoints")}</h2>
          <ul className="list-disc space-y-1 pl-5">{recap.key_points.map((k) => <li key={k}>{k}</li>)}</ul>
        </Card>
        <FeedbackSurveyPrompt survey={recap.feedback_survey} />
        <LessonFeedbackCard lessonId={l.id} />
        <AboutQuestion />
        <div className="flex flex-wrap gap-3">
          <Button variant="outline" onClick={() => navigate(`/learn/${courseId}`)}><ArrowLeft className="h-4 w-4" /> {t("lesson.backToPath")}</Button>
          <Button variant="outline" onClick={() => navigate(`/learn/${courseId}/lesson/${lessonId}/practice`)}>{t("practice.button")}</Button>
          <Button variant="outline" onClick={async () => {
            const sc = await roleplay.generate(t("rp.fromLesson", { title: l.title, objective: l.objective }), "easy").catch(() => null);
            if (sc) navigate(`/roleplay/${(await roleplay.start(sc.id)).id}`);
          }}>🎭 {t("rp.practise")}</Button>
          {recap.next_subsection_id && (
            <Button onClick={() => navigate(`/learn/${courseId}/lesson/${recap.next_subsection_id}`)}>
              {t("lesson.next")} <ArrowRight className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
    );
  }

  const answered = l.activities.filter((a) => a.attempt).length + graded;
  const shownLang = l.translation?.status === "ready" ? l.translation.lang : "";
  const readLang = shownLang || l.translation?.source || l.curriculum.language || "en";
  const showPulse = !pulseOff && l.activities.length >= 2 && answered >= Math.ceil(l.activities.length / 2) && answered < l.activities.length;
  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">
      <Link to={`/learn/${courseId}`} className="inline-flex items-center gap-1 text-sm font-medium text-muted hover:text-accent">
        <ArrowLeft className="h-4 w-4" /> {l.curriculum.title}
      </Link>
      <header>
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">{l.section.title}</p>
        <h1 className="font-display text-3xl font-extrabold">{l.title}</h1>
        <p className="text-muted">🎯 {l.objective}</p>
        {l.translation && (
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            <label className="flex items-center gap-1.5">
              <span className="text-muted">🌐 {t("translate.label")}</span>
              <select value={lang} onChange={(e) => updatePrefs.mutate({ learning: { lesson_language: e.target.value } })}
                className="rounded-lg border-2 border-line bg-surface px-2 py-1">
                <option value="">{t("translate.original", { lang: LANG_NAMES[l.translation.source] ?? l.translation.source })}</option>
                {l.translation.available.filter((c) => c !== l.translation!.source).map((c) => <option key={c} value={c}>{LANG_NAMES[c] ?? c}</option>)}
              </select>
            </label>
            {l.translation.status === "translating" && <span role="status" className="text-muted">{t("translate.working")}</span>}
            {l.translation.status === "failed" && <span role="alert" className="text-bad">{t("translate.failed")}</span>}
            {l.translation.status === "budget" && <span role="alert" className="text-bad">{t("translate.budget")}</span>}
            {l.translation.status === "ready" && <span className="text-xs text-muted">{t("translate.machine")}</span>}
          </div>
        )}
      </header>

      {l.state !== "completed" && <FastTrack lessonId={l.id} courseId={Number(courseId)} lang={readLang} autoOpen={fastParam} />}

      <Card className="py-3">
        <Toggle checked={kili} onChange={setKili} label={`${COMPANION_EMOJI[me?.preferences.mascot.character ?? "kili"] ?? "🦜"} ${t("lx.tutor.toggle")}`} />
        <p className="text-sm text-muted">{t("lx.tutor.sub")}</p>
      </Card>

      {kili ? (
        <TutorChat lessonId={l.id} lang={shownLang || undefined} onHandOver={() => document.getElementById("lx-activities")?.scrollIntoView({ behavior: "smooth" })} />
      ) : (
      <LessonTabs lessonId={l.id}>
      <Card>
        <ExplainSelection subsectionId={l.id} lang={l.translation?.status === "ready" ? lang : undefined}>
          <div className="prose-chat text-[1.05rem]">
            <Md>{l.explanation_md}</Md>
          </div>
        </ExplainSelection>
        <button
          type="button"
          onClick={() => setAsking(true)}
          aria-expanded={asking}
          className="mt-4 inline-flex items-center gap-2 rounded-xl border-2 border-line px-3 py-1.5 text-sm font-semibold hover:border-accent"
        >
          <MessageCircleHeart className="h-4 w-4 text-accent" /> {t("lesson.ask")}
        </button>
        <Link
          to={`/live?lesson=${l.id}`}
          className="ml-2 mt-4 inline-flex items-center gap-2 rounded-xl border-2 border-line px-3 py-1.5 text-sm font-semibold hover:border-accent"
        >
          <Video className="h-4 w-4 text-accent" /> {t("live.forLesson")}
        </Link>
        {asking && <LessonAsk question={t("lesson.askAbout", { title: l.title })} onClose={() => setAsking(false)} />}
      </Card>
      </LessonTabs>
      )}

      <LessonMedia features={me?.features} md={l.explanation_md} title={l.title} keyPoints={l.key_points} lang={readLang}
        lessonId={l.id} listened={listened} onListened={onListened} />

      <h2 id="lx-activities" className="scroll-mt-20 font-display text-xl font-bold">{t("lesson.practice")}</h2>
      {l.activities.map((a, i) => (
        <Fragment key={`${a.id}-${shownLang}-${a.attempt ? "done" : "open"}`}>
          <ActivityCard activity={a} index={i} hints lang={shownLang || undefined} onGraded={() => setGraded((g) => g + 1)} />
          {showPulse && i === Math.ceil(l.activities.length / 2) - 1 && <PulseCard lessonId={l.id} lang={shownLang || undefined} onClose={closePulse} />}
        </Fragment>
      ))}

      <Card className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted">{t("lesson.answered", { n: Math.min(answered, l.activities.length), count: l.activities.length })}</p>
        {finishQueued ? <p role="status" className="text-sm text-amber-800 dark:text-amber-200">{t("offline.finishSaved")}</p> : (
          <Button onClick={() => complete.mutate()} loading={complete.isPending}>
            {t("lesson.finish")} <ArrowRight className="h-4 w-4" />
          </Button>
        )}
      </Card>
    </div>
  );
}

/** Remount per lesson so recap/progress state never leaks between lessons. */
export default function LessonPage() {
  const { lessonId } = useParams();
  return <LessonView key={lessonId} />;
}
