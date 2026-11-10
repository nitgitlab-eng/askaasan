import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Users } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Button, Card } from "@/components/ui";
import { billing } from "@/lib/billing";
import { confirmDialog } from "@/lib/dialog";

/** Account page: members can leave their family plan; owners get a link to manage theirs on the Plans page. */
export function FamilyCard() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["billing-family"], queryFn: billing.family.get });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(false);
  if (!data?.role) return null;

  async function leave() {
    if (!(await confirmDialog(t("account.family.leaveConfirm"), { danger: true }))) return;
    setBusy(true);
    setErr(false);
    try {
      qc.setQueryData(["billing-family"], await billing.family.leave());
      void qc.invalidateQueries({ queryKey: ["billing"] });
    } catch {
      setErr(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-2">
      <h2 className="flex items-center gap-2 font-display text-lg font-bold"><Users className="h-5 w-5 text-accent" /> {t("account.family.title")}</h2>
      {data.role === "owner" ? (
        <>
          <p className="text-sm">{t("account.family.owner", { plan: data.plan?.name ?? "", count: data.members?.length ?? 1, max: data.max_members })}</p>
          <Link to="/plans#family" className="text-sm font-semibold text-accent">{t("account.family.manage")}</Link>
        </>
      ) : (
        <>
          <p className="text-sm">{t("account.family.member", { owner: data.owner_name ?? "", plan: data.plan?.name ?? "" })}</p>
          <Button variant="outline" loading={busy} onClick={() => void leave()}>{t("account.family.leave")}</Button>
        </>
      )}
      {err && <p role="alert" className="text-sm text-bad">{t("account.family.failed")}</p>}
    </Card>
  );
}
