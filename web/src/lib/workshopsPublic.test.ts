import { describe, expect, it } from "vitest";

import { blankRunForm, canEnrol, istParts, istToIso, joinPhase, runIcs, runSection, splitDuration, stageProgress, validateRunForm, type Run } from "./workshops";

const T0 = Date.parse("2026-11-01T10:00:00Z");
const min = 60_000;
const run = (over: Partial<Run> = {}): Run => ({
  id: 3, workshop: { slug: "prompting", title: "Prompt Engineering, live", summary: "Write; test, improve", level: "beginner", duration_minutes: 90 },
  starts_at: new Date(T0).toISOString(), status: "scheduled", price_paise: 0, enrolled: false, session_id: null, audience: "public",
  lobby_opens_at: new Date(T0 - 15 * min).toISOString(), join_opens_at: new Date(T0 - 15 * min).toISOString(), join_closes_at: new Date(T0 + 15 * min).toISOString(),
  ...over,
});

describe("join window", () => {
  it("walks before lobby → lobby → open → closed", () => {
    expect(joinPhase(run(), T0 - 60 * min)).toBe("before_lobby");
    expect(joinPhase(run(), T0 - 10 * min)).toBe("lobby");
    expect(joinPhase(run(), T0 + 5 * min)).toBe("open");
    expect(joinPhase(run(), T0 + 16 * min)).toBe("closed");
  });
  it("cancelled and ended runs are shut; test runs (no window) are open any time", () => {
    expect(joinPhase(run({ status: "cancelled" }), T0 - 60 * min)).toBe("cancelled");
    expect(joinPhase(run({ status: "ended" }), T0)).toBe("closed");
    expect(joinPhase(run({ lobby_opens_at: null, join_opens_at: null, join_closes_at: null }), T0 - 999 * min)).toBe("anytime");
  });
  it("sorts runs into sections; a started session always stays under My workshops", () => {
    expect(runSection(run(), T0 - 60 * min)).toBe("upcoming");
    expect(runSection(run({ enrolled: true }), T0 - 60 * min)).toBe("mine");
    expect(runSection(run({ my_status: "paid_pending" }), T0 - 60 * min)).toBe("mine");
    expect(runSection(run({ enrolled: true }), T0 + 60 * min)).toBe("past");
    expect(runSection(run({ enrolled: true, session_id: 4, status: "ended" }), T0 + 600 * min)).toBe("mine");
  });
  it("enrolment needs seats and an open window", () => {
    expect(canEnrol(run({ seats_left: 3 }), T0 - 60 * min)).toBe("ok");
    expect(canEnrol(run({ seats_left: 0 }), T0 - 60 * min)).toBe("full");
    expect(canEnrol(run(), T0 + 60 * min)).toBe("closed");
    expect(canEnrol(run({ status: "cancelled" }), T0)).toBe("cancelled");
  });
  it("splits a countdown", () => {
    expect(splitDuration(((26 * 60 + 5) * 60 + 9) * 1000)).toEqual({ d: 1, h: 2, m: 5, s: 9 });
    expect(splitDuration(-5)).toEqual({ d: 0, h: 0, m: 0, s: 0 });
  });
});

describe("calendar file", () => {
  it("has UTC start/end, escaped text, a link and a 15-minute reminder", () => {
    const ics = runIcs(run(), "https://aasan.app/workshops/3", new Date(T0 - 86_400_000));
    expect(ics).toContain("BEGIN:VCALENDAR\r\n");
    expect(ics).toContain("DTSTART:20261101T100000Z");
    expect(ics).toContain("DTEND:20261101T113000Z"); // 90 minutes
    expect(ics).toContain("SUMMARY:Prompt Engineering\\, live");
    expect(ics).toContain("DESCRIPTION:Write\\; test\\, improve\\nhttps://aasan.app/workshops/3");
    expect(ics).toContain("TRIGGER:-PT15M");
    expect(ics.split("\r\n").every((l) => l.length <= 75)).toBe(true);
  });
  it("uses ends_at when the server sends it", () => {
    expect(runIcs(run({ ends_at: "2026-11-01T12:00:00Z" }), "u")).toContain("DTEND:20261101T120000Z");
  });
});

describe("admin run form", () => {
  const now = Date.parse("2026-10-18T00:00:00Z");
  const good = { ...blankRunForm(), workshop_slug: "prompting", date: "2026-11-01", time: "15:30" };

  it("reads date and time as India time", () => {
    expect(istToIso("2026-11-01", "15:30")).toBe("2026-11-01T10:00:00.000Z");
    expect(istParts("2026-11-01T10:00:00Z")).toEqual({ date: "2026-11-01", time: "15:30" });
  });
  it("a free run sends price 0 and ignores the price box", () => {
    const { errors, body } = validateRunForm({ ...good, price: "abc" }, now);
    expect(errors).toEqual({});
    expect(body).toMatchObject({ workshop_slug: "prompting", starts_at: "2026-11-01T10:00:00.000Z", price_paise: 0, capacity: 0, late_join_minutes: 15, lobby_opens_minutes: 15 });
  });
  it("a paid run needs ₹1 to ₹10,000 and sends paise", () => {
    expect(validateRunForm({ ...good, paid: true, price: "" }, now).errors.price).toBe("price");
    expect(validateRunForm({ ...good, paid: true, price: "0.5" }, now).errors.price).toBe("price");
    expect(validateRunForm({ ...good, paid: true, price: "10000.01" }, now).errors.price).toBe("price");
    expect(validateRunForm({ ...good, paid: true, price: "499.50" }, now).body?.price_paise).toBe(49950);
    expect(validateRunForm({ ...good, paid: true, price: "1" }, now).body?.price_paise).toBe(100);
  });
  it("flags a missing template, a past start and out-of-range numbers", () => {
    const { errors, body } = validateRunForm({ ...good, workshop_slug: "", date: "2026-10-01", capacity: "5001", late_join_minutes: "61", lobby_opens_minutes: "4" }, now);
    expect(body).toBeNull();
    expect(errors).toEqual({ workshop_slug: "template", date: "past", capacity: "capacity", late_join_minutes: "late", lobby_opens_minutes: "lobby" });
    expect(validateRunForm({ ...good, time: "" }, now).errors.date).toBe("when");
  });
});

describe("stage progress", () => {
  const tick = (done: boolean) => ({ text: "x", done });
  const stages = [
    { key: "a", kind: "teach" as const, title: "A", minutes: 5, concepts: [tick(true), tick(true)], steps: [] },
    { key: "b", kind: "diy" as const, title: "B", minutes: 5, concepts: [], steps: [tick(true), tick(false)] },
    { key: "c", kind: "assessment" as const, title: "C", minutes: 5, concepts: [], steps: [] },
    { key: "d", kind: "teach" as const, title: "D", minutes: 5, concepts: [], steps: [] },
  ];
  it("counts finished stages plus the done share of the current one", () => {
    expect(stageProgress({ stages, stage_index: 0 })).toBe(50 / 2); // 2/2 of stage 1 → 1/4
    expect(stageProgress({ stages, stage_index: 1 })).toBe(38); // (1 + 0.5) / 4
    expect(stageProgress({ stages, stage_index: 4 })).toBe(100);
    expect(stageProgress({ stages: [], stage_index: 0 })).toBe(0);
  });
});
