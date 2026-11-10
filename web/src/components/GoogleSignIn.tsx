import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { resendVerification, useCompleteLogin } from "@/lib/auth";
import { buttonWidth, emailFromCredential, fetchGoogleClientId, googleLogin, loadGoogleIdentity } from "@/lib/google";

type Problem = "" | "failed" | "emailUnverified" | "accountUnverified" | "tooMany" | "generic";

/**
 * The official "Continue with Google" button. Renders nothing at all until the server says a client ID is set, so a
 * server without Google sign-in shows no empty divider or broken button.
 */
export function GoogleSignIn({ divider = false, className = "" }: { divider?: boolean; className?: string }) {
  const { t, i18n } = useTranslation();
  const complete = useCompleteLogin();
  const [clientId, setClientId] = useState("");
  const [rendered, setRendered] = useState(false);
  const [problem, setProblem] = useState<Problem>("");
  const [email, setEmail] = useState("");
  const [notice, setNotice] = useState("");
  const slot = useRef<HTMLDivElement>(null);
  const completeRef = useRef(complete);
  useEffect(() => {
    completeRef.current = complete; // GIS keeps the callback we registered once; it must see the latest navigate/query client
  });

  useEffect(() => {
    let alive = true;
    fetchGoogleClientId()
      .then((id) => alive && setClientId(id))
      .catch(() => {}); // no answer → no button
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!clientId || !slot.current) return;
    let alive = true;
    const el = slot.current;
    const onCredential = async ({ credential }: { credential: string }) => {
      setProblem("");
      setNotice("");
      try {
        const payload = await googleLogin(credential);
        completeRef.current(payload, payload.created ? { to: "/onboarding" } : undefined);
      } catch (err) {
        if (!(err instanceof ApiError)) return setProblem("generic");
        if (err.status === 409) {
          setEmail(emailFromCredential(credential));
          return setProblem("accountUnverified");
        }
        if (err.status === 401) return setProblem(err.data?.detail === "google_email_unverified" ? "emailUnverified" : "failed");
        setProblem(err.status === 429 ? "tooMany" : "generic");
      }
    };
    loadGoogleIdentity()
      .then((gsi) => {
        if (!alive) return;
        gsi.initialize({ client_id: clientId, callback: onCredential, itp_support: true });
        gsi.renderButton(el, { type: "standard", theme: "outline", size: "large", text: "continue_with", shape: "rectangular", width: buttonWidth(el), locale: i18n.language });
        setRendered(true);
      })
      .catch(() => {}); // script blocked or offline: the page stays usable without the button
    return () => {
      alive = false;
    };
  }, [clientId, i18n.language]);

  if (!clientId) return null;

  const message = problem === "tooMany" ? t("auth.tooMany") : problem === "generic" ? t("mentor.errors.generic") : problem ? t(`auth.google.${problem}`) : "";
  return (
    <div className={className} data-testid="google-signin">
      {divider && (
        <div className="my-4 flex items-center gap-3 text-sm text-muted">
          <span className="h-px flex-1 bg-line" /> {t("auth.or")} <span className="h-px flex-1 bg-line" />
        </div>
      )}
      <div ref={slot} className="flex w-full justify-center" />
      {!rendered && (
        <Button variant="outline" className="w-full" disabled>
          {t("auth.google.continue")}
        </Button>
      )}
      {message && (
        <p role="alert" className="mt-3 rounded-lg bg-bad/10 px-3 py-2 text-sm text-bad">
          {message}
          {problem === "accountUnverified" && (
            <button type="button" className="ms-2 font-semibold underline" onClick={async () => setNotice(await resendVerification(email))}>
              {t("auth.resend")}
            </button>
          )}
        </p>
      )}
      {notice && (
        <p role="status" className="mt-2 text-sm text-muted">
          {notice}
        </p>
      )}
    </div>
  );
}
