import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { cn } from "@/lib/cn";

export function LegalLinks({ className }: { className?: string }) {
  const { t } = useTranslation();
  return (
    <nav aria-label={t("legal.links")} className={cn("flex flex-wrap justify-center gap-x-4 gap-y-1 text-xs text-muted", className)}>
      <Link to="/privacy" className="hover:text-accent">{t("legal.privacy")}</Link>
      <Link to="/terms" className="hover:text-accent">{t("legal.terms")}</Link>
      <Link to="/refunds" className="hover:text-accent">{t("legal.refunds")}</Link>
      <Link to="/dpa" className="hover:text-accent">{t("legal.dpa")}</Link>
      <Link to="/contact" className="hover:text-accent">{t("legal.contact")}</Link>
    </nav>
  );
}
