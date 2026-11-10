import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { confirmDialog } from "@/lib/dialog";
import { Button, Card, Toggle } from "@/components/ui";
import { api, ApiError } from "@/lib/api";

type G = { applies: boolean; email?: string; digest?: boolean; last_sent?: string | null };

/** Under-18 learners: who gets progress updates, send the link now, weekly email on/off, revoke the link. */
export function GuardianCard() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["guardian-me"], queryFn: () => api<G>("/api/users/guardian/") });
  const [msg, setMsg] = useState("");
  if (!data?.applies) return null;
  const act = async (body: object, method: "POST" | "PATCH" = "POST", ok = "") => {
    setMsg("");
    try {
      qc.setQueryData(["guardian-me"], await api<G>("/api/users/guardian/", { method, json: body }));
      if (ok) setMsg(ok);
    } catch (e) {
      const code = e instanceof ApiError ? String((e.data as { code?: string } | undefined)?.code ?? "") : "";
      setMsg(code === "sent_recently" ? t("guardian.recently") : code === "email_not_configured" ? t("mailSetup.notReady") : code === "send_failed" ? t("mailSetup.sendFailed") : t("mentor.errors.generic"));
    }
  };
  return (
    <Card className="space-y-3">
      <h2 className="font-display text-xl font-bold">{t("guardian.cardTitle")}</h2>
      <p className="text-sm text-muted">{t("guardian.cardSub", { email: data.email })}</p>
      <Toggle label={t("guardian.weekly")} checked={!!data.digest} onChange={(v) => void act({ digest: v }, "PATCH")} />
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" onClick={() => void act({ action: "send" }, "POST", t("guardian.sent"))}>{t("guardian.sendNow")}</Button>
        <Button variant="ghost" onClick={async () => { if (await confirmDialog(t("guardian.revokeConfirm"), { danger: true })) void act({ action: "revoke" }, "POST", t("guardian.revoked")); }}>{t("guardian.revoke")}</Button>
      </div>
      {msg && <p role="status" className="text-sm">{msg}</p>}
    </Card>
  );
}
