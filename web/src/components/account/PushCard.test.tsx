import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import * as push from "@/lib/push";
import { useAuth } from "@/stores/auth";
import { apiRoutes, renderPage } from "@/test/render";

import { PushCard } from "./PushCard";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));
vi.mock("@/lib/push", async (orig) => ({
  ...(await orig<typeof import("@/lib/push")>()),
  pushSupported: vi.fn(() => true),
  deviceState: vi.fn(),
  enablePush: vi.fn(async () => "on"),
  disablePush: vi.fn(async () => undefined),
}));

const me = { email: "k@example.com", preferences: { notifications: { email_study: true, email_plan: true, kili_nudges: true, push_streak: false } } };

function setup(state: push.PushState, enabled = true, backoff: "normal" | "alternate" | "paused" = "normal") {
  vi.mocked(push.deviceState).mockResolvedValue(state);
  const reminders = { state: backoff, since: backoff === "normal" ? null : "2026-10-20T10:00:00Z", learned_time: null, time_chosen: false };
  vi.mocked(api).mockImplementation(
    apiRoutes({
      "/api/users/push/test/": { queued: true },
      "/api/users/push/reminders/resume/": () => {
        reminders.state = "normal";
        return { reminders };
      },
      "/api/users/push/": () => ({ enabled, public_key: "KEY", subscribed: state === "on", devices: state === "on" ? 1 : 0, reminders: { ...reminders } }),
      "/api/users/me/": me,
      "/api/users/preferences/": (init) => ({ ...me.preferences, ...(init?.json as object) }),
    }) as never,
  );
  return renderPage(<PushCard />);
}

describe("PushCard", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
    useAuth.setState({ access: "tok", signedIn: true });
  });

  it("stays hidden when the server has no push keys", async () => {
    const { container } = setup("off_server", false);
    await waitFor(() => expect(push.deviceState).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });

  it("turns on with the server's key", async () => {
    setup("off");
    fireEvent.click(await screen.findByRole("button", { name: "Turn on notifications" }));
    await waitFor(() => expect(push.enablePush).toHaveBeenCalledWith("KEY"));
  });

  it("explains a blocked permission", async () => {
    setup("denied");
    expect(await screen.findByText(/blocked for Aasan/)).toBeInTheDocument();
  });

  it("when on: per-kind toggles, a test and turning off", async () => {
    setup("on");
    const streak = await screen.findByRole("switch", { name: "Streak at risk" });
    expect(streak).toHaveAttribute("aria-checked", "false");
    fireEvent.click(streak);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/users/preferences/", { method: "PATCH", json: { notifications: { push_streak: true } } }));
    fireEvent.click(screen.getByRole("button", { name: "Send a test" }));
    expect(await screen.findByText(/Sent!/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Turn off on this device" }));
    await waitFor(() => expect(push.disablePush).toHaveBeenCalled());
    expect(await screen.findByRole("button", { name: "Turn on notifications" })).toBeInTheDocument();
  });

  it("explains paused reminders and resumes them", async () => {
    const { container } = setup("on", true, "paused");
    expect(await screen.findByText(/Reminders are paused because you didn't open/)).toBeInTheDocument();
    expect(container.querySelector("#push")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Resume reminders" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/users/push/reminders/resume/", { method: "POST" }));
    expect(await screen.findByText("Reminders are back to normal.")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText(/Reminders are paused/)).not.toBeInTheDocument());
  });

  it("says when reminders come every other day", async () => {
    setup("on", true, "alternate");
    expect(await screen.findByText(/now come every other day/)).toBeInTheDocument();
  });

  it("shows no banner when reminders are normal", async () => {
    setup("on");
    await screen.findByRole("switch", { name: "Streak at risk" });
    expect(screen.queryByRole("button", { name: "Resume reminders" })).not.toBeInTheDocument();
  });
});
