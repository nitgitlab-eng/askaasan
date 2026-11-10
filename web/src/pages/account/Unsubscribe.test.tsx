import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderPage } from "@/test/render";

import Unsubscribe from "./Unsubscribe";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn(async () => ({ ok: true, category: "email_workshops" })) }));

describe("unsubscribe", () => {
  it("names the workshop email category", async () => {
    renderPage(<Unsubscribe />, { route: "/unsubscribe?t=abc" });
    expect(await screen.findByText(/Workshop emails:/)).toBeInTheDocument();
  });
});
