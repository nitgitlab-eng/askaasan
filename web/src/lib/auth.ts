import { startAuthentication } from "@simplewebauthn/browser";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import i18n from "@/i18n";
import { useAuth } from "@/stores/auth";

import { ApiError, api } from "./api";
import { promptDialog } from "./dialog";
import { clearOfflineData } from "./offline";
import { endpointForLogout } from "./push";
import { meKey } from "./useMe";
import type { AuthPayload } from "./types";

export function useCompleteLogin() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const setAccess = useAuth((s) => s.setAccess);
  return (p: AuthPayload, opts: { to?: string } = {}) => {
    void clearOfflineData(); // never show a previous person's offline copies
    setAccess(p.access); // the refresh token arrived as an HttpOnly cookie
    qc.setQueryData(meKey, p.user);
    // Only same-site relative paths (no protocol-relative or absolute URLs) — prevents open redirects.
    const next = new URLSearchParams(location.search).get("next");
    navigate(opts.to ?? (next && next.startsWith("/") && !next.startsWith("//") ? next : "/"), { replace: true });
  };
}

export async function passkeyLogin(): Promise<AuthPayload> {
  const { key, options } = await api<{ key: string; options: string }>("/api/users/passkey/authenticate/begin/", { method: "POST" });
  const credential = await startAuthentication({ optionsJSON: JSON.parse(options) });
  return api<AuthPayload>("/api/users/passkey/authenticate/complete/", { method: "POST", json: { key, credential } });
}

export function useLogout() {
  const qc = useQueryClient();
  const clear = useAuth((s) => s.clear);
  return async () => {
    try {
      const push_endpoint = await endpointForLogout(); // this device stops getting notifications for this account
      await api("/api/users/logout/", { method: "POST", ...(push_endpoint ? { json: { push_endpoint } } : {}) }); // revokes + clears the cookie
    } finally {
      clear();
      qc.clear();
      void clearOfflineData();
    }
  };
}

/**
 * Re-sends the email-verification link; returns the message to show (the server caps emails per day).
 * Signed out (Google sign-in met an unverified account), pass the address: the server mails it if it is unverified.
 */
export async function resendVerification(email?: string): Promise<string> {
  try {
    await api("/api/users/email-verification/request/", { method: "POST", ...(email ? { json: { email } } : {}) });
    return i18n.t("auth.verificationSent");
  } catch (e) {
    return e instanceof ApiError && e.status === 429 ? i18n.t("auth.tooManyEmails") : i18n.t("mentor.errors.generic");
  }
}

/**
 * Proves it's really the learner before a sensitive change (the server answered 403 reauth_required with `methods`).
 * Tries a passkey first, then the password, then an emailed code. On success the fresh session replaces the old one.
 * Resolves false if the learner cancels or every method fails.
 */
export async function reauthenticate(methods: string[]): Promise<boolean> {
  const done = (r: { access?: string }) => {
    if (r?.access) useAuth.getState().setAccess(r.access);
    return true;
  };
  if (methods.includes("passkey")) {
    try {
      const { key, options } = await api<{ key: string; options: string }>("/api/users/passkey/authenticate/begin/", { method: "POST" });
      const credential = await startAuthentication({ optionsJSON: JSON.parse(options) });
      return done(await api<{ access?: string }>("/api/users/reauth/", { method: "POST", json: { key, credential } }));
    } catch {
      /* cancelled or not this device: fall through to the next method */
    }
  }
  if (methods.includes("password")) {
    const password = await promptDialog(i18n.t("passkeys.passwordPrompt"), { ok: i18n.t("passkeys.reauthTitle") });
    if (!password) return false;
    try {
      return done(await api<{ access?: string }>("/api/users/reauth/", { method: "POST", json: { password } }));
    } catch {
      return false;
    }
  }
  if (methods.includes("email_code")) {
    try {
      await api("/api/users/reauth/", { method: "POST", json: {} }); // 202: the code is on its way
      const code = await promptDialog(i18n.t("passkeys.codePrompt"), { ok: i18n.t("passkeys.reauthTitle") });
      if (!code) return false;
      return done(await api<{ access?: string }>("/api/users/reauth/", { method: "POST", json: { code: code.replace(/\D/g, "") } }));
    } catch {
      return false;
    }
  }
  return false;
}
