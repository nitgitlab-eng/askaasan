import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderPage } from "@/test/render";

import BossPage from "./Boss";

vi.mock("@/lib/api", async (orig) => {
  const real = await orig<typeof import("@/lib/api")>();
  return { ...real, api: vi.fn(async () => { throw new real.ApiError(404, { detail: "Not found." }); }) };
});

describe("Boss page errors (R21)", () => {
  it("a bad section shows not-found instead of Loading forever", async () => {
    renderPage(<BossPage />, { route: "/learn/1/boss/999", path: "/learn/:courseId/boss/:sectionId" });
    expect(await screen.findByText(/couldn't find that page/)).toBeInTheDocument();
    expect(screen.queryByText("Loading…")).toBeNull();
  });
});
