import { useEffect, useRef, type RefObject } from "react";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

/**
 * Modal drawer keyboard behaviour: focus moves into the panel when it opens, Tab and Shift+Tab stay inside it,
 * Escape closes it, and focus goes back to whatever opened it when it closes.
 */
export function useDialogFocus(panel: RefObject<HTMLElement | null>, onClose: () => void) {
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const items = () => Array.from(panel.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    (items()[0] ?? panel.current)?.focus();
    const onKey = (e: KeyboardEvent) => {
      // A confirm dialog opened from inside the panel handles its own keys.
      const modal = document.activeElement instanceof HTMLElement ? document.activeElement.closest('[aria-modal="true"]') : null;
      if (modal && modal !== panel.current) return;
      if (e.key === "Escape") {
        close.current();
        return;
      }
      if (e.key !== "Tab" || !panel.current) return;
      const list = items();
      if (!list.length) {
        e.preventDefault();
        return;
      }
      const first = list[0];
      const last = list[list.length - 1];
      const inside = panel.current.contains(document.activeElement);
      if (e.shiftKey && (document.activeElement === first || !inside)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (document.activeElement === last || !inside)) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      if (opener?.isConnected) opener.focus();
    };
  }, [panel]);
}
