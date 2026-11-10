import { describe, expect, it } from "vitest";

import type { ChatChange, Question } from "./orgs";
import { applyChange, type Draft } from "./surveyChat";

const q = (id: string, text = id): Question => ({ id, type: "rating", text });
const draft: Draft = { title: "T", description: "", questions: [q("q1"), q("q2")] };

describe("applyChange", () => {
  it("adds after a question, or at the end", () => {
    const add: ChatChange = { id: "c1", op: "add", summary: "", after: "q1", question: { id: "q3", type: "text", text: "New", section: "Canteen" } };
    expect(applyChange(draft, add).questions.map((x) => x.id)).toEqual(["q1", "q3", "q2"]);
    expect(applyChange(draft, { ...add, after: "" }).questions.map((x) => x.id)).toEqual(["q1", "q2", "q3"]);
    expect(applyChange(draft, { ...add, after: "gone" }).questions.at(-1)?.section).toBe("Canteen");
  });
  it("never reuses an id that is taken", () => {
    const add: ChatChange = { id: "c1", op: "add", summary: "", question: { id: "q2", type: "text", text: "Dup" } };
    expect(applyChange(draft, add).questions.map((x) => x.id)).toEqual(["q1", "q2", "q3"]);
  });
  it("updates in place and keeps the id; ignores missing targets", () => {
    const upd: ChatChange = { id: "c1", op: "update", summary: "", target: "q2", question: { id: "zz", type: "scale", text: "S", min: 1, max: 5 } };
    const out = applyChange(draft, upd);
    expect(out.questions[1]).toMatchObject({ id: "q2", type: "scale", max: 5 });
    expect(applyChange(draft, { ...upd, target: "q9" })).toBe(draft);
  });
  it("removes, retitles, and does not mutate the input", () => {
    const out = applyChange(applyChange(draft, { id: "c", op: "remove", summary: "", target: "q1" }), { id: "d", op: "title", summary: "", text: "Short" });
    expect(out).toMatchObject({ title: "Short", questions: [{ id: "q2" }] });
    expect(draft.questions).toHaveLength(2);
    expect(draft.title).toBe("T");
  });
});
