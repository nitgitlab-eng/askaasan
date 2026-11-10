import { ArrowLeft, Award, Headphones, Building2, CalendarDays, Cpu, HeartHandshake, IndianRupee, LayoutDashboard, Library, LifeBuoy, Mail, Presentation, Scale, ShieldCheck, Stethoscope, TicketPercent, Undo2, UserCog, Users } from "lucide-react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Navigate, Outlet } from "react-router-dom";

import { TourHost } from "@/components/tour/Tour";
import { startTour, useAutoTour } from "@/components/tour/tourStore";

import { canSee } from "@/lib/admin";
import { cn } from "@/lib/cn";
import { useApplyAppearance, useMe } from "@/lib/useMe";

/** Console sections in sidebar order; `key` is the label under admin.nav.sections, the path segment is the role gate. */
const SECTIONS = [
  { to: "/admin/overview", key: "overview", icon: LayoutDashboard },
  { to: "/admin/users", key: "users", icon: Users },
  { to: "/admin/orgs", key: "orgs", icon: Building2 },
  { to: "/admin/catalog", key: "catalog", icon: Library },
  { to: "/admin/certificates", key: "certificates", icon: Award },
  { to: "/admin/workshops", key: "workshops", icon: Presentation },
  { to: "/admin/payments", key: "payments", icon: IndianRupee },
  { to: "/admin/refunds", key: "refunds", icon: Undo2 },
  { to: "/admin/families", key: "families", icon: HeartHandshake },
  { to: "/admin/codes", key: "codes", icon: TicketPercent },
  { to: "/admin/support", key: "support", icon: LifeBuoy },
  { to: "/admin/system", key: "system", icon: Stethoscope },
  { to: "/admin/providers", key: "providers", icon: Cpu },
  { to: "/admin/features", key: "features", icon: Headphones },
  { to: "/admin/calendar-apps", key: "calendarApps", icon: CalendarDays },
  { to: "/admin/email", key: "email", icon: Mail },
  { to: "/admin/site", key: "site", icon: Scale },
  { to: "/admin/staff", key: "staff", icon: UserCog },
] as const;
const section = (to: string) => to.split("/")[2];

/** Staff-only console. Server enforces permissions too; this guard is UX. */
export function AdminLayout() {
  const { t } = useTranslation();
  const { data: me, isLoading } = useMe();
  useApplyAppearance(me);
  useAutoTour("admin", !!me?.is_staff);
  useEffect(() => {
    if (new URLSearchParams(location.search).get("tour")) startTour("admin");
  }, []);
  if (isLoading) return null;
  if (!me?.is_staff) return <Navigate to="/" replace />;
  return (
    <div className="flex min-h-dvh flex-col md:flex-row">
      {/* Desktop: the sidebar stays in view (sticky, one screen tall) and its menu scrolls on its own, so the 18 sections
          never spill past the dark panel (light text on the light page = invisible) on shorter screens. */}
      <aside className="sticky top-0 z-30 flex shrink-0 items-center gap-2 border-b border-line bg-ink px-3 py-2 text-bg md:h-dvh md:w-64 md:flex-col md:items-stretch md:border-b-0 md:p-4">
        <div className="flex shrink-0 items-center gap-2 md:mb-6">
          <ShieldCheck className="h-6 w-6 text-accent" />
          <div>
            <p className="font-display text-xl font-extrabold leading-none">{t("admin.nav.title")}</p>
            <p className="hidden text-xs opacity-70 md:block">{me.email}</p>
          </div>
        </div>
        <nav aria-label={t("admin.nav.label")} className="ml-auto flex min-w-0 gap-1 overflow-x-auto md:-mx-1 md:ml-0 md:min-h-0 md:flex-1 md:flex-col md:overflow-x-hidden md:overflow-y-auto md:px-1">
          {SECTIONS.filter((s) => canSee(me.staff_roles ?? ["superadmin"], section(s.to))).map(({ to, key, icon: Icon }) => {
            const label = t(`admin.nav.sections.${key}`);
            return (
              <NavLink key={to} to={to} title={label} aria-label={label} className={({ isActive }) => cn("flex shrink-0 items-center gap-3 rounded-xl px-3 py-2 font-medium hover:bg-white/10", isActive && "bg-accent text-accent-ink hover:bg-accent")}>
                <Icon className="h-5 w-5" />
                <span className="hidden md:inline">{label}</span>
              </NavLink>
            );
          })}
        </nav>
        <NavLink to="/" className="hidden shrink-0 items-center gap-2 rounded-xl px-3 py-2 opacity-80 hover:bg-white/10 md:mt-2 md:flex">
          <ArrowLeft className="h-4 w-4" /> {t("admin.nav.back")}
        </NavLink>
      </aside>
      <main className="min-w-0 flex-1">
        <TourHost />
        <Outlet />
      </main>
    </div>
  );
}
