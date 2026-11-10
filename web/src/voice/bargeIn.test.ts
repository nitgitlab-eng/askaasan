import { describe, expect, it } from "vitest";

import { decideBargeIn, hasWakeWord, isEcho, stripWake } from "./bargeIn";

const saying = ["A prompt is an instruction you give the AI."];

describe("barge-in decisions", () => {
  it("2+ new words interrupt; one word does not", () => {
    expect(decideBargeIn("wait no", [])).toBe("wake");
    expect(decideBargeIn("what about images", saying)).toBe("speech");
    expect(decideBargeIn("images", saying)).toBeNull();
  });

  it("an echo of what Aasan is saying is ignored", () => {
    expect(isEcho("an instruction you give", saying)).toBe(true);
    expect(decideBargeIn("prompt is an instruction", saying)).toBeNull();
    expect(isEcho("tell me about tokens", saying)).toBe(false);
  });

  it("a Tamil echo still counts when the recogniser changes endings or spacing", () => {
    const tamil = ["இது speaker-ல இருந்து வர்ற சத்தம் மைக்குல திரும்ப பதிவாகுற echo ஆ இருக்கலாம்.", "இன்னைக்கு என்ன படிக்கணும்?"];
    expect(isEcho("இது ஸ்பீக்கர்ல இருந்து வர சத்தம் மைக்ல திரும்ப பதிவாகுது", tamil)).toBe(true);
    expect(isEcho("இன்னைக்குஎன்ன படிக்கணும்", tamil)).toBe(true); // two words heard as one
    expect(isEcho("பதி வாகுற echo", tamil)).toBe(true); // one word heard as two
    expect(decideBargeIn("சத்தம் மைக்குல திரும்ப பதிவாகுது", tamil)).toBeNull();
    // The learner's own new question is not an echo, even with a word or two in common.
    expect(isEcho("இன்னைக்கு நான் பைத்தான் படிக்கணும்", tamil)).toBe(false);
    expect(decideBargeIn("எனக்கு loops புரியல", tamil)).toBe("speech");
  });

  it("zero-width marks and Unicode forms don't break the match", () => {
    expect(isEcho("ப​திவாகுற திரும்ப", ["திரும்ப பதிவாகுற"])).toBe(true);
    expect(isEcho("Instruction  YOU give!", saying)).toBe(true);
  });

  it("a stricter ratio for the moments after Aasan stops", () => {
    expect(isEcho("what is a prompt", saying)).toBe(true);
    expect(isEcho("what is a prompt", saying, 0.8)).toBe(false);
  });

  it("wake words in English and Tamil, with punctuation", () => {
    for (const t of ["Aasan", "aasan, wait", "Stop!", "ஆசான்", "நிறுத்து"]) expect(hasWakeWord(t)).toBe(true);
    expect(decideBargeIn("Aasan", saying)).toBe("wake");
    expect(hasWakeWord("stopwatch")).toBe(false);
  });

  it("Aasan saying “stop” itself is not a wake word", () => {
    const own = ["You can stop the timer at any point."];
    expect(decideBargeIn("stop the timer", own)).toBeNull();
    expect(decideBargeIn("stop", ["Tokens are pieces of words."])).toBe("wake");
  });

  it("strips leading wake words only", () => {
    expect(stripWake("Aasan, what is a token?")).toBe("what is a token?");
    expect(stripWake("Aasan wait. Explain again")).toBe("Explain again");
    expect(stripWake("ஆசான் இது என்ன")).toBe("இது என்ன");
    expect(stripWake("Aasan.")).toBe("");
    expect(stripWake("how do I stop it")).toBe("how do I stop it");
  });
});
