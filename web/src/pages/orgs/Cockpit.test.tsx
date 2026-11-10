import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderPage } from "@/test/render";

import Cockpit from "./Cockpit";

vi.mock("@/lib/api", async (orig) => {
  const real = await orig<typeof import("@/lib/api")>();
  return {
    ...real,
    api: vi.fn(async (path: string) => {
      if (path === "/api/orgs/acme/") return { id: 1, slug: "acme", name: "Acme School", kind: "school", role: "admin", members: 3, groups: 1 };
      if (path === "/api/orgs/acme/analytics/") throw new real.ApiError(500, { detail: "boom" });
      return null;
    }),
  };
});

describe("Org cockpit errors (R21)", () => {
  it("a failed analytics load shows an error with Retry instead of Loading forever", async () => {
    renderPage(<Cockpit />, { route: "/org/acme", path: "/org/:slug" });
    expect(await screen.findByText(/Something went wrong while loading/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Retry/ })).toBeInTheDocument();
  });
});
