import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";
import { apiRoutes, renderPage } from "@/test/render";

import AdminWorkshops from "./Workshops";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));
const apiMock = vi.mocked(api);
let orgsList: unknown;

beforeEach(() => {
  orgsList = [{ id: 1, slug: "acme", name: "Acme College", members: 80, workshops: false, workshop_seats: 0, seats_used: 0 }];
  apiMock.mockImplementation(apiRoutes({
    "/api/admin/workshops/orgs/1/": (init?: { json?: object }) => ({ id: 1, slug: "acme", name: "Acme College", workshops: false, workshop_seats: 0, ...init?.json }),
    "/api/admin/workshops/orgs/": () => {
      if (orgsList instanceof Error) throw orgsList;
      return orgsList;
    },
    "/api/admin/workshops/": [],
  }) as typeof api);
});
afterEach(() => apiMock.mockReset());

describe("admin: organisation workshop settings", () => {
  it("switches institution workshops on and sets a monthly seat cap", async () => {
    renderPage(<AdminWorkshops />);
    fireEvent.click(await screen.findByRole("tab", { name: "Organisations" }));
    const row = await screen.findByTestId("admin-org-acme");
    const sw = within(row).getByRole("switch", { name: "Institution workshops" });
    expect(sw).toHaveAttribute("aria-checked", "false");
    fireEvent.click(sw);
    await waitFor(() => expect(apiMock).toHaveBeenCalledWith("/api/admin/workshops/orgs/1/", { method: "PATCH", json: { workshops: true } }));
    await waitFor(() => expect(within(row).getByRole("switch", { name: "Institution workshops" })).toHaveAttribute("aria-checked", "true"));
    fireEvent.change(within(row).getByLabelText(/Workshop seats per month/), { target: { value: "abc" } });
    expect(within(row).getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.change(within(row).getByLabelText(/Workshop seats per month/), { target: { value: "500" } });
    fireEvent.click(within(row).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(apiMock).toHaveBeenCalledWith("/api/admin/workshops/orgs/1/", { method: "PATCH", json: { workshop_seats: 500 } }));
  });

  it("says so when the server doesn't offer the settings", async () => {
    orgsList = new ApiError(404, {});
    renderPage(<AdminWorkshops />);
    fireEvent.click(await screen.findByRole("tab", { name: "Organisations" }));
    expect(await screen.findByText("This server doesn't offer organisation workshop settings yet.")).toBeInTheDocument();
  });
});
