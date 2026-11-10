import { describe, expect, it } from "vitest";

import { layoutGraph, parseEmails, type KbGraph } from "./school";

const g: KbGraph = {
  documents: [{ id: 1, title: "Handbook" }, { id: 2, title: "Safety" }, { id: 3, title: "No topics" }],
  topics: [{ key: "leave policy", label: "Leave Policy", count: 1 }, { key: "safety", label: "Safety", count: 2 }],
  links: [{ doc: 1, topic: "leave policy" }, { doc: 1, topic: "safety" }, { doc: 2, topic: "safety" }, { doc: 2, topic: "unknown" }],
};

describe("layoutGraph", () => {
  it("places every node inside the box and links only known topics", () => {
    const { nodes, edges } = layoutGraph(g, 400);
    expect(nodes).toHaveLength(5);
    for (const n of nodes) {
      expect(n.x).toBeGreaterThanOrEqual(n.r);
      expect(n.x).toBeLessThanOrEqual(400 - n.r);
      expect(n.y).toBeGreaterThanOrEqual(n.r);
      expect(n.y).toBeLessThanOrEqual(400 - n.r);
    }
    expect(edges).toHaveLength(3);
    expect(edges.every((e) => nodes.some((n) => n.id === e.to))).toBe(true);
  });

  it("is deterministic and keeps nodes from overlapping much", () => {
    const a = layoutGraph(g), b = layoutGraph(g);
    expect(a).toEqual(b);
    const n = a.nodes;
    for (let i = 0; i < n.length; i++) for (let j = i + 1; j < n.length; j++) expect(Math.hypot(n[i].x - n[j].x, n[i].y - n[j].y)).toBeGreaterThan(n[i].r + n[j].r - 1);
  });

  it("copes with an empty graph", () => {
    expect(layoutGraph({ documents: [], topics: [], links: [] })).toEqual({ nodes: [], edges: [] });
  });
});

describe("parseEmails", () => {
  it("dedupes and lower-cases pasted addresses", () => {
    expect(parseEmails("A@x.in, b@y.com\nnot-an-email a@X.in")).toEqual(["a@x.in", "b@y.com"]);
  });
});
