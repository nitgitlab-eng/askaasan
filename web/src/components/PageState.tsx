import { RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { ApiError } from "@/lib/api";
import { Kili } from "@/mascot/Kili";

import { Button } from "./ui";

/** Shown instead of an endless "Loading…" when a page's data failed or doesn't exist. */
export function PageError({ error, notFound, onRetry }: { error?: unknown; notFound?: boolean; onRetry?: () => void }) {
  const { t } = useTranslation();
  const missing = notFound || (error instanceof ApiError && (error.status === 404 || error.status === 403));
  return (
    <div role="alert" className="flex flex-col items-center gap-3 px-4 py-20 text-center">
      <Kili mood="confused" size={120} />
      <p className="font-display text-xl font-bold">{missing ? t("page.notFound") : t("page.error")}</p>
      <div className="flex flex-wrap justify-center gap-2">
        {!missing && onRetry && <Button variant="outline" onClick={onRetry}><RotateCcw className="h-4 w-4" /> {t("common.retry")}</Button>}
        <Link to="/" className="inline-flex items-center rounded-xl px-4 py-2.5 font-semibold text-accent hover:bg-surface-2">{t("page.home")}</Link>
      </div>
    </div>
  );
}
