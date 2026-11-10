import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";

import { ConsentFields } from "@/components/ConsentFields";
import { GoogleSignIn } from "@/components/GoogleSignIn";
import { consentReady, emptyConsent } from "@/lib/consent";
import { Button, Field } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useCompleteLogin } from "@/lib/auth";
import type { AuthPayload } from "@/lib/types";
import type { MascotMood } from "@/mascot/store";

import { AuthLayout } from "./AuthLayout";

export default function Signup() {
  const { t, i18n } = useTranslation();
  const complete = useCompleteLogin();
  const [params] = useSearchParams();
  const ref = params.get("ref") ?? "";
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [mood, setMood] = useState<MascotMood>("wave");
  const [consent, setConsent] = useState(emptyConsent);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const body = { ...Object.fromEntries(new FormData(e.currentTarget)), language: i18n.language === "en" ? "en" : "ta", ...(ref ? { ref } : {}), accept_terms: consent.accept, age_band: consent.age_band, guardian_email: consent.guardian_email };
    setBusy(true);
    setErrors({});
    setMood("thinking");
    try {
      const payload = await api<AuthPayload>("/api/users/register/", { method: "POST", json: body });
      setMood("celebrate");
      complete(payload);
    } catch (err) {
      setMood("hmm");
      const data = err instanceof ApiError ? (err.data as Record<string, string[]>) : null;
      if (err instanceof ApiError && err.status === 403 && err.data?.detail === "sso_required") {
        setErrors({ form: t("auth.sso.signupRequired", { org: String(err.data?.org || t("auth.sso.yourOrg")) }) });
        return;
      }
      setErrors({
        email: data?.email?.includes("email_taken") ? t("auth.emailTaken") : "",
        password: data?.non_field_errors || data?.password ? t("auth.weakPassword") : "",
        form: !data ? t("mentor.errors.generic") : "",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout title={t("auth.createAccount")} sub={t("auth.createSub")} mood={mood}>
      {ref && <p className="mb-3 rounded-xl bg-amber-100 px-3 py-2 text-sm text-amber-800">🎁 {t("game.invitedBonus")}</p>}
      <form onSubmit={submit} className="space-y-4" onFocus={() => setMood("watching")}>
        <Field label={t("auth.name")} name="display_name" autoComplete="name" />
        <Field label={t("auth.email")} name="email" type="email" autoComplete="email" required error={errors.email} />
        <Field label={t("auth.password")} name="password" type="password" autoComplete="new-password" minLength={8} required error={errors.password} />
        <ConsentFields value={consent} onChange={setConsent} />
        {errors.form && <p role="alert" className="text-sm text-bad">{errors.form}</p>}
        <Button type="submit" className="w-full" loading={busy} disabled={!consentReady(consent)}>
          {t("auth.signUp")}
        </Button>
      </form>
      <GoogleSignIn divider />
      <p className="mt-6 text-center text-sm">
        {t("auth.haveAccount")}{" "}
        <Link to={`/login${location.search}`} className="font-semibold text-accent hover:underline">
          {t("auth.signIn")}
        </Link>
      </p>
    </AuthLayout>
  );
}
