import { KeyRound } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { GoogleSignIn } from "@/components/GoogleSignIn";
import { OrgSignIn } from "@/components/OrgSignIn";
import { Button, Field } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { passkeyLogin, useCompleteLogin } from "@/lib/auth";
import { ssoAvailable } from "@/lib/sso";
import type { AuthPayload } from "@/lib/types";
import type { MascotMood } from "@/mascot/store";

import { AuthLayout } from "./AuthLayout";

export default function Login() {
  const { t } = useTranslation();
  const complete = useCompleteLogin();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [mood, setMood] = useState<MascotMood>("idle");
  const [orgSso, setOrgSso] = useState(false);
  const [ssoEmail, setSsoEmail] = useState<string | null>(null); // set when the password sign-in answered sso_required
  useEffect(() => {
    let alive = true;
    void ssoAvailable().then((on) => alive && setOrgSso(on));
    return () => {
      alive = false;
    };
  }, []);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    setMood("thinking");
    try {
      complete(await api<AuthPayload>("/api/users/login/", { method: "POST", json: Object.fromEntries(form) }));
    } catch (err) {
      setMood("hmm");
      if (err instanceof ApiError && err.status === 403 && err.data?.detail === "sso_required") {
        setSsoEmail(String(form.get("email") ?? ""));
        setError(t("auth.sso.required", { org: String(err.data?.org || t("auth.sso.yourOrg")) }));
        return;
      }
      setError(err instanceof ApiError && err.status === 401 ? t("auth.invalid") : err instanceof ApiError && err.status === 429 ? t("auth.tooMany") : t("mentor.errors.generic"));
    } finally {
      setBusy(false);
    }
  }

  async function withPasskey() {
    setError("");
    try {
      complete(await passkeyLogin());
    } catch {
      setMood("hmm");
      setError(t("auth.passkeyFailed"));
    }
  }

  return (
    <AuthLayout title={t("auth.welcome")} sub={t("auth.signInSub")} mood={mood}>
      <form onSubmit={submit} className="space-y-4" onFocus={() => setMood("watching")}>
        <Field label={t("auth.email")} name="email" type="email" autoComplete="email webauthn" required />
        <Field label={t("auth.password")} name="password" type="password" autoComplete="current-password" required />
        {error && (
          <p role="alert" className="rounded-lg bg-bad/10 px-3 py-2 text-sm text-bad">
            {error}
          </p>
        )}
        <div className="flex justify-end">
          <Link to="/forgot-password" className="text-sm font-medium text-accent hover:underline">
            {t("auth.forgot")}
          </Link>
        </div>
        <Button type="submit" className="w-full" loading={busy}>
          {t("auth.signIn")}
        </Button>
      </form>
      <div className="my-4 flex items-center gap-3 text-sm text-muted">
        <span className="h-px flex-1 bg-line" /> {t("auth.or")} <span className="h-px flex-1 bg-line" />
      </div>
      <Button variant="outline" className="w-full" onClick={withPasskey}>
        <KeyRound className="h-4 w-4" /> {t("auth.passkey")}
      </Button>
      <GoogleSignIn className="mt-3" />
      {(orgSso || ssoEmail !== null) && <OrgSignIn key={ssoEmail ?? ""} initialEmail={ssoEmail ?? ""} openInitially={ssoEmail !== null} />}
      <p className="mt-6 text-center text-sm">
        {t("auth.noAccount")}{" "}
        <Link to={`/signup${location.search}`} className="font-semibold text-accent hover:underline">
          {t("auth.signUp")}
        </Link>
      </p>
    </AuthLayout>
  );
}
