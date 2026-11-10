import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { apiRoutes, renderPage } from "@/test/render";

import AdminCatalog from "./Catalog";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

const decide = vi.fn();

describe("Admin catalog reject (R19, R25)", () => {
  beforeEach(() => {
    decide.mockReset();
    vi.mocked(api).mockReset();
    vi.mocked(api).mockImplementation(
      apiRoutes({
        "/api/admin/catalog/7/": (init) => decide(init?.json),
        "/api/admin/catalog/": [{ id: 7, title: "UPI safety", description: "", cover_emoji: "📘", owner_email: "t@x.in", lessons: 1, share_token: "s" }],
      }) as never,
    );
  });

  it("Cancel in the reason dialog does not reject the course", async () => {
    renderPage(<AdminCatalog />);
    fireEvent.click(await screen.findByRole("button", { name: /Request changes/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(decide).not.toHaveBeenCalled();
  });

  it("confirming sends the reject with the typed note", async () => {
    renderPage(<AdminCatalog />);
    fireEvent.click(await screen.findByRole("button", { name: /Request changes/i }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Add sources" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /Request changes/i }));
    await waitFor(() => expect(decide).toHaveBeenCalledWith({ decision: "reject", note: "Add sources" }));
  });

  it("uses the singular for one lesson (R15)", async () => {
    renderPage(<AdminCatalog />);
    expect((await screen.findByText("t@x.in", { exact: false })).textContent).toContain("· 1 lesson ·");
  });
});
