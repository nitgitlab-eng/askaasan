import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { legal } from "@/lib/legal";
import { Kili } from "@/mascot/Kili";

import { consentReady, emptyConsent } from "@/lib/consent";

import { ConsentFields } from "./ConsentFields";

/** Shown once to anyone who hasn't accepted the current Terms (Google sign-ups, existing users, policy updates). */
export function ConsentGate({ updated }: { updated: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [v, setV] = useState(emptyConsent);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  async function go() {
    setBusy(true);
    setErr("");
    try {
      await legal.consent({ accept: v.accept, age_band: v.age_band as "adult" | "minor", guardian_email: v.guardian_email });
      await qc.invalidateQueries({ queryKey: ["me"] });
    } catch (e) {
      // A guardian email that hit the daily email cap is not a generic failure.
      setErr(e instanceof ApiError && e.status === 429 ? t("auth.tooManyEmails") : t("mentor.errors.generic"));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4">
      <div role="dialog" aria-modal="true" aria-labelledby="consent-title" className="w-full max-w-md space-y-4 rounded-3xl bg-surface p-6 shadow-xl">
        <div className="flex justify-center"><Kili mood="wave" size={88} /></div>
        <h2 id="consent-title" className="text-center font-display text-2xl font-bold">{updated ? t("legal.gateUpdated") : t("legal.gateTitle")}</h2>
        <p className="text-center text-sm text-muted">{t("legal.gateSub")}</p>
        <ConsentFields value={v} onChange={setV} />
        {err && <p role="alert" className="text-sm text-bad">{err}</p>}
        <Button className="w-full" disabled={!consentReady(v)} loading={busy} onClick={go}>{t("legal.continue")}</Button>
      </div>
    </div>
  );
}
