/** Web push on this device: ask permission, subscribe through the service worker and tell the server. */
import i18n from "@/i18n";
import { mascot } from "@/mascot/store";

import { api } from "./api";

/** Reminder back-off: "alternate" = every other day, "paused" = only "we miss you" (reminders went unopened). */
export interface ReminderStatus {
  state: "normal" | "alternate" | "paused";
  since: string | null;
  learned_time: string | null; // "HH:MM" the learner usually starts studying, once learned
  time_chosen: boolean;
}

export interface PushStatus {
  enabled: boolean;
  public_key: string;
  subscribed: boolean;
  devices: number;
  reminders?: ReminderStatus;
}

export type PushState = "unsupported" | "off_server" | "denied" | "off" | "on";

export const pushKey = ["push-status"] as const;
export const pushStatus = () => api<PushStatus>("/api/users/push/");

export function pushSupported(): boolean {
  return typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

/** VAPID public key (base64url) → the bytes PushManager.subscribe wants. */
export function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (base64url.length % 4)) % 4);
  const raw = atob((base64url + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function registration(): Promise<ServiceWorkerRegistration> {
  const reg = (await navigator.serviceWorker.getRegistration()) ?? (await navigator.serviceWorker.register("/sw.js"));
  await navigator.serviceWorker.ready;
  return reg;
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null;
  const reg = await navigator.serviceWorker.getRegistration();
  return (await reg?.pushManager.getSubscription()) ?? null;
}

/** The state of push on this device, given the server's answer. */
export async function deviceState(status: PushStatus | undefined): Promise<PushState> {
  if (!pushSupported()) return "unsupported";
  if (!status?.enabled) return "off_server";
  if (Notification.permission === "denied") return "denied";
  return (await currentSubscription()) && status.subscribed ? "on" : "off";
}

/** Ask permission and subscribe. → the resulting state ("denied" if the learner said no). */
export async function enablePush(publicKey: string): Promise<PushState> {
  if (!pushSupported()) return "unsupported";
  const perm = await Notification.requestPermission();
  if (perm !== "granted") return perm === "denied" ? "denied" : "off";
  const reg = await registration();
  const sub =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) }));
  const json = sub.toJSON();
  await api("/api/users/push/subscriptions/", { method: "POST", json: { endpoint: json.endpoint, keys: json.keys } });
  return "on";
}

/** Stop push on this device (server first, then the browser). */
export async function disablePush(): Promise<void> {
  const sub = await currentSubscription();
  if (!sub) return;
  try {
    await api("/api/users/push/subscriptions/", { method: "DELETE", json: { endpoint: sub.endpoint } });
  } finally {
    await sub.unsubscribe().catch(() => undefined);
  }
}

/** On sign-out: this device's endpoint, so the server can forget it (and the browser subscription is dropped). */
export async function endpointForLogout(): Promise<string | undefined> {
  try {
    const sub = await currentSubscription();
    if (!sub) return undefined;
    const endpoint = sub.endpoint;
    void sub.unsubscribe().catch(() => undefined);
    return endpoint;
  } catch {
    return undefined;
  }
}

export const sendTestPush = () => api("/api/users/push/test/", { method: "POST" });

/** Back to normal reminders after they were reduced or paused for going unopened. */
export const resumeReminders = () => api<{ reminders: ReminderStatus }>("/api/users/push/reminders/resume/", { method: "POST" });

/** After the first lesson: Kili offers reminders on this device, once, only if the browser hasn't been asked yet. */
export async function offerPushAfterFirstLesson(delayMs = 2500): Promise<boolean> {
  if (!pushSupported() || Notification.permission !== "default") return false;
  const st = await pushStatus().catch(() => null);
  if (!st?.enabled || st.subscribed) return false;
  const t = i18n.t.bind(i18n);
  setTimeout(() => {
    mascot.say(t("push.kiliPrompt"), {
      ms: 15_000,
      actions: [
        { label: t("push.turnOn"), onClick: () => void enablePush(st.public_key).then((s) => s === "on" && mascot.say(t("push.on"), { ms: 3000 })).catch(() => undefined) },
        { label: t("push.notNow"), onClick: () => mascot.hush() },
      ],
    });
  }, delayMs);
  return true;
}
