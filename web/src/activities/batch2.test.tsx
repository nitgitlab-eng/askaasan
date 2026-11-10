import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DecisionTreeBody } from "./bodies2";
import { REGISTRY } from "./registry";
import { compile } from "./safeMath";

describe("safeMath", () => {
  it("evaluates whitelisted maths", () => {
    expect(compile("a*x^2 + b", ["x", "a", "b"])({ x: 3, a: 2, b: 1 })).toBe(19);
    expect(compile("-sqrt(x)+abs(-2)", ["x"])({ x: 9 })).toBe(-1);
  });
  it("rejects anything else", () => {
    for (const bad of ["alert(1)", "x;y", "constructor", "window", "y+1", "x.y"]) {
      expect(() => compile(bad, ["x"])).toThrow();
    }
  });
});

const TREE = {
  start: "s",
  nodes: {
    s: { text: "Start", choices: [{ id: "s.0", text: "Go on", next: "m" }, { id: "s.1", text: "Stop", next: "" }] },
    m: { text: "Middle", choices: [{ id: "m.0", text: "Finish", next: "" }, { id: "m.1", text: "Quit", next: "" }] },
  },
};

describe("decision tree", () => {
  it("walks the story and is ready only at an ending", () => {
    const set = vi.fn();
    render(<DecisionTreeBody payload={TREE} answer={{}} setAnswer={set} result={null} locked={false} />);
    fireEvent.click(screen.getByText("Go on"));
    expect(set).toHaveBeenCalledWith({ path: ["s.0"] });
    expect(REGISTRY.decision_tree.ready({ path: ["s.0"] }, TREE)).toBe(false);
    expect(REGISTRY.decision_tree.ready({ path: ["s.0", "m.0"] }, TREE)).toBe(true);
    expect(REGISTRY.decision_tree.ready({ path: ["s.1"] }, TREE)).toBe(true);
  });
});
