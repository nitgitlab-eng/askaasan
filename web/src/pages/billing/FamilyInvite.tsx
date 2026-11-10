import { useMutation, useQuery } from "@tanstack/react-query";
import { Users } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { resendVerification } from "@/lib/auth";
import { billing } from "@/lib/billing";
import { mascot } from "@/mascot/store";

const KNOWN = ["invite_invalid", "invite_used", "invite_expired", "invite_not_for_you", "verify_email_first", "family_already", "seat_covered", "family_full", "family_inactive", "too_many_attempts"];

/** /family/:token — someone invited you to their family plan. Joining is one explicit click (the token is one-time). */
export default function FamilyInvitePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { token = "" } = useParams();
  const [resent, setResent] = useState("");
  const preview = useQuery({ queryKey: ["family-invite", token], queryFn: () => billing.family.preview(token), retry: false });
  const join = useMutation({
    mutationFn: () => billing.family.accept({ token }),
    onSuccess: () => mascot.react("celebrate"),
  });
  const codeOf = (e: unknown) => (e instanceof ApiError ? String(e.data?.code ?? "") : "");
  const problem = codeOf(join.error) || codeOf(preview.error) || preview.data?.problem || (preview.data && !preview.data.for_you ? "invite_not_for_you" : "");
  const errText = (c: string) => (KNOWN.includes(c) ? t(`billing.family.errors.${c}`, { hint: preview.data?.email_hint ?? "" }) : t("billing.family.errors.generic"));

  return (
    <div className="mx-auto max-w-md px-4 py-16 text-center">
      <Card className="space-y-4">
        <Users className="mx-auto h-10 w-10 text-accent" />
        {preview.isLoading && <p>{t("common.loading")}</p>}
        {join.data ? (
          <>
            <p className="font-display text-2xl font-bold">{t("billing.family.welcome", { owner: preview.data?.owner_name ?? "", plan: join.data.plan?.name ?? "" })}</p>
            <Button onClick={() => navigate("/plans")}>{t("billing.family.seePlan")}</Button>
          </>
        ) : (
          <>
            {preview.data && (
              <p className="font-display text-xl font-bold">{t("billing.family.inviteTitle", { owner: preview.data.owner_name, plan: preview.data.plan ?? "" })}</p>
            )}
            {preview.data && <p className="text-sm text-muted">{t("billing.family.inviteBody")}</p>}
            {problem ? <p role="alert" className="text-bad">{errText(problem)}</p> : preview.data && (
              <Button loading={join.isPending} onClick={() => join.mutate()}>{t("billing.family.accept")}</Button>
            )}
            {problem === "verify_email_first" && (
              <>
                <Button variant="outline" onClick={() => void resendVerification().then(setResent)}>{t("auth.resend")}</Button>
                {resent && <p role="status" className="text-sm text-muted">{resent}</p>}
              </>
            )}
          </>
        )}
      </Card>
    </div>
  );
}
