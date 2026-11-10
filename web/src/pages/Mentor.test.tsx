import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";

import type { ChatMsg } from "@/lib/useMentorSocket";

import MentorPage from "./Mentor";

vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  api: vi.fn(async (path: string) => (path === "/api/assistant/conversations/5/" ? { messages: [{ id: 1, role: "assistant", content: "Old answer from chat 5" }] } : null)),
}));

const seen: (number | null)[] = [];
vi.mock("@/lib/useMentorSocket", () => ({
  useMentorSocket: (opts: { conversationId: number | null }) => {
    seen.push(opts.conversationId);
    const [messages, setMessages] = useState<ChatMsg[]>([]);
    return { status: "connecting", messages, setMessages, busy: false, error: null, send: () => false, cancel: () => {}, retry: () => false };
  },
}));

function Nav() {
  const navigate = useNavigate();
  return <button onClick={() => navigate("/mentor")}>go-new</button>;
}

describe("Mentor follows the URL (R22)", () => {
  it("/mentor/5 → /mentor starts a fresh conversation", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/mentor/5"]}>
          <Nav />
          <Routes>
            <Route path="/mentor" element={<MentorPage />} />
            <Route path="/mentor/:id" element={<MentorPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Old answer from chat 5")).toBeInTheDocument();
    fireEvent.click(screen.getByText("go-new"));
    await waitFor(() => expect(screen.queryByText("Old answer from chat 5")).toBeNull());
    expect(seen.at(-1)).toBeNull();
  });
});

describe("Ask Aasan shows what it's doing", () => {
  it("says it is connecting instead of just greying out Send", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/mentor"]}>
          <Routes>
            <Route path="/mentor" element={<MentorPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/connecting to aasan/i)).toBeInTheDocument();
  });
});

