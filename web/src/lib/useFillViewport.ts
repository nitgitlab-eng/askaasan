import { useLayoutEffect, useState, type RefObject } from "react";

/**
 * Height that makes `ref` fill the screen from where it starts down to the bottom edge. A fixed `100dvh` ignored the
 * bars above the page (top bar, "Please verify your email" banner), so Ask Aasan's message box sat just below the
 * screen and new users thought chat was broken. Re-measured on resize and whenever the bars above change size.
 */
export function useFillViewport(ref: RefObject<HTMLElement | null>): number | undefined {
  const [height, setHeight] = useState<number>();
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const top = el.getBoundingClientRect().top + window.scrollY;
      setHeight(Math.max(320, Math.round(window.innerHeight - top)));
    };
    measure();
    window.addEventListener("resize", measure);
    // The banner can appear or disappear (e.g. after verifying), which moves this element.
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    if (el.parentElement) ro?.observe(el.parentElement);
    return () => {
      window.removeEventListener("resize", measure);
      ro?.disconnect();
    };
  }, [ref]);
  return height;
}
