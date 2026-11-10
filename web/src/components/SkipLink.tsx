import type { MouseEvent } from "react";
import { useTranslation } from "react-i18next";

/**
 * "Skip to content": the first focusable element on the page. Hidden until it receives keyboard focus, then shown
 * fixed top-left (44 px tall). Activating it moves focus to <main id="main" tabIndex={-1}> so keyboard and
 * screen-reader users jump past the navigation.
 */
export function SkipLink() {
  const { t } = useTranslation();
  const jump = (e: MouseEvent<HTMLAnchorElement>) => {
    const main = document.getElementById("main");
    if (!main) return; // fall back to the plain #main anchor jump
    e.preventDefault();
    main.focus();
  };
  return (
    <a
      href="#main"
      onClick={jump}
      className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-[100] focus:flex focus:h-11 focus:items-center focus:rounded-xl focus:bg-accent focus:px-4 focus:font-semibold focus:text-accent-ink focus:shadow-lg"
    >
      {t("a11y.skipToContent")}
    </a>
  );
}
