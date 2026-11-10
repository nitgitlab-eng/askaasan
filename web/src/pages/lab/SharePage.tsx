import { useQuery } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Md } from "@/components/Md";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ActivityCard } from "@/activities/ActivityCard";
import type { ActivityData } from "@/activities/types";
import { Button, Card } from "@/components/ui";
import { api } from "@/lib/api";
import { Kili } from "@/mascot/Kili";
import { useAuth } from "@/stores/auth";

interface ShareInfo {
  id: number;
  title: string;
  description: string;
  cover_emoji: string;
  creator: string;
  lessons: number;
  level: string;
  sections: { title: string; lessons: string[] }[];
  enrolled: boolean;
  curriculum_id: number | null;
}

/** Public course page. Guests can play lesson 1 free; continuing needs an account. */
export default function SharePage() {
  const { t } = useTranslation();
  const { token } = useParams();
  const navigate = useNavigate();
  const access = useAuth((s) => s.access);
  const [guest, setGuest] = useState(false);
  const [done, setDone] = useState(0);
  const [busy, setBusy] = useState(false);
  const info = useQuery({ queryKey: ["share", token, !!access], queryFn: () => api<ShareInfo>(`/api/share/${token}/`), retry: false });
  const lesson = useQuery({
    queryKey: ["share-lesson", token],
    queryFn: () => api<{ title: string; explanation_md: string; activities: (ActivityData & { locked: boolean })[] }>(`/api/share/${token}/lesson/`),
    enabled: guest,
  });
  const next = encodeURIComponent(`/s/${token}`);

  async function enroll() {
    if (!access) return navigate(`/signup?next=${next}`);
    setBusy(true);
    try {
      const r = await api<{ curriculum_id: number }>(`/api/share/${token}/enroll/`, { method: "POST" });
      try {
        sessionStorage.setItem("aasan-joined-course", String(r.curriculum_id)); // onboarding returns here
      } catch {
        /* storage blocked: onboarding just builds a starter course */
      }
      navigate(`/learn/${r.curriculum_id}`);
    } finally {
      setBusy(false);
    }
  }

  if (info.isError) return <div className="flex min-h-dvh flex-col items-center justify-center gap-3 p-6 text-center"><Kili mood="confused" size={120} /><p>{t("share.notFound")}</p><Link to="/" className="font-semibold text-accent">Aasan</Link></div>;
  const c = info.data;
  if (!c) return <p className="p-8 text-muted">{t("common.loading")}</p>;

  return (
    <main className="mx-auto max-w-3xl space-y-6 px-4 py-10">
      <Card className="flex flex-col items-center gap-3 text-center">
        <span className="text-6xl">{c.cover_emoji}</span>
        <h1 className="font-display text-3xl font-extrabold">{c.title}</h1>
        <p className="text-muted">{c.description}</p>
        <p className="text-sm text-muted">{t("catalog.by", { name: c.creator })} · {t("catalog.lessons", { count: c.lessons })} · {t(`learn.levels.${c.level}`)}</p>
        <div className="flex flex-wrap justify-center gap-2">
          {c.enrolled && c.curriculum_id ? (
            <Button onClick={() => navigate(`/learn/${c.curriculum_id}`)}>{t("share.continue")}</Button>
          ) : (
            <>
              <Button onClick={enroll} loading={busy}>{access ? t("share.join") : t("share.signupToJoin")}</Button>
              {!access && !guest && <Button variant="outline" onClick={() => setGuest(true)}>{t("share.tryFree")}</Button>}
            </>
          )}
        </div>
      </Card>

      {!guest && (
        <Card>
          <h2 className="mb-2 font-display text-xl font-bold">{t("share.inside")}</h2>
          {c.sections.map((s) => (
            <div key={s.title} className="mb-2">
              <p className="font-semibold">{s.title}</p>
              <ul className="list-disc pl-5 text-sm text-muted">{s.lessons.map((l) => <li key={l}>{l}</li>)}</ul>
            </div>
          ))}
        </Card>
      )}

      {guest && lesson.data && (
        <>
          <Card>
            <p className="text-xs font-semibold uppercase text-muted">{t("share.freeLesson")}</p>
            <h2 className="font-display text-2xl font-bold">{lesson.data.title}</h2>
            <div className="prose-chat mt-2"><Md>{lesson.data.explanation_md}</Md></div>
          </Card>
          {lesson.data.activities.map((a, i) => a.locked ? (
            <Card key={a.id} className="flex items-center gap-3 text-muted"><Lock className="h-5 w-5" /> <span>{a.title} — {t("share.lockedForGuests")}</span></Card>
          ) : (
            <ActivityCard key={a.id} activity={a} index={i} submitUrl={`/api/share/${token}/attempt/${a.id}/`} onGraded={() => setDone((d) => d + 1)} />
          ))}
          {done > 0 && (
            <Card className="flex flex-col items-center gap-3 border-2 border-accent text-center">
              <Kili mood="celebrate" size={110} />
              <p className="font-display text-xl font-bold">{t("share.likedIt")}</p>
              <p className="text-muted">{t("share.signupPitch")}</p>
              <Button onClick={enroll}>{t("share.signupToJoin")}</Button>
            </Card>
          )}
        </>
      )}
    </main>
  );
}
