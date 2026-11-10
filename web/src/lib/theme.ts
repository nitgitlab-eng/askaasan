import type { ThemeName } from "./types";

const DARK_QUERY = "(prefers-color-scheme: dark)";

function darkQuery(): MediaQueryList | null {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia(DARK_QUERY) : null;
}

/** What the device asks for right now: "dark" when it prefers a dark colour scheme, else "light". */
export function deviceTheme(): "light" | "dark" {
  return darkQuery()?.matches ? "dark" : "light";
}

/** The palette actually painted for a saved theme: "system" follows the device, everything else is itself. */
export function resolveTheme(theme: ThemeName): Exclude<ThemeName, "system"> {
  return theme === "system" ? deviceTheme() : theme;
}

let unsubscribe: (() => void) | null = null;

/**
 * Paints `theme` on <html data-theme>. For "system" it also follows the device live (the page flips when the
 * device setting changes) until the next call or the returned cleanup. Only one subscription exists at a time,
 * so the pre-login default in main.tsx is replaced, not doubled, once the learner's preferences load.
 */
export function applyTheme(theme: ThemeName): () => void {
  unsubscribe?.();
  unsubscribe = null;
  const root = document.documentElement;
  root.dataset.theme = resolveTheme(theme);
  if (theme !== "system") return () => undefined;
  const mql = darkQuery();
  if (!mql) return () => undefined;
  const onChange = (e: MediaQueryListEvent) => {
    root.dataset.theme = e.matches ? "dark" : "light";
  };
  mql.addEventListener("change", onChange);
  const stop = () => {
    mql.removeEventListener("change", onChange);
    if (unsubscribe === stop) unsubscribe = null;
  };
  unsubscribe = stop;
  return stop;
}
