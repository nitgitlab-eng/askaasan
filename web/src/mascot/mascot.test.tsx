import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Kili } from "./Kili";
import { mascot, useMascot } from "./store";

afterEach(() => {
  vi.useRealTimers();
  act(() => useMascot.setState({ mood: "idle", bubble: null, character: "kili", look: {} }));
});

describe("mascot store", () => {
  it("transient moods fall back to idle", () => {
    vi.useFakeTimers();
    act(() => mascot.react("cheer"));
    expect(useMascot.getState().mood).toBe("cheer");
    act(() => vi.advanceTimersByTime(2300));
    expect(useMascot.getState().mood).toBe("idle");
  });

  it("persistent moods (ms=0) stay until changed", () => {
    vi.useFakeTimers();
    act(() => mascot.react("thinking", 0));
    act(() => vi.advanceTimersByTime(60_000));
    expect(useMascot.getState().mood).toBe("thinking");
  });

  it("say() shows a bubble then auto-hides", () => {
    vi.useFakeTimers();
    act(() => mascot.say("வணக்கம்", { ms: 1000 }));
    expect(useMascot.getState().bubble?.text).toBe("வணக்கம்");
    act(() => vi.advanceTimersByTime(1100));
    expect(useMascot.getState().bubble).toBeNull();
  });
});

describe("<Kili />", () => {
  it("renders accessories and mood props", () => {
    const { container, rerender } = render(<Kili mood="thinking" accessories={["glasses"]} outfit="veshti" />);
    expect(screen.getByRole("img", { name: "Kili" })).toBeInTheDocument();
    expect(container.querySelectorAll("circle").length).toBeGreaterThan(3); // thinking dots + eye
    rerender(<Kili mood="hmm" />);
    expect(container.textContent).toContain("?");
    rerender(<Kili mood="sleepy" />);
    expect(container.textContent).toContain("z");
  });
});

describe("<Kili /> wears the learner's look (R10)", () => {
  const body = (c: HTMLElement) => [...c.querySelectorAll("[fill]")].map((e) => e.getAttribute("fill"));

  it("uses the chosen colour when no colour prop is passed", () => {
    act(() => useMascot.getState().setLook({ color: "#0ea5e9", outfit: "none", accessories: [] }));
    const { container } = render(<Kili mood="idle" />);
    expect(body(container)).toContain("#0ea5e9");
  });

  it("an explicit colour still wins", () => {
    act(() => useMascot.getState().setLook({ color: "#0ea5e9" }));
    const { container } = render(<Kili mood="idle" color="#f43f5e" />);
    expect(body(container)).toContain("#f43f5e");
    expect(body(container)).not.toContain("#0ea5e9");
  });

  it("a preview of another companion doesn't borrow the learner's colour", () => {
    act(() => useMascot.getState().setLook({ color: "#0ea5e9" }));
    const { container } = render(<Kili mood="idle" character="yaanai" />);
    expect(body(container)).not.toContain("#0ea5e9");
  });
});
