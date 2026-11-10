import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Lock, Mail, Send } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ActivityCard } from "@/activities/ActivityCard";
import type { ActivityData } from "@/activities/types";
import { Md } from "@/components/Md";
import { Button, Card, Field } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { guestHeaders, guestToken, pub, type GuestLanding, type GuestRolePlay } from "@/lib/guests";
import { Kili } from "@/mascot/Kili";
import { useAuth } from "@/stores/auth";

const HEX = /^#[0-9a-fA-F]{6}$/;

function Frame({ brand, children }: { brand?: GuestLanding["brand"]; children: ReactNode }) {
  const color = brand?.color && HEX.test(brand.color) ? brand.color : undefined;
  return (
    <main className="mx-auto min-h-dvh max-w-2xl space-y-4 px-4 py-6 sm:py-10">
      <header className="flex items-center justify-between gap-3 border-b-4 pb-3" style={color ? { borderColor: color } : undefined}>
        <div className="flex min-w-0 items-center gap-2">
          {brand?.logo_url?.startsWith("/") && <img src={brand.logo_url} alt="" className="h-9 w-9 rounded-lg object-contain" />}
          <span className="truncate font-display text-lg font-bold">{brand?.name ?? "Aasan"}</span>
        </div>
        <span className="shrink-0 text-xs text-muted">Aasan · ஆசான்</span>
      </header>
      {children}
    </main>
  );
}

function Problem({ text }: { text: string }) {
  return (
    <Frame>
      <div className="flex flex-col items-center gap-3 py-10 text-center">
        <Kili mood="confused" size={110} />
        <p>{text}</p>
        <Link to="/" className="font-semibold text-accent">Aasan</Link>
      </div>
    </Frame>
  );
}

function codeOf(e: unknown): string {
  return e instanceof ApiError ? String(e.data?.code ?? e.status) : "";
}

function useLanding(slug: string) {
  return useQuery({ queryKey: ["guest-landing", slug], queryFn: () => pub.landing(slug), retry: false });
}

/** /g/:slug — landing: who made it, what's inside, start (optionally with name + email), resume via magic link. */
export default function GuestLandingPage() {
  const { t } = useTranslation();
  const { slug = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const magic = params.get("m");
  const [resuming, setResuming] = useState(!!magic);
  const [resumeErr, setResumeErr] = useState(false);
  const landing = useLanding(slug);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [mailed, setMailed] = useState(false);

  useEffect(() => {
    if (!magic) return;
    pub.resume(slug, magic)
      .then((r) => { guestToken.set(slug, r.token); void qc.invalidateQueries({ queryKey: ["guest-landing", slug] }); })
      .catch(() => setResumeErr(true))
      .finally(() => { setResuming(false); setParams({}, { replace: true }); });
  }, [magic, slug, qc, setParams]);

  if (landing.isError) {
    const c = codeOf(landing.error);
    return <Problem text={c.startsWith("link_") ? t(`guest.pub.${c}`) : t("guest.pub.notFound")} />;
  }
  const d = landing.data;
  if (!d || resuming) return <p className="p-8 text-muted">{t("common.loading")}</p>;
  const target = d.target;
  const lessons = target?.lessons ?? [];
  const done = new Set(d.me?.lessons_done ?? []);
  const nextLesson = lessons.find((l) => !done.has(l.id)) ?? lessons[0];

  async function start(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg("");
    try {
      const r = await pub.start(slug, d!.collect_email ? { name, email } : { name });
      if (r.token) guestToken.set(slug, r.token);
      if (r.code === "check_email") setMsg(t("guest.pub.checkEmail"));
      else {
        await qc.invalidateQueries({ queryKey: ["guest-landing", slug] });
        if (target?.kind === "roleplay") navigate(`/g/${slug}/role-play`);
        else if (nextLesson) navigate(`/g/${slug}/lesson/${nextLesson.id}`);
      }
    } catch (err) {
      const c = codeOf(err);
      setMsg(c.startsWith("link_") ? t(`guest.pub.${c}`) : c === "429" ? t("guest.pub.slowDown") : c === "name_email_required" ? t("guest.pub.needNameEmail") : t("guest.error"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Frame brand={d.brand}>
      {resumeErr && <p role="alert" className="rounded-xl bg-amber-100 px-3 py-2 text-sm text-amber-800">{t("guest.pub.badMagic")}</p>}
      <Card className="flex flex-col items-center gap-3 text-center">
        <span className="text-6xl" aria-hidden>{target?.cover_emoji}</span>
        <h1 className="font-display text-2xl font-extrabold sm:text-3xl">{target?.title}</h1>
        {target?.description && <p className="text-muted">{target.description}</p>}
        <p className="text-sm text-muted">{target?.kind === "roleplay" ? t("guest.pub.rpIntro", { who: target.character ?? "" }) : t("guest.pub.lessonsN", { count: lessons.length })}</p>
      </Card>

      {!d.me ? (
        d.state !== "ok" ? <Card className="text-center text-muted">{t(`guest.pub.link_${d.state}`)}</Card> : (
          <Card>
            <form onSubmit={start} className="space-y-3">
              <h2 className="font-display text-lg font-bold">{t("guest.pub.tryFree")}</h2>
              <Field label={d.collect_email ? t("guest.pub.name") : t("guest.pub.nameOptional")} value={name} maxLength={80} autoComplete="name" required={d.collect_email} onChange={(e) => setName(e.target.value)} />
              {d.collect_email && (
                <>
                  <Field label={t("guest.pub.email")} type="email" value={email} autoComplete="email" required onChange={(e) => setEmail(e.target.value)} />
                  <p className="text-xs text-muted">{t("guest.pub.emailWhy")} {t("guestSafe.resumeHint")}</p>
                </>
              )}
              {msg && <p role="status" className="text-sm">{msg}</p>}
              <Button type="submit" className="w-full" loading={busy}>{t("guest.pub.start")}</Button>
              <p className="text-center text-xs text-muted">{t("guest.pub.noAccount")}</p>
            </form>
          </Card>
        )
      ) : (
        <Card className="space-y-3">
          <p className="font-semibold">{d.me.name ? t("guest.pub.welcomeBack", { name: d.me.name }) : t("guest.pub.welcome")}</p>
          {target?.kind === "course" ? (
            <ul className="space-y-1">
              {lessons.map((l, i) => (
                <li key={l.id}>
                  <Link to={`/g/${slug}/lesson/${l.id}`} className="flex items-center gap-2 rounded-xl px-2 py-2 hover:bg-surface-2">
                    {done.has(l.id) ? <CheckCircle2 className="h-5 w-5 text-emerald-600" /> : <span className="flex h-5 w-5 items-center justify-center rounded-full bg-surface-2 text-xs">{i + 1}</span>}
                    <span>{l.title}</span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <Button className="w-full" onClick={() => navigate(`/g/${slug}/role-play`)}>{t("guest.pub.openRoleplay")}</Button>
          )}
          <div className="flex flex-wrap gap-2">
            {target?.kind === "course" && nextLesson && <Button onClick={() => navigate(`/g/${slug}/lesson/${nextLesson.id}`)}>{t("guest.pub.continue")}</Button>}
            <Button variant="outline" onClick={() => navigate(`/g/${slug}/done`)}>{t("guest.pub.finish")}</Button>
          </div>
          {d.me.has_email && (
            <Button variant="ghost" className="text-sm" disabled={mailed} onClick={async () => {
              try { await pub.emailLink(slug); setMailed(true); } catch (x) { const c = codeOf(x); setMsg(c === "mail_limit" ? t("guestSafe.mailLimit") : c === "email_not_configured" ? t("mailSetup.notReady") : c === "send_failed" ? t("mailSetup.sendFailed") : t("guest.pub.slowDown")); }
            }}><Mail className="h-4 w-4" /> {mailed ? t("guest.pub.mailed") : t("guest.pub.emailMe")}</Button>
          )}
          {msg && <p role="status" className="text-sm">{msg}</p>}
        </Card>
      )}
    </Frame>
  );
}

/** /g/:slug/lesson/:id — one lesson of the link's course, graded by the guest-safe attempt endpoint. */
export function GuestLessonPage() {
  const { t } = useTranslation();
  const { slug = "", id = "" } = useParams();
  const navigate = useNavigate();
  const landing = useLanding(slug);
  const lesson = useQuery({ queryKey: ["guest-lesson", slug, id], queryFn: () => pub.lesson(slug, Number(id)), retry: false, enabled: !!guestToken.get(slug) });
  const [busy, setBusy] = useState(false);
  const [nextErr, setNextErr] = useState("");
  if (!guestToken.get(slug)) return <Problem text={t("guest.pub.startFirst")} />;
  if (lesson.isError) {
    const c = codeOf(lesson.error);
    return <Problem text={c.startsWith("link_") ? t(`guest.pub.${c}`) : c === "401" || c === "guest_token_required" ? t("guest.pub.startFirst") : t("guest.pub.notFound")} />;
  }
  const l = lesson.data;
  if (!l) return <p className="p-8 text-muted">{t("common.loading")}</p>;

  async function next() {
    setBusy(true);
    setNextErr("");
    try {
      await pub.lessonDone(slug, l!.id);
      navigate(l!.next_id ? `/g/${slug}/lesson/${l!.next_id}` : `/g/${slug}/done`);
    } catch (e) {
      setNextErr(codeOf(e) === "answer_all_first" ? t("guestSafe.answerAll") : t("guest.error"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Frame brand={landing.data?.brand}>
      <Link to={`/g/${slug}`} className="text-sm font-semibold text-accent">← {landing.data?.target?.title ?? ""}</Link>
      <Card>
        <p className="text-xs font-semibold uppercase text-muted">{t("guest.pub.lessonOf", { n: l.position, total: l.total })}</p>
        <h1 className="font-display text-2xl font-bold">{l.title}</h1>
        <div className="prose-chat mt-2"><Md>{l.explanation_md}</Md></div>
      </Card>
      {l.activities.map((a, i) => a.locked ? (
        <Card key={a.id} className="flex items-center gap-3 text-muted"><Lock className="h-5 w-5 shrink-0" /> <span>{a.title} — {t("guest.pub.locked")}</span></Card>
      ) : (
        <ActivityCard key={a.id} activity={a as unknown as ActivityData} index={i} submitUrl={`/api/guests/public/${slug}/attempt/${a.id}/`} submitHeaders={guestHeaders(slug)} />
      ))}
      {nextErr && <p role="alert" className="text-sm text-bad">{nextErr}</p>}
      <Button className="w-full" loading={busy} onClick={next}>{l.next_id ? t("guest.pub.nextLesson") : t("guest.pub.finish")}</Button>
    </Frame>
  );
}

/** /g/:slug/role-play — a short guest conversation with the link's scenario (turns + daily AI capped server-side). */
export function GuestRolePlayPage() {
  const { t } = useTranslation();
  const { slug = "" } = useParams();
  const navigate = useNavigate();
  const landing = useLanding(slug);
  const [s, setS] = useState<GuestRolePlay | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [fatal, setFatal] = useState("");
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!guestToken.get(slug)) return;
    pub.startRoleplay(slug).then(setS).catch((e) => setFatal(codeOf(e)));
  }, [slug]);
  useEffect(() => end.current?.scrollIntoView?.({ behavior: "smooth", block: "end" }), [s?.turns.length]);

  if (!guestToken.get(slug)) return <Problem text={t("guest.pub.startFirst")} />;
  if (fatal) return <Problem text={fatal.startsWith("link_") ? t(`guest.pub.${fatal}`) : t("guest.pub.notFound")} />;
  if (!s) return <p className="p-8 text-muted">{t("common.loading")}</p>;

  const errText = (e: unknown) => {
    const c = codeOf(e);
    return c === "turn_limit" ? t("guest.pub.turnLimit") : c === "guest_ai_limit" ? t("guest.pub.aiLimit") : c === "too_short" ? t("guest.pub.tooShort") : c === "429" ? t("guest.pub.slowDown") : t("guest.error");
  };

  async function say(e: FormEvent) {
    e.preventDefault();
    const msg = text.trim();
    if (!msg) return;
    setBusy(true);
    setErr("");
    try {
      setS(await pub.say(slug, msg));
      setText("");
    } catch (x) {
      setErr(errText(x));
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    setBusy(true);
    setErr("");
    try {
      setS(await pub.endRoleplay(slug));
    } catch (x) {
      setErr(errText(x));
    } finally {
      setBusy(false);
    }
  }

  const sc = s.scenario;
  return (
    <Frame brand={landing.data?.brand}>
      <Card className="space-y-1">
        <h1 className="font-display text-xl font-bold">{sc.emoji} {sc.title}</h1>
        <p className="text-sm text-muted">{t("guest.pub.youPlay", { role: sc.learner_role })} · {sc.setting}</p>
        {!!sc.objectives.length && <ul className="list-disc pl-5 text-sm">{sc.objectives.map((o) => <li key={o}>{o}</li>)}</ul>}
      </Card>
      <div className="space-y-2" aria-live="polite">
        {s.turns.map((turn, i) => (
          <div key={i} className={cn("max-w-[85%] rounded-2xl px-4 py-2", turn.role === "learner" ? "ml-auto bg-accent text-accent-ink" : "bg-surface-2")}>
            {turn.role === "character" && <p className="text-xs font-semibold text-muted">{sc.character.name}</p>}
            {turn.role === "character" ? <div className="prose-chat"><Md ai>{turn.text}</Md></div> : <p className="whitespace-pre-wrap">{turn.text}</p>}
          </div>
        ))}
        {busy && <p className="text-sm text-muted">{t("guest.pub.typing", { name: sc.character.name })}</p>}
        <div ref={end} />
      </div>
      {s.status === "active" ? (
        <>
          <form onSubmit={say} className="flex gap-2">
            <input aria-label={t("guest.pub.yourReply")} className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2.5" value={text} maxLength={1000}
              placeholder={t("guest.pub.yourReply")} disabled={busy || s.turns_left <= 0} onChange={(e) => setText(e.target.value)} />
            <Button type="submit" aria-label={t("guest.pub.send")} loading={busy} disabled={s.turns_left <= 0}><Send className="h-4 w-4" /></Button>
          </form>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-muted">{t("guest.pub.turnsLeft", { count: s.turns_left })}</p>
            <Button variant="outline" disabled={busy} onClick={finish}>{t("guest.pub.endRoleplay")}</Button>
          </div>
        </>
      ) : s.result && (
        <Card className="space-y-2 border-2 border-accent">
          <p className="font-display text-3xl font-extrabold">{s.result.overall}/100</p>
          <p>{s.result.summary}</p>
          {!!s.result.strengths?.length && <><p className="font-semibold">{t("guest.pub.strengths")}</p><ul className="list-disc pl-5 text-sm">{s.result.strengths.map((x) => <li key={x}>{x}</li>)}</ul></>}
          {!!s.result.improvements?.length && <><p className="font-semibold">{t("guest.pub.improve")}</p><ul className="list-disc pl-5 text-sm">{s.result.improvements.map((x) => <li key={x}>{x}</li>)}</ul></>}
          <Button className="w-full" onClick={() => navigate(`/g/${slug}/done`)}>{t("guest.pub.finish")}</Button>
        </Card>
      )}
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
    </Frame>
  );
}

/** /g/:slug/done — summary + sign-up call to action; after sign-up the guest's progress moves into the account. */
export function GuestDonePage() {
  const { t } = useTranslation();
  const { slug = "" } = useParams();
  const access = useAuth((s) => s.access);
  const ready = useAuth((s) => s.ready);
  const hasToken = !!guestToken.get(slug);
  const summary = useQuery({
    queryKey: ["guest-summary", slug],
    queryFn: async () => { await pub.finish(slug); return pub.summary(slug); },
    enabled: hasToken, retry: false,
  });
  const [claimed, setClaimed] = useState<{ course_id: number | null } | null>(null);
  const [claimErr, setClaimErr] = useState(false);
  const claiming = useRef(false);

  useEffect(() => {
    if (!ready || !access || !hasToken || !summary.data || summary.data.me.claimed || claiming.current) return;
    claiming.current = true;
    pub.claim(slug).then((r) => { setClaimed(r); guestToken.clear(slug); }).catch(() => setClaimErr(true));
  }, [ready, access, hasToken, slug, summary.data]);

  if (!hasToken && !claimed) return <Problem text={t("guest.pub.startFirst")} />;
  if (summary.isError) return <Problem text={t("guest.pub.notFound")} />;
  const d = summary.data;
  if (!d) return <p className="p-8 text-muted">{t("common.loading")}</p>;
  const next = encodeURIComponent(`/g/${slug}/done`);

  return (
    <Frame brand={d.brand}>
      <Card className="flex flex-col items-center gap-3 text-center">
        <Kili mood="celebrate" size={110} />
        <h1 className="font-display text-2xl font-extrabold">{t("guest.pub.doneTitle")}</h1>
        <p className="text-muted">{d.target?.title}</p>
        <div className="grid w-full grid-cols-3 gap-2">
          <div className="rounded-xl bg-surface-2 p-3"><p className="text-xs text-muted">{t("guest.pub.answers")}</p><p className="text-xl font-bold">{d.answers}</p></div>
          <div className="rounded-xl bg-surface-2 p-3"><p className="text-xs text-muted">{t("guest.pub.correct")}</p><p className="text-xl font-bold">{d.correct}</p></div>
          <div className="rounded-xl bg-surface-2 p-3"><p className="text-xs text-muted">{d.roleplay ? t("guest.pub.rpScore") : t("guest.pub.lessonsDone")}</p>
            <p className="text-xl font-bold">{d.roleplay ? d.roleplay.overall : d.me.lessons_done.length}</p></div>
        </div>
        {d.roleplay?.summary && <p className="text-sm">{d.roleplay.summary}</p>}
      </Card>
      <Card className="flex flex-col items-center gap-3 border-2 border-accent text-center">
        {claimed || d.me.claimed ? (
          <>
            <p className="font-display text-lg font-bold">{t("guest.pub.saved")}</p>
            <Link to={claimed?.course_id ? `/learn/${claimed.course_id}` : "/"} className="rounded-xl bg-accent px-4 py-2 font-semibold text-accent-ink">{t("guest.pub.keepGoing")}</Link>
          </>
        ) : access ? (
          <p>{claimErr ? t("guest.error") : t("guest.pub.saving")}</p>
        ) : (
          <>
            <p className="font-display text-lg font-bold">{t("guest.pub.signupTitle")}</p>
            <p className="text-muted">{t("guest.pub.signupPitch")}</p>
            <Link to={`/signup?next=${next}`} className="w-full rounded-xl bg-accent px-4 py-2.5 font-semibold text-accent-ink">{t("guest.pub.signup")}</Link>
            <Link to={`/login?next=${next}`} className="text-sm font-semibold text-accent">{t("guest.pub.haveAccount")}</Link>
          </>
        )}
      </Card>
      <Link to={`/g/${slug}`} className="block text-center text-sm text-muted">← {t("guest.pub.back")}</Link>
    </Frame>
  );
}
