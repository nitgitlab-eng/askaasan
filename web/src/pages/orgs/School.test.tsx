import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { apiRoutes, renderPage } from "@/test/render";

import { SetupWithKili } from "./School";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

const long = "A".repeat(300) + "XYZ-MARKER" + "B".repeat(590);
const chat = {
  turns: 1,
  max_turns: 10,
  messages: [
    { role: "user", content: "hi" },
    { role: "assistant", content: "ok", proposals: [{ op: "set_description", title: "", text: long, roles: [], feature: "", on: false, why: "" }] },
  ],
};

describe("Set up with Kili approval (S34)", () => {
  const applied = vi.fn();
  beforeEach(() => {
    applied.mockReset();
    vi.mocked(api).mockReset();
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/orgs/acme/setup-chat/apply/": (init) => (applied(init?.json), chat), "/api/orgs/acme/setup-chat/": chat, "/api/": null }) as never);
  });

  it("shows the full proposal text the admin is approving", async () => {
    renderPage(<SetupWithKili slug="acme" />);
    expect(await screen.findByText(long)).toBeInTheDocument();
  });

  it("does not pre-select proposals", async () => {
    renderPage(<SetupWithKili slug="acme" />);
    const box = await screen.findByRole("checkbox");
    expect(box).not.toBeChecked();
    fireEvent.click(box);
    expect(box).toBeChecked();
  });

  it("applying without ticking accepts nothing", async () => {
    renderPage(<SetupWithKili slug="acme" />);
    await screen.findByRole("checkbox");
    fireEvent.click(screen.getByRole("button", { name: /Apply/ }));
    await waitFor(() => expect(applied).toHaveBeenCalled());
    expect(applied.mock.calls[0][0]).toMatchObject({ accept: [] });
  });
});
