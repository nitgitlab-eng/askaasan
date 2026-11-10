import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, ChevronDown, ShieldCheck, WifiOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, NavLink, Outlet, useLocation } from "react-router-dom";

import { TourHost } from "@/components/tour/Tour";
import { useAutoTour } from "@/components/tour/tourStore";
import { cn } from "@/lib/cn";
import { LAB_SECTION, SECTIONS, sectionFor, tabFor, visibleTabs, type NavSection, type NavTab } from "@/lib/nav";
import { flushQueue, useOnline, useQueuedCount } from "@/lib/offline";
import { orgs } from "@/lib/orgs";
import { resendVerification, useLogout } from "@/lib/auth";
import { useApplyAppearance, useMe } from "@/lib/useMe";

import { useNudges } from "@/lib/useNudges";

import { GameBar, RewardToasts } from "./GameBar";
import { ConsentGate } from "./ConsentGate";
import { GuardianConsentBanner } from "./GuardianConsentBanner";
import { PlanLimitSheet } from "./PlanLimitSheet";
import { SectionTabs } from "./SectionTabs";
import { SkipLink } from "./SkipLink";
import { StorageNotice } from "./StorageNotice";
import { YouMenu } from "./YouMenu";
import { Kili } from "@/mascot/Kili";
import { MascotDock } from "@/mascot/MascotDock";
import { mascot, useMascot } from "@/mascot/store";

export function AppShell() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const logout = useLogout();
  const { pathname } = useLocation();
  const qc = useQueryClient();
  useApplyAppearance(me);
  const online = useOnline();
  const queued = useQueuedCount();
  useAutoTour("app", pathname === "/" && !!me?.profile.onboarding_completed);
  useEffect(() => {
    if (online) void flushQueue().then((n) => n && void qc.invalidateQueries()); // answers given offline get checked now
  }, [online, qc]);
  useNudges(!!me?.profile.onboarding_completed, me?.preferences.mascot.chattiness ?? 2);
  const greeted = useRef(false);
  const [resendMsg, setResendMsg] = useState("");
  const look = me?.preferences.mascot;
  const character = look?.character;
  const accessoriesKey = look?.accessories.join(",");
  useEffect(() => {
    if (character) useMascot.getState().setCharacter(character);
  }, [character]);
  // Every <Kili> without explicit props wears the learner's chosen colour and outfit.
  useEffect(() => {
    if (look) useMascot.getState().setLook({ color: look.color, outfit: look.outfit, accessories: look.accessories });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [look?.color, look?.outfit, accessoriesKey]);

  useEffect(() => {
    if (!me || greeted.current) return;
    greeted.current = true;
    const first = !sessionStorage.getItem("aasan-greeted");
    sessionStorage.setItem("aasan-greeted", "1");
    if (first && me.preferences.mascot.chattiness > 0) {
      setTimeout(() => {
        mascot.react("wave");
        mascot.say(t("mascot.firstHello", { name: me.preferences.mascot.name }));
      }, 600);
    }
  }, [me, t]);

  const { data: brand } = useQuery({ queryKey: ["my-brand"], queryFn: orgs.myBrand, staleTime: 5 * 60_000 });
  const off = new Set(brand?.disabled ?? []); // features the learner's school switched off
  const inOrg = (brand?.orgs.length ?? 0) > 0;
  const sections = [...SECTIONS, ...(me?.can_author ? [LAB_SECTION] : [])]
    .map((s) => ({ section: s, tabs: visibleTabs(s, off) }))
    .filter((s) => s.tabs.length > 0);
  const main = sections.filter((s) => s.section !== LAB_SECTION);
  const current = sectionFor(pathname, sections.map((s) => s.section));
  const currentTabs = sections.find((s) => s.section === current)?.tabs ?? [];
  const name = me?.profile.display_name || me?.email?.split("@")[0] || "";
  const linkCls = (active: boolean) =>
    cn("flex shrink-0 items-center gap-3 rounded-xl px-3 py-2 font-medium transition hover:bg-surface-2", active && "bg-accent text-accent-ink hover:bg-accent");
  const sectionLink = ({ section, tabs }: { section: NavSection; tabs: { to: string }[] }, compact = true) => {
    const Icon = section.icon;
    const active = current === section;
    return (
      <Link key={section.key} to={tabs[0].to} aria-label={t(section.label)} aria-current={active ? "page" : undefined}
        data-tour={`section-${section.key}`}
        className={compact
          ? cn("flex min-w-0 flex-1 flex-col items-center gap-0.5 rounded-xl px-1 py-1.5 text-[11px] font-semibold", active ? "text-accent" : "text-muted")
          : linkCls(active)}>
        <Icon className="h-5 w-5" aria-hidden />
        <span className={compact ? "max-w-full truncate" : ""}>{t(section.label)}</span>
      </Link>
    );
  };
  // Desktop sidebar: the section you're in is unfolded; ▸ peeks into another one (one at a time). A peek lasts until
  // the next page, so moving on always shows where you are.
  const [peek, setPeek] = useState<{ path: string; key: string | null } | null>(null);
  const openKey = peek?.path === pathname ? peek.key : (current?.key ?? null);
  const sidebarSection = ({ section, tabs }: { section: NavSection; tabs: NavTab[] }) => {
    const Icon = section.icon;
    const here = current === section;
    const open = openKey === section.key && tabs.length > 1;
    const currentTab = here ? tabFor(pathname, section) : undefined;
    const subId = `nav-sub-${section.key}`;
    return (
      <div key={section.key}>
        <div className="flex items-center gap-1">
          <Link to={tabs[0].to} aria-label={t(section.label)} data-tour={`section-${section.key}`}
            className={cn("flex min-w-0 flex-1 items-center gap-3 rounded-xl px-3 py-2 font-medium transition hover:bg-surface-2",
              here && (tabs.length > 1 ? "text-accent" : "bg-accent text-accent-ink hover:bg-accent"))}
            aria-current={here && tabs.length < 2 ? "page" : undefined}>
            <Icon className="h-5 w-5" aria-hidden />
            <span className="truncate">{t(section.label)}</span>
          </Link>
          {tabs.length > 1 && (
            <button type="button" aria-expanded={open} aria-controls={subId}
              aria-label={t(open ? "nav.collapse" : "nav.expand", { section: t(section.label) })}
              onClick={() => setPeek({ path: pathname, key: open ? null : section.key })}
              className="rounded-lg p-1.5 text-muted hover:bg-surface-2">
              <ChevronDown aria-hidden className={cn("h-4 w-4 transition", !open && "-rotate-90")} />
            </button>
          )}
        </div>
        {open && (
          <ul id={subId} className="mb-1 ml-5 mt-0.5 space-y-0.5 border-l border-line pl-3">
            {tabs.map((tab) => {
              const active = currentTab?.to === tab.to;
              return (
                <li key={tab.to}>
                  <Link to={tab.to} aria-current={active ? "page" : undefined}
                    className={cn("block rounded-lg px-2.5 py-1.5 text-sm font-medium transition hover:bg-surface-2",
                      active ? "bg-accent text-accent-ink hover:bg-accent" : "text-muted hover:text-ink")}>
                    {t(tab.label)}
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    );
  };
  const you = (placement: "up" | "down") => (
    <YouMenu name={name} onLogout={logout} disabled={off} inOrg={inOrg} placement={placement}
      extras={{ lab: !!me?.can_author, admin: !!me?.is_staff }} />
  );

  if (me && !me.profile.onboarding_completed) return <Navigate to="/onboarding" replace />;

  return (
    <div className="flex min-h-dvh flex-col md:flex-row">
      <SkipLink />
      {/* Desktop: five sections, then what only some people have, then "You". */}
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-line bg-surface/90 p-4 backdrop-blur md:flex">
        <div className="mb-6 flex shrink-0 items-center gap-2">
          <Kili mood="idle" size={40} />
          <span className="font-display text-2xl font-extrabold text-accent">{t("app.name")}</span>
        </div>
        {brand?.primary && (brand.primary.logo_url || brand.primary.brand_color) && (
          <div className="-mt-4 mb-3 flex items-center gap-2 rounded-xl px-2 py-1.5" style={brand.primary.brand_color ? { background: `${brand.primary.brand_color}1a` } : undefined}>
            {brand.primary.logo_url && <img src={brand.primary.logo_url} alt="" className="h-7 w-7 rounded-lg object-contain" />}
            <span className="truncate text-sm font-semibold" style={brand.primary.brand_color ? { color: brand.primary.brand_color } : undefined}>{brand.primary.name}</span>
          </div>
        )}
        <nav aria-label={t("nav.main")} className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
          {main.map((s) => sidebarSection(s))}
          {(inOrg || me?.can_author || me?.is_staff) && <div role="separator" className="my-2 border-t border-line" />}
          {inOrg && (
            <NavLink to="/orgs" className={({ isActive }) => linkCls(isActive)}>
              <Building2 className="h-5 w-5" aria-hidden /> {t("nav.mySchool")}
            </NavLink>
          )}
          {sections.filter((s) => s.section === LAB_SECTION).map((s) => sidebarSection(s))}
          {me?.is_staff && (
            <NavLink to="/admin" className={({ isActive }) => linkCls(isActive)}>
              <ShieldCheck className="h-5 w-5" aria-hidden /> {t("nav.admin")}
            </NavLink>
          )}
        </nav>
        <div className="mt-2 border-t border-line pt-2">{you("up")}</div>
      </aside>
      {/* Phone: logo + "You" on top, the five sections as a bottom bar. */}
      <header className="sticky top-0 z-40 flex items-center gap-2 border-b border-line bg-surface/90 px-3 py-2 backdrop-blur md:hidden">
        <Kili mood="idle" size={32} />
        <span className="font-display text-xl font-extrabold text-accent">{t("app.name")}</span>
        <div className="ml-auto">{you("down")}</div>
      </header>
      <nav aria-label={t("nav.main")} className="fixed inset-x-0 bottom-0 z-40 flex items-stretch gap-1 border-t border-line bg-surface/95 px-1 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
        {main.map((s) => sectionLink(s))}
      </nav>
      <main id="main" tabIndex={-1} className="min-w-0 flex-1 pb-20 outline-none md:pb-0">
        <RewardToasts />
        <PlanLimitSheet />
        <StorageNotice />
        <TourHost />
        {(!online || queued > 0) && (
          <div role="status" className="flex items-center justify-center gap-2 bg-amber-100 px-4 py-1.5 text-sm text-amber-900 dark:bg-amber-950/60 dark:text-amber-200">
            <WifiOff className="h-4 w-4" /> {!online ? t("offline.banner") : t("offline.syncing", { count: queued })}
          </div>
        )}
        {me?.consent?.required && <ConsentGate updated={!!me.consent.age_band} />}
        <div className="sticky top-0 z-30 flex justify-end border-b border-line bg-bg/80 px-4 py-2 backdrop-blur">
          <GameBar />
        </div>
        {(me?.consent?.guardian === "pending" || me?.consent?.guardian === "objected") && <GuardianConsentBanner state={me.consent.guardian} />}
        {me && !me.email_verified && (
          <div className="flex items-center justify-center gap-3 bg-accent/15 px-4 py-2 text-sm">
            {t("auth.verifyBanner")}
            <button className="font-semibold text-accent underline" onClick={() => void resendVerification().then(setResendMsg)}>
              {t("auth.resend")}
            </button>
            {resendMsg && <span role="status">{resendMsg}</span>}
          </div>
        )}
        {current && <SectionTabs section={current} tabs={currentTabs} pathname={pathname} />}
        <Outlet />
      </main>
      {me && !pathname.startsWith("/live") && !pathname.startsWith("/workshops/session") && (
        // Ask Aasan on a phone: the message bar spans the width and its End button sits where the floating Kili would;
        // Kili is already in the voice orb and beside every answer there.
        <div className={pathname.startsWith("/mentor") ? "contents max-md:hidden" : "contents"}>
          <MascotDock prefs={me.preferences.mascot} />
        </div>
      )}
    </div>
  );
}
