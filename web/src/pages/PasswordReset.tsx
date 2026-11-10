import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";

import { Button, Field } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useCompleteLogin } from "@/lib/auth";
import type { AuthPayload } from "@/lib/types";

import { AuthLayout } from "./AuthLayout";

const RESEND_SECONDS = 60;

/** Forgot password: email → the 6-digit code we mailed → a new password (then signed in). The mail also carries a
 *  /reset-password link, which skips the code step. */
export function ForgotPassword() {
  const { t } = useTranslation();
  const complete = useCompleteLogin();
  const [step, setStep] = useState<"email" | "code" | "password">("email");
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [wait, setWait] = useState(0);

  useEffect(() => {
    if (wait <= 0) return;
    const id = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(id);
  }, [wait]);

  async function sendCode(to: string) {
    setBusy(true);
    setError("");
    // Always 204, whether or not the address has an account.
    await api("/api/users/password-reset/request/", { method: "POST", json: { email: to } }).catch(() => {});
    setBusy(false);
    setWait(RESEND_SECONDS);
    setStep("code");
  }

  async function submitEmail(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const to = String(new FormData(e.currentTarget).get("email") || "").trim();
    setEmail(to);
    await sendCode(to);
  }

  async function submitCode(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const code = String(new FormData(e.currentTarget).get("code") || "").replace(/\D/g, "");
      const res = await api<{ token: string }>("/api/users/password-reset/verify-otp/", { method: "POST", json: { email, code } });
      setToken(res.token);
      setStep("password");
    } catch (err) {
      setError(err instanceof ApiError && err.data?.detail === "otp_locked" ? t("auth.otp.locked") : t("auth.otp.wrong"));
    } finally {
      setBusy(false);
    }
  }

  async function submitPassword(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const password = String(form.get("password") || "");
    if (password !== form.get("confirm")) {
      setError(t("auth.otp.mismatch"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      complete(await api<AuthPayload>("/api/users/password-reset/confirm/", { method: "POST", json: { token, password } }));
    } catch (err) {
      if (err instanceof ApiError && err.data?.detail === "invalid_token") {
        setError(t("auth.otp.expired"));
        setStep("email");
      } else {
        const why = err instanceof ApiError && Array.isArray(err.data?.password) ? (err.data.password as string[]).join(" ") : "";
        setError(why ? `${t("auth.weakPassword")}. ${why}` : t("auth.weakPassword"));
      }
    } finally {
      setBusy(false);
    }
  }

  const sub = step === "email" ? t("auth.resetSub") : step === "code" ? t("auth.otp.sent", { email }) : t("auth.otp.choose");
  return (
    <AuthLayout title={t("auth.resetTitle")} sub={sub} mood={error ? "hmm" : step === "email" ? "idle" : "cheer"}>
      {step === "email" && (
        <form onSubmit={submitEmail} className="space-y-4">
          <Field label={t("auth.email")} name="email" type="email" autoComplete="email" defaultValue={email} required error={error} />
          <Button type="submit" className="w-full" loading={busy}>{t("auth.otp.send")}</Button>
        </form>
      )}
      {step === "code" && (
        <form onSubmit={submitCode} className="space-y-4">
          <Field
            key="code"
            label={t("auth.otp.code")}
            name="code"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="\d{6}"
            maxLength={6}
            placeholder="••••••"
            className="text-center font-mono text-2xl tracking-[0.5em]"
            autoFocus
            required
            error={error}
          />
          <Button type="submit" className="w-full" loading={busy}>{t("auth.otp.verify")}</Button>
          <div className="flex items-center justify-between text-sm">
            <button type="button" className="font-medium text-accent hover:underline" onClick={() => { setError(""); setStep("email"); }}>
              {t("auth.otp.changeEmail")}
            </button>
            <button type="button" className="font-medium text-accent hover:underline disabled:text-muted disabled:no-underline" disabled={wait > 0 || busy} onClick={() => sendCode(email)}>
              {wait > 0 ? t("auth.otp.resendIn", { s: wait }) : t("auth.otp.resend")}
            </button>
          </div>
        </form>
      )}
      {step === "password" && (
        <form onSubmit={submitPassword} className="space-y-4">
          <Field key="password" label={t("auth.newPassword")} name="password" type="password" autoComplete="new-password" minLength={8} autoFocus required />
          <Field label={t("auth.otp.confirm")} name="confirm" type="password" autoComplete="new-password" minLength={8} required error={error} />
          <Button type="submit" className="w-full" loading={busy}>{t("auth.savePassword")}</Button>
        </form>
      )}
      <Link to="/login" className="mt-6 block text-center text-sm font-semibold text-accent">{t("common.back")}</Link>
    </AuthLayout>
  );
}

export function ResetPassword() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const complete = useCompleteLogin();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const password = new FormData(e.currentTarget).get("password");
      complete(await api<AuthPayload>("/api/users/password-reset/confirm/", { method: "POST", json: { token: params.get("token"), password } }));
    } catch (err) {
      const why = err instanceof ApiError && Array.isArray(err.data?.password) ? (err.data.password as string[]).join(" ") : "";
      setError(err instanceof ApiError && err.data?.detail === "invalid_token" ? t("auth.badLink") : why ? `${t("auth.weakPassword")}. ${why}` : t("auth.weakPassword"));
    } finally {
      setBusy(false);
    }
  }
  return (
    <AuthLayout title={t("auth.resetTitle")} mood={error ? "hmm" : "idle"}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t("auth.newPassword")} name="password" type="password" autoComplete="new-password" minLength={8} required error={error} />
        <Button type="submit" className="w-full" loading={busy}>{t("auth.savePassword")}</Button>
      </form>
    </AuthLayout>
  );
}

export function VerifyEmail() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const [state, setState] = useState<"pending" | "ok" | "bad">("pending");
  useEffect(() => {
    api("/api/users/email-verification/confirm/", { method: "POST", json: { token: params.get("token") } })
      .then(() => setState("ok"))
      .catch(() => setState("bad"));
  }, [params]);
  const title = state === "pending" ? t("auth.verifying") : state === "ok" ? t("auth.verified") : t("auth.badLink");
  return (
    <AuthLayout title={title} mood={state === "ok" ? "celebrate" : state === "bad" ? "hmm" : "thinking"}>
      <Link to="/" className="font-semibold text-accent">{t("nav.home")} →</Link>
    </AuthLayout>
  );
}
