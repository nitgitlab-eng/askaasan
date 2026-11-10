import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { resendVerification, useCompleteLogin } from "@/lib/auth";
import { sso } from "@/lib/sso";

import { AuthLayout } from "./AuthLayout";

type Problem = "" | "accountUnverified" | "expired" | "domain" | "denied" | "tooMany" | "failed";

/** A state is single use: never send the same one twice (React may run the effect twice in development). */
const sent = new Set<string>();

/** Where the organisation's identity provider sends the browser back: finish the SSO sign-in. */
export default function SsoCallback() {
  const { t, i18n } = useTranslation();
  const complete = useCompleteLogin();
  const completeRef = useRef(complete);
  // A cancelled sign-in or a link without code/state needs no request: decided once, from the address.
  const [query] = useState(() => new URLSearchParams(location.search));
  const [problem, setProblem] = useState<Problem>(() => (query.get("error") ? "denied" : !query.get("code") || !query.get("state") ? "expired" : ""));
  const [email, setEmail] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    completeRef.current = complete;
  });

  useEffect(() => {
    const code = query.get("code") ?? "";
    const state = query.get("state") ?? "";
    if (query.get("error") || !code || !state || sent.has(state)) return;
    sent.add(state);
    sso
      .callback(code, state, i18n.language)
      .then((p) => completeRef.current(p, p.created ? { to: "/onboarding" } : undefined))
      .catch((err) => {
        if (!(err instanceof ApiError)) return setProblem("failed");
        if (err.status === 409) {
          setEmail(String(err.data?.email ?? ""));
          return setProblem("accountUnverified");
        }
        const code = String(err.data?.detail ?? "");
        if (code === "invalid_state") return setProblem("expired");
        if (code === "sso_domain_not_allowed" || code === "sso_tenant_mismatch") return setProblem("domain");
        setProblem(err.status === 429 ? "tooMany" : "failed");
      });
  }, [query, i18n.language]);

  return (
    <AuthLayout title={t("auth.sso.title")} mood={problem ? "hmm" : "thinking"}>
      {!problem && <p role="status" className="text-muted">{t("auth.sso.signingIn")}</p>}
      {problem && (
        <div className="space-y-3">
          <p role="alert" className="rounded-lg bg-bad/10 px-3 py-2 text-sm text-bad">
            {problem === "tooMany" ? t("auth.tooMany") : problem === "accountUnverified" ? t("auth.google.accountUnverified") : t(`auth.sso.err.${problem}`)}
          </p>
          {problem === "accountUnverified" && email && (
            <Button variant="outline" onClick={async () => setNotice(await resendVerification(email))}>{t("auth.sso.resend")}</Button>
          )}
          {notice && <p role="status" className="text-sm text-muted">{notice}</p>}
          <Link to="/login" className="block text-sm font-semibold text-accent hover:underline">{t("auth.sso.back")}</Link>
        </div>
      )}
    </AuthLayout>
  );
}
