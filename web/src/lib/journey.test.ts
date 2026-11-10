import { describe, expect, it, vi } from "vitest";

import { voicesFor } from "@/voice/narrator";

import { heardTracker, hostRoles, move, moveTo } from "./journey";

describe("move / moveTo", () => {
  it("moves up and down and ignores the edges", () => {
    expect(move([1, 2, 3], 1, -1)).toEqual([2, 1, 3]);
    expect(move([1, 2, 3], 1, 1)).toEqual([1, 3, 2]);
    const list = [1, 2, 3];
    expect(move(list, 0, -1)).toBe(list);
    expect(move(list, 2, 1)).toBe(list);
  });
  it("drags an item to a new position", () => {
    expect(moveTo(["a", "b", "c", "d"], 0, 2)).toEqual(["b", "c", "a", "d"]);
    expect(moveTo(["a", "b", "c"], 2, 0)).toEqual(["c", "a", "b"]);
    const l = ["a"];
    expect(moveTo(l, 0, 5)).toBe(l);
  });
});

describe("heardTracker", () => {
  it("reports the union of heard parts, de-duplicated, reaching 80%", () => {
    const report = vi.fn();
    const heard = heardTracker(report, 5);
    heard(0);
    expect(report).not.toHaveBeenCalled();
    heard(1);
    expect(report).toHaveBeenLastCalledWith([0, 1]);
    heard(1);
    heard(2);
    heard(3); // 4 of 5 = 80% → reported even though only 2 new since last time
    expect(report).toHaveBeenLastCalledWith([0, 1, 2, 3]);
  });
  it("always reports the last part", () => {
    const report = vi.fn();
    heardTracker(report, 10)(9);
    expect(report).toHaveBeenCalledWith([9]);
  });
});

describe("two hosts, two voices", () => {
  it("gives host A and host B different server voice roles (no pitch trick)", () => {
    const v = hostRoles([{ speaker: "A", text: "Hi" }, { speaker: "B", text: "Hello" }, { speaker: "A", text: "So?" }]);
    expect(v[0]).toEqual(v[2]);
    expect(v).toEqual(["host_a", "host_b", "host_a"]);
  });
  it("finds voices for a language, falling back to the base language", () => {
    const all = [{ lang: "en-US" }, { lang: "en-IN" }, { lang: "ta-IN" }, { lang: "en-GB" }] as SpeechSynthesisVoice[];
    expect(voicesFor(all, "en-IN").map((x) => x.lang)).toEqual(["en-IN"]);
    expect(voicesFor(all, "en-AU").map((x) => x.lang)).toEqual(["en-US", "en-IN", "en-GB"]);
    expect(voicesFor(all, "hi-IN")).toEqual([]);
  });
});
