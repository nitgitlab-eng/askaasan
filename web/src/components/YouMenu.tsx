import { Building2, ChevronDown, Crown, FlaskConical, LifeBuoy, LogOut, Palette, ShieldCheck, ShoppingBag, UserCog } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { cn } from "@/lib/cn";

export interface YouMenuProps {
  name: string;
  onLogout: () => void;
  /** Org-switchable features the learner's school turned off (shop hides Wardrobe). */
  disabled: Set<string>;
  inOrg: boolean;
  /** Shown here only on phones (the desktop sidebar lists them itself). */
  extras: { lab: boolean; admin: boolean };
  placement: "up" | "down";
}

/** Everything about "me" in one place: account, look, plan, help, sign out. */
export function YouMenu({ name, onLogout, disabled, inOrg, extras, placement }: YouMenuProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        button.current?.focus();
      }
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    root.current?.querySelector<HTMLElement>("[role=menuitem]")?.focus();
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const items = [
    { to: "/account", label: t("nav.account"), icon: UserCog },
    { to: "/personalize", label: t("nav.personalize"), icon: Palette },
    ...(disabled.has("shop") ? [] : [{ to: "/shop", label: t("nav.shop"), icon: ShoppingBag }]),
    { to: "/plans", label: t("nav.plans"), icon: Crown },
    { to: "/help", label: t("nav.help"), icon: LifeBuoy },
    ...(placement === "down" && inOrg ? [{ to: "/orgs", label: t("nav.mySchool"), icon: Building2 }] : []),
    ...(placement === "down" && extras.lab ? [{ to: "/lab", label: t("nav.lab"), icon: FlaskConical }] : []),
    ...(placement === "down" && extras.admin ? [{ to: "/admin", label: t("nav.admin"), icon: ShieldCheck }] : []),
    ...(inOrg ? [] : [{ to: "/orgs", label: t("nav.createOrg"), icon: Building2 }]),
  ];
  const initial = (name.trim()[0] ?? "?").toUpperCase();

  return (
    <div ref={root} className="relative" data-tour="you-menu">
      <button
        ref={button}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("nav.you")}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 rounded-xl px-2 py-2 font-medium hover:bg-surface-2"
      >
        <span aria-hidden className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent/15 font-display font-bold text-accent">{initial}</span>
        <span className={cn("min-w-0 flex-1 truncate text-left", placement === "down" && "sr-only")}>{name || t("nav.you")}</span>
        <ChevronDown aria-hidden className={cn("h-4 w-4 shrink-0 text-muted transition", open && "rotate-180", placement === "down" && "hidden")} />
      </button>
      {open && (
        <div
          role="menu"
          aria-label={t("nav.you")}
          className={cn(
            "absolute z-50 w-56 rounded-2xl border border-line bg-surface p-1.5 shadow-xl",
            placement === "up" ? "bottom-full left-0 mb-2" : "right-0 top-full mt-2",
          )}
        >
          {items.map(({ to, label, icon: Icon }) => (
            <Link key={`${to}-${label}`} role="menuitem" to={to} onClick={() => setOpen(false)} className="flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium hover:bg-surface-2 focus:bg-surface-2 focus:outline-none">
              <Icon aria-hidden className="h-4 w-4 text-muted" /> {label}
            </Link>
          ))}
          <div className="my-1 border-t border-line" />
          <button type="button" role="menuitem" onClick={onLogout} className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium text-muted hover:bg-surface-2 focus:bg-surface-2 focus:outline-none">
            <LogOut aria-hidden className="h-4 w-4" /> {t("nav.logout")}
          </button>
        </div>
      )}
    </div>
  );
}
