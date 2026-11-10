import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ArtifactCheckBody } from "@/activities/bodiesLx";
import { isHttpsUrl } from "@/activities/lxArtifact";
import { REGISTRY } from "@/activities/registry";

import { WidgetFrame } from "./InteractiveWidget";
import { ANSWER_TYPE, isWidgetFrameUrl, readWidgetAnswer, WIDGET_SANDBOX } from "./widgetFrame";

describe("AI widget sandbox", () => {
  const URL = "/api/learn/widgets/3/frame/?t=.eJyrVkrOT0lVslIqLU4tUqoFAC3NBQs:1u2:abc-_";
  it("renders only in a scripts-only sandboxed iframe loading our signed frame endpoint (no srcdoc)", () => {
    render(<WidgetFrame lessonId={7} widget={{ status: "ready", can_edit: false, title: "EMI", frame_url: URL, has_checkpoint: true, checkpoint_question: "EMI at 12%?" }} />);
    const frame = screen.getByTitle(/EMI/) as HTMLIFrameElement;
    expect(frame.tagName).toBe("IFRAME");
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    expect(frame.getAttribute("sandbox")).not.toMatch(/same-origin|forms|popups|top-navigation|modals/);
    expect(frame.getAttribute("src")).toBe(URL);
    expect(frame.getAttribute("srcdoc")).toBeNull();
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(screen.getByText(/EMI at 12%\?/)).toBeInTheDocument();
  });

  it("never frames anything but our widget endpoint", () => {
    expect(WIDGET_SANDBOX).toBe("allow-scripts");
    expect(isWidgetFrameUrl(URL)).toBe(true);
    for (const bad of ["https://evil.example/x", "//evil.example/api/learn/widgets/1/frame/?t=a", "javascript:alert(1)", "/api/learn/widgets/1/frame/?t=a&x=<", undefined, ""]) {
      expect(isWidgetFrameUrl(bad)).toBe(false);
    }
    render(<WidgetFrame lessonId={7} widget={{ status: "ready", can_edit: false, title: "Evil", frame_url: "https://evil.example/" }} />);
    expect((screen.getByTitle(/Evil/) as HTMLIFrameElement).getAttribute("src")).toBeNull();
  });

  it("accepts exactly one strictly-typed answer message from the frame (origin null)", () => {
    const frame = {} as Window;
    const ok = (data: unknown, extra: Partial<MessageEvent> = {}) => readWidgetAnswer({ origin: "null", source: frame, data, ...extra } as MessageEvent, frame);
    expect(ok({ type: ANSWER_TYPE, answer: 8885 })).toBe(8885);
    expect(ok({ type: ANSWER_TYPE, answer: " compound " })).toBe("compound");
    expect(ok({ type: ANSWER_TYPE, answer: 1 }, { origin: "https://evil.example" })).toBeNull();
    expect(ok({ type: ANSWER_TYPE, answer: 1 }, { source: {} as Window })).toBeNull();
    expect(readWidgetAnswer({ origin: "null", source: frame, data: { type: ANSWER_TYPE, answer: 1 } } as MessageEvent, null)).toBeNull();
    for (const bad of [null, "x", [1], { type: "other", answer: 1 }, { type: ANSWER_TYPE }, { type: ANSWER_TYPE, answer: 1, extra: 2 },
      { type: ANSWER_TYPE, answer: Number.NaN }, { type: ANSWER_TYPE, answer: Infinity }, { type: ANSWER_TYPE, answer: "x".repeat(101) },
      { type: ANSWER_TYPE, answer: "" }, { type: ANSWER_TYPE, answer: { v: 1 } }, { type: ANSWER_TYPE, answer: true }]) {
      expect(ok(bad)).toBeNull();
    }
  });
});

describe("artifact_check activity", () => {
  it("is ready only with an https:// address", () => {
    expect(isHttpsUrl("https://kavya.github.io/")).toBe(true);
    expect(isHttpsUrl("https://sites.google.com/view/kavya")).toBe(true);
    for (const u of ["http://kavya.github.io", "kavya.github.io", "https://", "https://user@x.io", "javascript:alert(1)", ""]) expect(isHttpsUrl(u)).toBe(false);
    expect(REGISTRY.artifact_check.ready({ url: "https://a.b" }, {})).toBe(true);
    expect(REGISTRY.artifact_check.ready({}, {})).toBe(false);
  });

  it("shows the checklist, takes a URL and lists what's missing after checking", () => {
    const set = vi.fn();
    const payload = { steps: ["Publish it"], checklist: [{ kind: "heading", value: "My projects", min_count: 1 }, { kind: "images", value: "", min_count: 2 }], n_checks: 2 };
    const { rerender } = render(<ArtifactCheckBody payload={payload} answer={{}} setAnswer={set} result={null} locked={false} />);
    expect(screen.getByText(/My projects/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "https://kavya.github.io" } });
    expect(set).toHaveBeenCalledWith({ url: "https://kavya.github.io" });
    rerender(<ArtifactCheckBody payload={payload} answer={{ url: "https://kavya.github.io" }} setAnswer={set} locked
      result={{ score: 0.5, correct: false, feedback: "", reveal: { status: "missing", missing: [{ kind: "images", value: "", min_count: 2 }] } }} />);
    expect(screen.getAllByText(/2 image/).length).toBe(2);
  });
});
