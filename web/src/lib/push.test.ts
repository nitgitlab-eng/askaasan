import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

import { deviceState, disablePush, enablePush, endpointForLogout, keyBytes, pushSupported } from "./push";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn(async () => ({})) }));

const ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc";

function fakeBrowser(permission: NotificationPermission, existing = false) {
  const unsubscribe = vi.fn(async () => true);
  const sub = { endpoint: ENDPOINT, unsubscribe, toJSON: () => ({ endpoint: ENDPOINT, keys: { p256dh: "P", auth: "A" } }) };
  let current: typeof sub | null = existing ? sub : null;
  const pushManager = {
    getSubscription: vi.fn(async () => current),
    subscribe: vi.fn(async () => (current = sub)),
  };
  const reg = { pushManager };
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: { getRegistration: vi.fn(async () => reg), register: vi.fn(async () => reg), ready: Promise.resolve(reg) },
  });
  vi.stubGlobal("PushManager", function PushManager() {});
  const N = Object.assign(function Notification() {}, { permission, requestPermission: vi.fn(async () => permission) });
  vi.stubGlobal("Notification", N);
  return { pushManager, unsubscribe };
}

describe("web push on this device", () => {
  beforeEach(() => vi.mocked(api).mockClear());
  afterEach(() => {
    vi.unstubAllGlobals();
    Reflect.deleteProperty(navigator, "serviceWorker");
  });

  it("decodes the VAPID key", () => {
    expect(Array.from(keyBytes("AQID"))).toEqual([1, 2, 3]);
    expect(keyBytes("BP-_").length).toBe(3);
  });

  it("is unsupported without a service worker and PushManager", async () => {
    expect(pushSupported()).toBe(false);
    expect(await deviceState({ enabled: true, public_key: "k", subscribed: false, devices: 0 })).toBe("unsupported");
  });

  it("reports server-off, denied, off and on", async () => {
    fakeBrowser("default");
    expect(await deviceState({ enabled: false, public_key: "", subscribed: false, devices: 0 })).toBe("off_server");
    expect(await deviceState({ enabled: true, public_key: "k", subscribed: false, devices: 0 })).toBe("off");
    fakeBrowser("denied");
    expect(await deviceState({ enabled: true, public_key: "k", subscribed: false, devices: 0 })).toBe("denied");
    fakeBrowser("granted", true);
    expect(await deviceState({ enabled: true, public_key: "k", subscribed: true, devices: 1 })).toBe("on");
  });

  it("subscribes after permission and sends the subscription to the server", async () => {
    const { pushManager } = fakeBrowser("granted");
    expect(await enablePush("AQID")).toBe("on");
    expect(pushManager.subscribe).toHaveBeenCalledWith(expect.objectContaining({ userVisibleOnly: true }));
    expect(api).toHaveBeenCalledWith("/api/users/push/subscriptions/", { method: "POST", json: { endpoint: ENDPOINT, keys: { p256dh: "P", auth: "A" } } });
  });

  it("does nothing when the learner says no", async () => {
    const { pushManager } = fakeBrowser("denied");
    expect(await enablePush("AQID")).toBe("denied");
    expect(pushManager.subscribe).not.toHaveBeenCalled();
    expect(api).not.toHaveBeenCalled();
  });

  it("turning off tells the server and drops the browser subscription", async () => {
    const { unsubscribe } = fakeBrowser("granted", true);
    await disablePush();
    expect(api).toHaveBeenCalledWith("/api/users/push/subscriptions/", { method: "DELETE", json: { endpoint: ENDPOINT } });
    expect(unsubscribe).toHaveBeenCalled();
  });

  it("hands the endpoint to sign-out", async () => {
    fakeBrowser("granted", true);
    expect(await endpointForLogout()).toBe(ENDPOINT);
  });
});
