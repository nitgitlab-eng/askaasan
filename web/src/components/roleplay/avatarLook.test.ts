import { describe, expect, it } from "vitest";

import { avatarLook, hashString, inferEmotion, SKIN_TONES, TOP_COLOURS } from "./avatarLook";

describe("avatarLook", () => {
  it("is deterministic for the same character", () => {
    const a = avatarLook({ name: "Murugan", persona: "A friendly vegetable vendor", title: "Buying vegetables" });
    const b = avatarLook({ name: "Murugan", persona: "A friendly vegetable vendor", title: "Buying vegetables" });
    expect(a).toEqual(b);
  });

  it("ignores case and surrounding whitespace in the name", () => {
    expect(avatarLook({ name: "  Priya ", title: "Interview" })).toEqual(avatarLook({ name: "priya", title: "interview" }));
  });

  it("gives different characters different looks", () => {
    const names = ["Murugan", "Priya", "Ms. Fatima", "Rahul", "Lakshmi Aunty", "Mr. Joseph", "Kavya", "Arjun", "Selvi", "Ravi"];
    const looks = names.map((name) => JSON.stringify(avatarLook({ name, title: "Shop" })));
    expect(new Set(looks).size).toBe(names.length);
  });

  it("only uses palette colours", () => {
    for (const name of ["A", "B", "C", "D", "E", "F"]) {
      const l = avatarLook({ name });
      expect(SKIN_TONES).toContain(l.skin);
      expect(TOP_COLOURS).toContain(l.top);
      expect(l.trim).not.toBe(l.top);
    }
  });

  it("reads gender-neutral hints from the persona", () => {
    const f = avatarLook({ name: "Customer", persona: "She is an upset customer whose order is late" });
    expect(["bun", "long", "braid", "curly"]).toContain(f.hairStyle);
    expect(f.moustache).toBe(false);
    const m = avatarLook({ name: "Shopkeeper", persona: "He runs a small kirana store" });
    expect(m.dupatta).toBe(false);
    expect(m.bindi).toBe(false);
  });

  it("dresses interviewers formally (collar, no dupatta)", () => {
    const l = avatarLook({ name: "Anita", persona: "She is the HR interviewer at a bank", title: "Job interview" });
    expect(l.collar).toBe(true);
    expect(l.dupatta).toBe(false);
  });

  it("hash is stable", () => {
    expect(hashString("aasan")).toBe(hashString("aasan"));
    expect(hashString("aasan")).not.toBe(hashString("aasaN"));
  });
});

describe("inferEmotion", () => {
  it("thinks while waiting for a reply", () => {
    expect(inferEmotion("Thank you so much!", { waiting: true })).toBe("thinking");
  });
  it("is neutral for empty or plain text", () => {
    expect(inferEmotion("")).toBe("neutral");
    expect(inferEmotion(undefined)).toBe("neutral");
    expect(inferEmotion("The bus leaves at 5 pm.")).toBe("neutral");
  });
  it("smiles at friendly lines", () => {
    expect(inferEmotion("Welcome! Glad you came in today.")).toBe("happy");
    expect(inferEmotion("வணக்கம்! வாங்க, நன்றி.")).toBe("happy");
  });
  it("looks concerned at problems", () => {
    expect(inferEmotion("I'm sorry, but unfortunately the item is out of stock.")).toBe("concerned");
    expect(inferEmotion("மன்னிக்கவும், இது முடியாது.")).toBe("concerned");
  });
});
