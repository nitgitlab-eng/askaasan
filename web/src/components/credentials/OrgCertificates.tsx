import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Award } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { confirmDialog } from "@/lib/dialog";
import { RecordsExport } from "@/components/orgs/RecordsExport";
import { Button, Card } from "@/components/ui";
import { localeOf } from "@/i18n/languages";
import { ApiError } from "@/lib/api";
import { credentials, type CertKind } from "@/lib/credentials";
import { orgs } from "@/lib/orgs";

const KINDS: CertKind[] = ["course", "scenario", "test"];

/** Cockpit tab: issue certificates for assigned courses / scenarios a member finished and knowledge tests they passed. */
export function OrgCertificates({ slug }: { slug: string }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [member, setMember] = useState<number | "">("");
  const [err, setErr] = useState("");
  const members = useQuery({ queryKey: ["org-members", slug], queryFn: () => orgs.members(slug) });
  const issued = useQuery({ queryKey: ["org-certs", slug], queryFn: () => credentials.org(slug) });
  const eligible = useQuery({ queryKey: ["org-cert-eligible", slug, member], queryFn: () => credentials.eligible(slug, member as number), enabled: member !== "" });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["org-certs", slug] }); void qc.invalidateQueries({ queryKey: ["org-cert-eligible", slug] }); };
  const run = async (fn: () => Promise<unknown>) => {
    setErr("");
    try {
      await fn();
      refresh();
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 403 ? t("cred.org.notEligible")
        : e instanceof ApiError && e.data?.code === "issuer_name_reserved" ? t("credOrg.reserved") : t("mentor.errors.generic"));
    }
  };
  const none = eligible.data && KINDS.every((k) => !eligible.data[k].length);
  return (
    <div className="space-y-4">
      <RecordsExport slug={slug} />
      <Card className="space-y-3">
        <h2 className="flex items-center gap-2 font-display text-lg font-bold"><Award className="h-5 w-5 text-accent" /> {t("cred.org.title")}</h2>
        <p className="text-sm text-muted">{t("cred.org.hint")}</p>
        <select value={member} onChange={(e) => setMember(e.target.value ? Number(e.target.value) : "")} aria-label={t("cred.org.member")}
          className="w-full rounded-lg border-2 border-line bg-surface px-2 py-1.5 text-sm">
          <option value="">{t("cred.org.member")}</option>
          {members.data?.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
        </select>
        {none && <p className="text-sm text-muted">{t("cred.org.nothing")}</p>}
        {eligible.data && KINDS.map((k) => eligible.data[k].map((x) => (
          <div key={`${k}${x.id}`} className="flex flex-wrap items-center gap-2 rounded-lg border border-line px-3 py-1.5 text-sm">
            <span className="rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold">{t(`cred.kind.${k}`)}</span>
            <span className="min-w-0 flex-1">{x.title}</span>
            {x.issued ? <span className="text-xs text-good">{t("cred.org.issued")}</span>
              : <Button className="py-1 text-sm" onClick={() => void run(() => credentials.issue(slug, member as number, k, x.id))}>{t("cred.org.issue")}</Button>}
          </div>
        )))}
        {err && <p role="alert" className="text-sm text-bad">{err}</p>}
      </Card>
      <Card className="space-y-2">
        <h3 className="font-display text-base font-bold">{t("cred.org.list")}</h3>
        {issued.data && !issued.data.length && <p className="text-sm text-muted">{t("cred.org.empty")}</p>}
        {issued.data?.map((c) => (
          <div key={c.id} className="flex flex-wrap items-center gap-2 border-t border-line py-1.5 text-sm">
            <span className="flex-1">{c.learner} · {c.title} <span className="text-xs text-muted">· {t(`cred.kind.${c.kind}`)} · {new Date(c.issued_at).toLocaleDateString(localeOf(i18n.language))}</span></span>
            {c.revoked ? <span className="text-xs text-bad">{t("cred.status.revoked")}</span>
              : <button type="button" className="text-xs text-muted hover:text-bad" onClick={async () => { if (await confirmDialog(t("cred.revokeConfirm"), { danger: true })) void run(() => credentials.orgRevoke(slug, c.id)); }}>{t("cred.revoke")}</button>}
          </div>
        ))}
      </Card>
    </div>
  );
}
