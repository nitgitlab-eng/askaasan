import { Crown, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { PLAN_LIMIT_EVENT, type PlanLimitError } from "@/lib/billing";
import { Kili } from "@/mascot/Kili";

/** Friendly upgrade prompt shown whenever any feature hits a plan limit. */
export function PlanLimitSheet() {
  const { t } = useTranslation();
  const [hit, setHit] = useState<PlanLimitError | null>(null);
  useEffect(() => {
    const on = (e: Event) => setHit((e as CustomEvent<PlanLimitError>).detail);
    window.addEventListener(PLAN_LIMIT_EVENT, on);
    return () => window.removeEventListener(PLAN_LIMIT_EVENT, on);
  }, []);
  if (!hit) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center" onClick={() => setHit(null)}>
      <div role="dialog" aria-modal="true" aria-labelledby="plan-limit-title" className="relative w-full max-w-md space-y-3 rounded-3xl bg-surface p-6 text-center shadow-xl" onClick={(e) => e.stopPropagation()}>
        <button className="absolute right-4 top-4 text-muted hover:text-ink" onClick={() => setHit(null)} aria-label={t("common.back")}><X className="h-5 w-5" /></button>
        <div className="flex justify-center"><Kili mood="hmm" size={96} /></div>
        <h2 id="plan-limit-title" className="font-display text-2xl font-bold">{t("billing.sheet.title")}</h2>
        <p className="text-muted">{t(`billing.sheet.${hit.limit}`, { used: hit.used, max: hit.max })}</p>
        <Link to="/plans" onClick={() => setHit(null)} className="flex items-center justify-center gap-2 rounded-xl bg-accent px-4 py-3 font-bold text-accent-ink">
          <Crown className="h-5 w-5" /> {t("billing.sheet.cta")}
        </Link>
        <button className="text-sm text-muted hover:text-ink" onClick={() => setHit(null)}>{t("billing.sheet.later")}</button>
      </div>
    </div>
  );
}
