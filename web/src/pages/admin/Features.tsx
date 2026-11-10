import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Card, Toggle } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { Features } from "@/lib/types";
import { meKey } from "@/lib/useMe";

interface FeatureSettings extends Features { updated_at: string | null; updated_by: string | null }

/** Switch order; label is admin.features.rows.<k>, hint is admin.features.rows.<k>Hint. */
const ROWS: (keyof Features)[] = ["listen", "explainer", "podcast"];

/** Lesson media switches: platform-wide, all off by default. Every change is in the audit log. */
export default function AdminFeatures() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["admin-features"], queryFn: () => api<FeatureSettings>("/api/admin/features/") });
  const save = useMutation({
    mutationFn: (patch: Partial<Features>) => api<FeatureSettings>("/api/admin/features/", { method: "PATCH", json: patch }),
    onSuccess: (r) => {
      qc.setQueryData(["admin-features"], r);
      void qc.invalidateQueries({ queryKey: meKey });
    },
  });
  const shown = save.isPending && save.variables && data ? { ...data, ...save.variables } : data;
  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("admin.features.title")}</h1>
        <p className="text-muted">
          {t("admin.features.sub")} {t("admin.features.voicesIn")} <Link className="font-semibold text-accent" to="/admin/providers">{t("admin.nav.sections.providers")}</Link>.
        </p>
      </header>
      {isLoading && <p className="text-muted">{t("admin.common.loading")}</p>}
      {error && <p className="text-bad">{t("admin.features.loadFailed")}</p>}
      {shown && (
        <Card className="space-y-4">
          {ROWS.map((k) => (
            <div key={k}>
              <Toggle label={t(`admin.features.rows.${k}`)} checked={shown[k]} onChange={(v) => save.mutate({ [k]: v })} />
              <p className="text-xs text-muted">{t(`admin.features.rows.${k}Hint`)}</p>
            </div>
          ))}
          {save.isError && <p role="alert" className="text-sm text-bad">{save.error instanceof ApiError ? JSON.stringify(save.error.data) : t("admin.common.saveFailed")}</p>}
          {shown.updated_at && <p className="text-xs text-muted">{t(shown.updated_by ? "admin.features.lastChangedBy" : "admin.features.lastChanged", { when: new Date(shown.updated_at).toLocaleString("en-IN"), who: shown.updated_by })}</p>}
        </Card>
      )}
    </div>
  );
}
