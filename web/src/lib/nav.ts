/** The app's navigation: five plain sections in the sidebar, each with a tab row for its related pages. Every page
 * keeps its own route; this only decides how learners reach it. */
import { Award, BookOpen, ChartLine, FlaskConical, Home, MessageCircleHeart, type LucideIcon } from "lucide-react";

export interface NavTab {
  to: string;
  label: string; // i18n key
  /** An org-switchable feature: hidden when the learner's school turned it off. */
  feature?: string;
}

export interface NavSection {
  key: string;
  label: string; // i18n key
  icon: LucideIcon;
  tabs: NavTab[];
}

export const SECTIONS: NavSection[] = [
  {
    key: "home",
    label: "nav.home",
    icon: Home,
    tabs: [
      { to: "/", label: "nav.home" },
      { to: "/today", label: "nav.today" },
      { to: "/plan", label: "nav.plan" },
    ],
  },
  {
    key: "learn",
    label: "nav.learn",
    icon: BookOpen,
    tabs: [
      { to: "/learn", label: "learn.title" },
      { to: "/catalog", label: "nav.catalog" },
      { to: "/paths", label: "nav.paths" },
      { to: "/careers", label: "nav.careers" },
      { to: "/review", label: "nav.review" },
      { to: "/documents", label: "nav.documents" },
    ],
  },
  {
    key: "practice",
    label: "nav.practice",
    icon: MessageCircleHeart,
    tabs: [
      { to: "/mentor", label: "nav.mentor", feature: "mentor" },
      { to: "/roleplay", label: "nav.roleplay", feature: "roleplay" },
      { to: "/live", label: "nav.live", feature: "live" },
      { to: "/workshops", label: "nav.workshops", feature: "workshops" },
    ],
  },
  {
    key: "progress",
    label: "nav.progress",
    icon: ChartLine,
    tabs: [
      { to: "/progress", label: "nav.progress" },
      { to: "/mastery", label: "nav.mastery" },
      { to: "/skills", label: "nav.skills" },
      { to: "/leaderboard", label: "nav.leaderboard", feature: "leaderboard" },
    ],
  },
  { key: "certificates", label: "cred.nav", icon: Award, tabs: [{ to: "/certificates", label: "cred.nav" }] },
];

/** Creators get a section of their own (shown only to them). */
export const LAB_SECTION: NavSection = {
  key: "lab",
  label: "nav.lab",
  icon: FlaskConical,
  tabs: [
    { to: "/lab", label: "nav.lab" },
    { to: "/connect", label: "mcpc.nav" },
  ],
};

const matches = (pathname: string, to: string) => (to === "/" ? pathname === "/" : pathname === to || pathname.startsWith(`${to}/`));

/** The section a route belongs to (nested routes too: /mastery/3 → progress). */
export function sectionFor(pathname: string, sections: NavSection[] = [...SECTIONS, LAB_SECTION]): NavSection | undefined {
  let best: { s: NavSection; len: number } | undefined;
  for (const s of sections)
    for (const tab of s.tabs)
      if (matches(pathname, tab.to) && (!best || tab.to.length > best.len)) best = { s, len: tab.to.length };
  return best?.s;
}

/** The tab a route belongs to (longest matching prefix). */
export function tabFor(pathname: string, section: NavSection): NavTab | undefined {
  return section.tabs.filter((t) => matches(pathname, t.to)).sort((a, b) => b.to.length - a.to.length)[0];
}

/** Tabs the learner can use: a feature their school switched off disappears. */
export function visibleTabs(section: NavSection, disabled: Iterable<string>): NavTab[] {
  const off = new Set(disabled);
  return section.tabs.filter((t) => !t.feature || !off.has(t.feature));
}
