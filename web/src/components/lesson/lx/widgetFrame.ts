/**
 * Security boundary for AI-written widgets. The widget runs ONLY in an iframe with
 * `sandbox="allow-scripts"` — no allow-same-origin (opaque "null" origin: no cookies, storage or
 * access to this page), no forms, popups, modals or top navigation. Its document comes from a
 * same-site endpoint (`/api/learn/widgets/<id>/frame/?t=<signed token>`) that sends its own CSP
 * (`sandbox allow-scripts; default-src 'none'; …`), so it is network-less and opaque even if opened
 * directly. (srcdoc is not used: it would inherit — and be blocked by — the app's own CSP.)
 * The server has already rejected network/eval/WebRTC code; a bootstrap removes WebRTC as well.
 */
export const WIDGET_SANDBOX = "allow-scripts";
export const ANSWER_TYPE = "aasan-widget-answer";

/** Only our own widget endpoint may be framed. */
export function isWidgetFrameUrl(u: string | undefined): u is string {
  return !!u && /^\/api\/learn\/widgets\/\d+\/frame\/\?t=[\w:.-]+$/.test(u);
}

/**
 * Accept exactly one message shape from exactly our sandboxed frame:
 * {type: "aasan-widget-answer", answer: finite number | short string}. Everything else → null.
 */
export function readWidgetAnswer(e: Pick<MessageEvent, "origin" | "source" | "data">, frame: Window | null | undefined): number | string | null {
  if (!frame || e.source !== frame || e.origin !== "null") return null;
  const d = e.data as unknown;
  if (!d || typeof d !== "object" || Array.isArray(d) || Object.getPrototypeOf(d) !== Object.prototype) return null;
  const keys = Object.keys(d);
  if (keys.length !== 2 || !keys.includes("type") || !keys.includes("answer")) return null;
  const { type, answer } = d as { type: unknown; answer: unknown };
  if (type !== ANSWER_TYPE) return null;
  if (typeof answer === "number") return Number.isFinite(answer) ? answer : null;
  if (typeof answer === "string") {
    const s = answer.trim();
    return s.length > 0 && s.length <= 100 ? s : null;
  }
  return null;
}
