import i18n from "@/i18n";

import { api } from "./api";
import type { AuthPayload } from "./types";

/** Google Identity Services: the official sign-in button. Loaded only when the server has a client ID. */
export const GSI_SRC = "https://accounts.google.com/gsi/client";

export type GoogleAuthPayload = AuthPayload & { created: boolean };

export interface GoogleButtonOptions {
  type?: "standard" | "icon";
  theme?: "outline" | "filled_blue" | "filled_black";
  size?: "large" | "medium" | "small";
  text?: "signin_with" | "signup_with" | "continue_with" | "signin";
  shape?: "rectangular" | "pill" | "circle" | "square";
  width?: number;
  locale?: string;
}

export interface GoogleId {
  initialize(config: { client_id: string; callback: (response: { credential: string }) => void; ux_mode?: "popup" | "redirect"; itp_support?: boolean }): void;
  renderButton(parent: HTMLElement, options: GoogleButtonOptions): void;
}

declare global {
  interface Window {
    google?: { accounts: { id: GoogleId } };
  }
}

/** The public Google OAuth client ID, or "" when sign-in with Google is not set up on this server. */
export async function fetchGoogleClientId(): Promise<string> {
  const r = await api<{ google_client_id?: string }>("/api/users/auth-config/");
  return r?.google_client_id || "";
}

let loader: Promise<GoogleId> | null = null;

/** Loads the GIS script once; resolves with `google.accounts.id` as soon as it is on the page. */
export function loadGoogleIdentity(): Promise<GoogleId> {
  const ready = window.google?.accounts?.id;
  if (ready) return Promise.resolve(ready);
  loader ??= new Promise<GoogleId>((resolve, reject) => {
    const fail = () => {
      loader = null; // a later attempt (e.g. after the network comes back) tries again
      reject(new Error("gsi_unavailable"));
    };
    const s = document.createElement("script");
    s.src = GSI_SRC;
    s.async = true;
    s.defer = true;
    s.onload = () => (window.google?.accounts?.id ? resolve(window.google.accounts.id) : fail());
    s.onerror = fail;
    document.head.appendChild(s);
  });
  return loader;
}

/** Exchanges the Google ID token for an Aasan session (creates or links the account server-side). */
export function googleLogin(credential: string): Promise<GoogleAuthPayload> {
  return api<GoogleAuthPayload>("/api/users/google/", { method: "POST", json: { credential, language: i18n.language } });
}

/** The email inside a Google ID token (an unverified claim, used only to address a resend — the server verifies). */
export function emailFromCredential(credential: string): string {
  try {
    const payload = credential.split(".")[1] ?? "";
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    const email = (JSON.parse(json) as { email?: unknown }).email;
    return typeof email === "string" ? email : "";
  } catch {
    return "";
  }
}

/** Width for the Google button (GIS caps it at 400px): match the passkey button above it. */
export function buttonWidth(el: HTMLElement): number {
  return Math.min(400, Math.max(200, el.offsetWidth || 400));
}
