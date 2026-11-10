import { fireEvent, screen, waitFor } from "@testing-library/react";
import { Link } from "react-router-dom";
import { expect, it, vi } from "vitest";

import { renderPage } from "@/test/render";

import ReviewHub from "./ReviewHub";

const card = (id: number, lesson: string) => ({
  card_id: id,
  lesson: { id, title: lesson },
  activity: { id, type: "quiz", title: `Q${id}`, payload: { prompt: "Pick one", options: ["A", "B"], multiple: false }, attempt: null },
});

let release: (v: unknown) => void = () => {};
let calls = 0;
vi.mock("@/lib/api", async (orig) => {
  const real = await orig<typeof import("@/lib/api")>();
  return {
    ...real,
    api: vi.fn(async (path: string) => {
      if (path.startsWith("/api/review/session/")) {
        calls += 1;
        // The first request answers last (slow network, the section changed, React's dev double effect); it must not replace the newer session.
        if (calls === 1) return new Promise((r) => (release = r)).then(() => ({ mode: "section", cards: [card(1, "Old lesson")] }));
        return { mode: "section", cards: [card(2, "New lesson")] };
      }
      if (path === "/api/review/overview/") return { due: 0, total: 0, reviewed_today: 0, by_course: [], next_due_at: null };
      return null;
    }),
  };
});

it("a late, older session response doesn't swap the cards the learner is answering", async () => {
  renderPage(<><Link to="/review?mode=section&section=6">other section</Link><ReviewHub /></>, { route: "/review?mode=section&section=5", path: "/review" });
  await waitFor(() => expect(calls).toBe(1));
  fireEvent.click(screen.getByText("other section")); // a second session request while the first is still out
  expect(await screen.findByText(/New lesson/)).toBeInTheDocument();
  release(null);
  await new Promise((r) => setTimeout(r, 20));
  expect(screen.getByText(/New lesson/)).toBeInTheDocument();
  expect(screen.queryByText(/Old lesson/)).toBeNull();
});
