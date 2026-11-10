import { useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/lib/api";
import { confirmDialog } from "@/lib/dialog";
import { orgs } from "@/lib/orgs";

/** Invitations sent but not yet accepted, each with a Revoke button (the link stops working). */
export function PendingInvites({ slug, onRevoked }: { slug: string; onRevoked?: (email: string) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const key = ["org-pending-invites", slug];
  const { data } = useQuery({ queryKey: key, queryFn: () => orgs.pendingInvites(slug) });
  const [err, setErr] = useState("");
  if (!data?.length) return null;
  async function revoke(id: number, email: string) {
    if (!(await confirmDialog(t("org.revokeInviteConfirm", { email }), { danger: true, ok: t("org.revokeInvite") }))) return;
    setErr("");
    try {
      await orgs.revokeInvite(slug, id);
      onRevoked?.(email);
    } catch (e) {
      setErr(t(`org.err.${e instanceof ApiError ? String(e.data?.code ?? e.data?.detail ?? "generic") : "generic"}`, { defaultValue: t("mentor.errors.generic") }));
    }
    await qc.invalidateQueries({ queryKey: key });
  }
  return (
    <div className="space-y-1 border-t border-line pt-2">
      <p className="text-sm font-semibold">{t("org.pendingInvites")}</p>
      <ul className="space-y-1">
        {data.map((i) => (
          <li key={i.id} className="flex items-center gap-2 text-sm">
            <span className="min-w-0 flex-1 truncate">{i.email} <span className="text-xs text-muted">· {t(`org.roles.${i.role}`)}</span></span>
            <button type="button" onClick={() => void revoke(i.id, i.email)} className="flex items-center gap-1 text-xs text-muted hover:text-bad">
              <X className="h-3.5 w-3.5" aria-hidden /> {t("org.revokeInvite")}
            </button>
          </li>
        ))}
      </ul>
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
    </div>
  );
}
