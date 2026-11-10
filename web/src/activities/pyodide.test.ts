import { afterEach, describe, expect, it, vi } from "vitest";

// A fresh module per test: the runner frame is cached at module level.
const load = async () => {
  vi.resetModules();
  return import("./pyodide");
};

/** Plays the sandboxed frame's side of the postMessage protocol. */
function fromFrame(frame: HTMLIFrameElement, data: unknown) {
  window.dispatchEvent(new MessageEvent("message", { data, source: frame.contentWindow }));
}
const frameEl = () => document.querySelector("iframe") as HTMLIFrameElement;

afterEach(() => {
  vi.useRealTimers();
  document.querySelectorAll("iframe").forEach((f) => f.remove());
});

describe("Python sandbox (S37)", () => {
  it("runs in an opaque-origin iframe: scripts only, never same-origin", async () => {
    const f = (await load()).sandboxFrame();
    expect(f.getAttribute("sandbox")).toBe("allow-scripts"); // no allow-same-origin
    expect(f.getAttribute("src")).toBe("/pyodide/runner.html"); // same-origin page with its own CSP, not srcdoc
    expect(f.srcdoc).toBe("");
  });

  it("never loads Pyodide into the app's own document", async () => {
    const { runPython } = await load();
    const run = runPython("print(1)");
    await Promise.resolve();
    expect(document.head.querySelector('script[src*="pyodide"]')).toBeNull();
    const f = frameEl();
    const post = vi.spyOn(f.contentWindow!, "postMessage");
    fromFrame(f, { type: "ready" });
    await vi.waitFor(() => expect(post).toHaveBeenCalled());
    const msg = post.mock.calls[0][0] as { id: number; code: string };
    expect(msg.code).toBe("print(1)"); // only the code goes in…
    fromFrame(f, { type: "result", id: msg.id, stdout: "1\n" }); // …and only printed output comes out
    expect(await run).toEqual({ stdout: "1" });
  });

  it("ignores messages that don't come from the sandbox frame", async () => {
    const { runPython } = await load();
    vi.useFakeTimers();
    const run = runPython("x", 1000);
    await Promise.resolve();
    window.dispatchEvent(new MessageEvent("message", { data: { type: "ready" }, source: window }));
    const f = frameEl();
    fromFrame(f, { type: "ready" });
    await vi.advanceTimersByTimeAsync(0);
    window.dispatchEvent(new MessageEvent("message", { data: { type: "result", id: 999, stdout: "spoof" }, source: window }));
    await vi.advanceTimersByTimeAsync(1100);
    const r = await run;
    expect(r.stdout).toBe("");
    expect(r.error).toMatch(/Stopped after 1s/);
    expect(document.querySelector("iframe")).toBeNull(); // a runaway run is killed with its frame
  });
});
