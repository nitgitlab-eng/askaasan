import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderPage } from "@/test/render";

import { CheckpointCard } from "./CheckpointCard";

const questions = [{ id: "q1", prompt: "What is UPI?", options: ["A payment system", "A bank"], lesson: "" }];

vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  api: vi.fn(async (path: string) => {
    if (path === "/api/study/courses/3/checkpoint/") return { status: "ready", questions, pre: null, post: null, gain: null };
    // The pre-test review no longer says which option was right, nor why.
    if (path === "/api/study/courses/3/checkpoint/submit/") return { status: "ready", questions, pre: { score: 0 }, post: null, gain: null, review: [{ id: "q1", picked: [1], ok: false, confidence: null }] };
    return null;
  }),
}));

describe("Checkpoint pre-test review without answers (HB)", () => {
  it("shows the result without crashing when correct/explanation are absent", async () => {
    const { container } = renderPage(<CheckpointCard courseId={3} progress={{ done: 0, total: 5 }} />);
    fireEvent.click(await screen.findByRole("button", { name: "Take the before-test" }));
    fireEvent.click(await screen.findByLabelText("A bank"));
    fireEvent.click(screen.getByRole("button", { name: /Submit|Check/ }));
    expect(await screen.findByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(container.querySelector(".bg-good\\/15")).toBeNull(); // no "right answer" highlight leaks
  });
});
