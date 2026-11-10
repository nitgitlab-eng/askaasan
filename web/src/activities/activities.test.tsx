import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CategorizationBody, ChoiceBody, FillBlankBody, MatchingBody } from "./bodies";
import { REGISTRY } from "./registry";

describe("activity readiness", () => {
  it("requires every blank / item / pair", () => {
    expect(REGISTRY.fill_blank.ready({ blanks: { "1": "x" } }, { blank_ids: ["1", "2"] })).toBe(false);
    expect(REGISTRY.fill_blank.ready({ blanks: { "1": "x", "2": "y" } }, { blank_ids: ["1", "2"] })).toBe(true);
    expect(REGISTRY.categorization.ready({ assign: { a: "X" } }, { items: [{}, {}] })).toBe(false);
    expect(REGISTRY.matching.ready({ pairs: { l0: "r0", l1: "r1" } }, { left: [{}, {}] })).toBe(true);
    expect(REGISTRY.quiz.ready({}, {})).toBe(false);
  });
});

describe("bodies", () => {
  it("single-choice quiz replaces the selection", () => {
    const set = vi.fn();
    render(<ChoiceBody payload={{ options: ["A1", "B1"], multiple: false }} answer={{ selected: [0] }} setAnswer={set} result={null} locked={false} />);
    fireEvent.click(screen.getByText("B1"));
    expect(set).toHaveBeenCalledWith({ selected: [1] });
  });

  it("fill-blank renders inputs at markers", () => {
    const set = vi.fn();
    render(<FillBlankBody payload={{ text: "AI learns from [[1]] and [[2]].", blank_ids: ["1", "2"] }} answer={{}} setAnswer={set} result={null} locked={false} />);
    fireEvent.change(screen.getByLabelText("Blank 2"), { target: { value: "data" } });
    expect(set).toHaveBeenCalledWith({ blanks: { "2": "data" } });
  });

  it("categorization: tap item then bucket", () => {
    const set = vi.fn();
    render(<CategorizationBody payload={{ categories: ["AI", "Not AI"], items: [{ id: "c0", text: "Spam filter" }] }} answer={{}} setAnswer={set} result={null} locked={false} />);
    fireEvent.click(screen.getByText("Spam filter"));
    fireEvent.click(screen.getByText("Not AI"));
    expect(set).toHaveBeenCalledWith({ assign: { c0: "Not AI" } });
  });

  it("matching: tap left then right, re-pairing frees the old pair", () => {
    const set = vi.fn();
    const payload = { left: [{ id: "l0", text: "Data" }, { id: "l1", text: "Model" }], right: [{ id: "r0", text: "Examples" }, { id: "r1", text: "Pattern" }] };
    render(<MatchingBody payload={payload} answer={{ pairs: { l1: "r0" } }} setAnswer={set} result={null} locked={false} />);
    fireEvent.click(screen.getByText("Data"));
    fireEvent.click(screen.getByText("Examples"));
    expect(set).toHaveBeenCalledWith({ pairs: { l0: "r0" } });
  });
});
