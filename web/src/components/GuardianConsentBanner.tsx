import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "@/lib/api";

/** Under-18s whose guardian hasn't approved yet: the AI features are locked server-side; this says why and resends. */
export function GuardianConsentBanner({ state }: { state: "pending" | "objected" }) {
  const { t } = useTranslation();
  const [msg, setMsg] = useState("");
  const resend = async () => {
    try {
      await api("/api/users/guardian/", { method: "POST", json: { action: "consent" } });
      setMsg(t("guardian.resent"));
    } catch (e) {
      setMsg(e instanceof ApiError && e.status === 429 ? t("guardian.recently") : t("errors.generic"));
    }
  };
  return (
    <div role="status" className="flex flex-wrap items-center justify-center gap-3 bg-amber-100 px-4 py-2 text-sm text-amber-900 dark:bg-amber-950/60 dark:text-amber-200">
      {state === "pending" ? t("guardian.pendingBanner") : t("guardian.objectedBanner")}
      {state === "pending" && (
        <button className="font-semibold underline" onClick={() => void resend()}>{t("guardian.resend")}</button>
      )}
      {msg && <span>{msg}</span>}
    </div>
  );
}
