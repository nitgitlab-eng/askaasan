import { Copy } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { InviteMail } from "@/lib/orgs";

/** Invitations that exist but weren't emailed (no SMTP yet, or it failed): say so and hand over the links to share. */
export function UnsentInvites({ mail }: { mail: InviteMail | null }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState("");
  if (!mail || mail.emailed !== false || !mail.links?.length) return null;
  return (
    <div role="status" className="space-y-1 rounded-xl border border-line bg-surface-2 p-3 text-sm">
      <p>{mail.code === "email_not_configured" ? t("mailSetup.invitesNotSetUp") : t("mailSetup.invitesNotSent")}</p>
      <ul className="space-y-1">
        {mail.links.map((l) => (
          <li key={l.link} className="flex flex-wrap items-center gap-2">
            <span className="min-w-0 truncate">{l.email}</span>
            <button type="button" onClick={() => { void navigator.clipboard?.writeText(l.link).catch(() => undefined); setCopied(l.link); }} className="flex items-center gap-1 text-xs font-semibold text-accent">
              <Copy className="h-3.5 w-3.5" /> {copied === l.link ? t("game.copied") : t("game.copyLink")}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
