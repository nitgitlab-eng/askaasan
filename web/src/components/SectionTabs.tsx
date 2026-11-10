import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { cn } from "@/lib/cn";
import { tabFor, type NavSection, type NavTab } from "@/lib/nav";

/** Phones only: the tab row at the top of a section (Learn: My courses · Catalog · Paths …). On desktop the sidebar
 * lists the same pages under the open section. Hidden for one-page sections. */
export function SectionTabs({ section, tabs, pathname }: { section: NavSection; tabs: NavTab[]; pathname: string }) {
  const { t } = useTranslation();
  if (tabs.length < 2) return null;
  const current = tabFor(pathname, section);
  return (
    <nav aria-label={t("nav.sectionTabs", { section: t(section.label) })} className="border-b border-line bg-bg/80 px-4 backdrop-blur md:hidden">
      <ul className="mx-auto flex max-w-5xl gap-1 overflow-x-auto py-2">
        {tabs.map((tab) => {
          const active = current?.to === tab.to;
          return (
            <li key={tab.to} className="shrink-0">
              <Link
                to={tab.to}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "block rounded-full px-3.5 py-1.5 text-sm font-semibold transition",
                  active ? "bg-accent text-accent-ink" : "text-muted hover:bg-surface-2 hover:text-ink",
                )}
              >
                {t(tab.label)}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
