import { describe, expect, it } from "vitest";

import i18n, { setMascotName } from "@/i18n";

import { companionName } from "./name";

describe("companionName", () => {
  it("shows default names in the reader's script and keeps custom names", () => {
    expect(companionName("mayil", "Mayil", "ta")).toBe("மயில்");
    expect(companionName("yaanai", "Yaanai", "en")).toBe("Yaanai");
    expect(companionName("kili", "Kili", "hi")).toBe("Kili");
    expect(companionName("mayil", "Kili", "en")).toBe("Mayil"); // default name follows the character
    expect(companionName("yaanai", "Appu", "ta")).toBe("Appu");
  });
});

describe("{{mascot}} in translations", () => {
  it("fills in the learner's companion", () => {
    setMascotName("Mayil");
    expect(i18n.t("lx.tutor.toggle", { defaultValue: "" }) || i18n.t("learn.building")).toContain("Mayil");
    setMascotName("Kili");
  });
});
