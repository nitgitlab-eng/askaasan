import { HeartPulse, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Md } from "@/components/Md";
import { Button, Card } from "@/components/ui";
import { cn } from "@/lib/cn";
import { learner, type PulseReply } from "@/lib/learner";

type Pick = { pace?: string; difficulty?: string; energy?: string; relevant?: boolean | null };

/** Mid-lesson check-in: pace, difficulty, energy, "is this what you wanted?" → Kili adapts right away. */
export function PulseCard({ lessonId, lang, onClose }: { lessonId: number; lang?: string; onClose: () => void }) {
  const { t } = useTranslation();
  const [pick, setPick] = useState<Pick>({});
  const [wish, setWish] = useState("");
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState<PulseReply | null>(null);
  const row = (key: "pace" | "difficulty" | "energy", opts: string[]) => (
    <div className="flex flex-wrap items-center gap-2">
      <span className="w-28 text-sm font-medium">{t(`pulse.${key}`)}</span>
      {opts.map((o) => (
        <button key={o} type="button" aria-pressed={pick[key] === o} onClick={() => setPick((p) => ({ ...p, [key]: o }))}
          className={cn("rounded-full border-2 px-3 py-1 text-sm", pick[key] === o ? "border-accent bg-accent text-accent-ink" : "border-line")}>
          {t(`pulse.opts.${key}.${o}`)}
        </button>
      ))}
    </div>
  );
  async function send() {
    setBusy(true);
    try { setReply(await learner.pulse(lessonId, { ...pick, wish: wish.trim(), lang })); }
    catch { setReply({ saved: false, message: t("mentor.errors.generic"), tip: "", simpler: "", extra: "" }); }
    finally { setBusy(false); }
  }
  return (
    <Card className="space-y-3 border-accent/50">
      <header className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 font-display text-lg font-bold"><HeartPulse className="h-5 w-5 text-accent" /> {t("pulse.title")}</h2>
        <button type="button" aria-label={t("common.close")} onClick={onClose}><X className="h-5 w-5" /></button>
      </header>
      {!reply ? (
        <>
          {row("pace", ["slow", "ok", "fast"])}
          {row("difficulty", ["easy", "right", "hard"])}
          {row("energy", ["low", "ok", "high"])}
          <div className="flex flex-wrap items-center gap-2">
            <span className="w-28 text-sm font-medium">{t("pulse.relevant")}</span>
            {[true, false].map((v) => (
              <button key={String(v)} type="button" aria-pressed={pick.relevant === v} onClick={() => setPick((p) => ({ ...p, relevant: v }))}
                className={cn("rounded-full border-2 px-3 py-1 text-sm", pick.relevant === v ? "border-accent bg-accent text-accent-ink" : "border-line")}>
                {t(v ? "pulse.yes" : "pulse.no")}
              </button>
            ))}
          </div>
          {pick.relevant === false && (
            <input value={wish} onChange={(e) => setWish(e.target.value)} maxLength={300} placeholder={t("pulse.wish")}
              className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2" />
          )}
          <Button onClick={send} loading={busy} disabled={!Object.keys(pick).length}>{t("pulse.send")}</Button>
        </>
      ) : (
        <div className="space-y-2">
          <p>{reply.message}</p>
          {reply.tip && <p className="text-sm text-muted">💡 {reply.tip}</p>}
          {reply.simpler && <div className="rounded-xl bg-surface-2 p-3"><p className="mb-1 text-sm font-semibold">{t("pulse.simpler")}</p><div className="prose-chat"><Md ai>{reply.simpler}</Md></div></div>}
          {reply.extra && <div className="rounded-xl bg-surface-2 p-3"><p className="mb-1 text-sm font-semibold">{t("pulse.further")}</p><div className="prose-chat"><Md ai>{reply.extra}</Md></div></div>}
        </div>
      )}
    </Card>
  );
}
