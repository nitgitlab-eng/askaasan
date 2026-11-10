import { describe, expect, it } from "vitest";

import { DEFAULT_VAD, VadMachine } from "./vad";
import { detectLang, SentenceStream, speakable } from "./text";

describe("detectLang", () => {
  it("picks Tamil for Tamil script, English otherwise", () => {
    expect(detectLang("ஜெனரேட்டிவ் AI என்றால் என்ன?")).toBe("ta");
    expect(detectLang("What is generative AI?")).toBe("en");
    expect(detectLang("Image, video மட்டும் இல்ல!")).toBe("ta");
  });
});

describe("speakable", () => {
  it("strips markdown and replaces code blocks", () => {
    expect(speakable("**Bold** and `x` [link](http://a) 🎉\n- item")).toBe("Bold and x link item");
    expect(speakable("Try:\n```py\nprint(1)\n```\nDone", "CODE")).toBe("Try: CODE Done");
  });
});

describe("SentenceStream", () => {
  it("early: a long first sentence starts at its first clause break; the rest splits on sentences", () => {
    const s = new SentenceStream(undefined, { early: true });
    const head = "Machine learning is a way for computers to learn from examples, ";
    expect(s.push(head)).toEqual(["Machine learning is a way for computers to learn from examples,"]);
    expect(s.push(`${head}not from rules, which makes`)).toEqual([]); // only the very first piece is early
    expect(s.flush(`${head}not from rules, which makes it flexible.`)).toEqual(["not from rules, which makes it flexible."]);
    expect(new SentenceStream().push(head)).toEqual([]); // off by default
    expect(new SentenceStream(undefined, { early: true }).push("Hi, there")).toEqual([]); // short: wait for the sentence
  });

  it("emits complete sentences as the text grows and flushes the tail", () => {
    const s = new SentenceStream();
    expect(s.push("Hello there")).toEqual([]);
    expect(s.push("Hello there. How are")).toEqual(["Hello there."]);
    expect(s.push("Hello there. How are you? I am")).toEqual(["How are you?"]);
    expect(s.flush("Hello there. How are you? I am Aasan")).toEqual(["I am Aasan"]);
  });

  it("holds an unclosed code fence until it closes", () => {
    const s = new SentenceStream();
    expect(s.push("Look at this. ```py\nprint(1)")).toEqual(["Look at this."]);
    const out = s.flush("Look at this. ```py\nprint(1)\n``` Nice!");
    expect(out.join(" ")).toContain("Nice!");
    expect(out.join(" ")).not.toContain("print");
  });

  it("never reads a code block, even one with sentences and blank lines inside", () => {
    const reply = "Here is the loop.\n\n```python\nfor i in range(3):\n    print(i). # done.\n\nx = 1\n```\n\nTry it yourself. What do you see?";
    const s = new SentenceStream("CODE");
    const spoken: string[] = [];
    for (let n = 1; n <= reply.length; n += 7) spoken.push(...s.push(reply.slice(0, n)));
    spoken.push(...s.flush(reply));
    const all = spoken.join(" ");
    expect(all).not.toMatch(/print|range|x = 1|`/);
    expect(spoken).toContain("CODE");
    expect(all).toContain("Here is the loop.");
    expect(all).toContain("What do you see?");
  });

  it("says the cue for a reply cut off inside a code block, and drops tables", () => {
    expect(speakable("See:\n```js\nlet a = 1", "CODE")).toBe("See: CODE");
    expect(speakable("Compare:\n| a | b |\n|---|---|\n| 1 | 2 |\nDone.")).toBe("Compare: Done.");
  });
});

describe("VadMachine", () => {
  const frames = (rms: number, ms: number) => Array.from({ length: ms / DEFAULT_VAD.frameMs }, () => rms);
  const run = (m: VadMachine, xs: number[]) => xs.map((x) => m.feed(x)).filter(Boolean);

  it("detects an utterance after quiet calibration", () => {
    const m = new VadMachine();
    expect(run(m, frames(0.003, 1000))).toEqual([]);
    expect(run(m, frames(0.2, 800))).toEqual(["speech-start"]);
    expect(run(m, frames(0.003, 1000))).toEqual(["speech-end"]);
  });

  it("ignores short blips and respects raised sensitivity", () => {
    const m = new VadMachine();
    run(m, frames(0.003, 1000));
    expect(run(m, [...frames(0.2, 80), ...frames(0.003, 1000)])).toEqual(["speech-start", "speech-cancel"]);
    m.sensitivity = 50;
    expect(run(m, frames(0.2, 500))).toEqual([]);
  });
});
