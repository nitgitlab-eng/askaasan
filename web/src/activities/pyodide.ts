import i18n from "@/i18n";

/**
 * Runs learner Python in the browser (Pyodide, self-hosted under /pyodide/ and lazy-loaded on first run).
 *
 * The code may come from a course creator (starter code), so it never runs in the app's own window:
 * it runs in an <iframe sandbox="allow-scripts"> with an opaque origin. Python's `js` module there sees
 * only that empty frame — no app cookies, storage, access token or DOM, and same-origin API calls fail.
 * Code goes in and printed output comes out through postMessage; nothing else crosses.
 *
 * The frame is a real page (public/pyodide/runner.html), not srcdoc: a srcdoc frame inherits the app's CSP, which
 * would then need 'unsafe-eval' site-wide. nginx gives /pyodide/ its own CSP (eval + wasm allowed there only).
 */
const RUNNER = "/pyodide/runner.html";
const LOAD_TIMEOUT_MS = 90_000; // first load downloads the runtime (~10 MB)

type FromFrame = { type: "ready" } | { type: "failed"; error: string } | { type: "result"; id: number; stdout: string; error?: string };

let frame: { el: HTMLIFrameElement; ready: Promise<void> } | null = null;
let seq = 0;

const fromFrame = (el: HTMLIFrameElement, e: MessageEvent): FromFrame | null =>
  e.source === el.contentWindow && e.data && typeof e.data === "object" ? (e.data as FromFrame) : null;

/** Builds the sandboxed frame. Exported for tests. */
export function sandboxFrame(): HTMLIFrameElement {
  const el = document.createElement("iframe");
  el.setAttribute("sandbox", "allow-scripts"); // no allow-same-origin: the frame gets a unique opaque origin
  el.setAttribute("aria-hidden", "true");
  el.tabIndex = -1;
  el.title = "Python";
  el.style.display = "none";
  el.src = RUNNER;
  return el;
}

function destroy() {
  frame?.el.remove();
  frame = null;
}

function load(): Promise<HTMLIFrameElement> {
  if (!frame) {
    const el = sandboxFrame();
    const ready = new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => done(new Error("timeout")), LOAD_TIMEOUT_MS);
      const on = (e: MessageEvent) => {
        const d = fromFrame(el, e);
        if (d?.type === "ready") done();
        else if (d?.type === "failed") done(new Error(d.error));
      };
      const done = (err?: Error) => {
        clearTimeout(timer);
        window.removeEventListener("message", on);
        if (err) reject(err);
        else resolve();
      };
      window.addEventListener("message", on);
    });
    document.body.appendChild(el);
    frame = { el, ready };
  }
  const f = frame;
  return f.ready.then(() => f.el);
}

export async function runPython(code: string, timeoutMs = 8000): Promise<{ stdout: string; error?: string }> {
  let el: HTMLIFrameElement;
  try {
    el = await load();
  } catch {
    destroy();
    return { stdout: "", error: i18n.t("act.code.loadFailed") };
  }
  const id = ++seq;
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      window.removeEventListener("message", on);
      destroy(); // the only way to stop a runaway loop; the next run starts a fresh frame
      resolve({ stdout: "", error: i18n.t("act.code.stopped", { n: timeoutMs / 1000 }) });
    }, timeoutMs);
    const on = (e: MessageEvent) => {
      const d = fromFrame(el, e);
      if (d?.type !== "result" || d.id !== id) return;
      clearTimeout(timer);
      window.removeEventListener("message", on);
      const stdout = String(d.stdout ?? "").trimEnd();
      if (d.error === undefined) return resolve({ stdout });
      resolve({ stdout, error: String(d.error).split("\n").filter(Boolean).slice(-3).join("\n") });
    };
    window.addEventListener("message", on);
    el.contentWindow?.postMessage({ type: "run", id, code }, "*"); // the frame's origin is opaque, so "*" is the only target
  });
}
