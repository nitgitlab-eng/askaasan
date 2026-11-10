import { describe, expect, it } from "vitest";

import en from "./en";
import i18n from "./index";

/** Hand-built "(s)" plurals read badly ("1 survey(s)"); every count string uses _one / _other keys instead. */
describe("plural strings", () => {
  it("no English string uses a '(s)' plural", () => {
    const bad: string[] = [];
    const walk = (o: object, p: string) =>
      Object.entries(o).forEach(([k, v]) => (typeof v === "string" ? /\w\(s\)/.test(v) && bad.push(`${p}${k}`) : v && typeof v === "object" && walk(v, `${p}${k}.`)));
    walk(en, "");
    expect(bad).toEqual([]);
  });

  it("picks singular and plural by count", () => {
    const t = i18n.getFixedT("en");
    expect(t("org.surveyBanner", { count: 1 })).toBe("1 survey waiting for your answers");
    expect(t("org.surveyBanner", { count: 2 })).toBe("2 surveys waiting for your answers");
    expect(t("lx.artifact.kinds.images", { count: 1 })).toBe("At least 1 image");
    expect(i18n.getFixedT("ta")("survey.requiredN", { count: 3 })).toBe("3 கட்டாயக் கேள்விகள் மீதம்");
  });
});

describe("strings with two counts are split into separately pluralised parts", () => {
  const t = i18n.getFixedT("en");
  it("unit counts", () => {
    expect(`${t("school.units.classesN", { count: 1 })} · ${t("school.units.learnersN", { count: 5 })}`).toBe("1 class · 5 learners");
    expect(`${t("school.units.classesN", { count: 2 })} · ${t("school.units.learnersN", { count: 1 })}`).toBe("2 classes · 1 learner");
  });
  it("lesson meta and revision board", () => {
    expect(t("teach.lessonQuestions", { count: 1 })).toBe("1 question");
    expect(t("today.boardReviews", { count: 1 })).toBe("1 review");
    expect(t("today.boardStations", { count: 3 })).toBe("3 stations");
  });
  it("final reports", () => {
    expect(t("rca.finalReports", { met: t("rca.metTimes", { count: 1 }), notMet: t("rca.notMetTimes", { count: 2 }) })).toBe("Final reports: met 1 time, not met 2 times.");
  });
});
