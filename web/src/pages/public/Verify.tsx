import { useQuery } from "@tanstack/react-query";
import { BadgeCheck, ShieldQuestion, ShieldX } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { Card } from "@/components/ui";
import { localeOf } from "@/i18n/languages";
import { ApiError } from "@/lib/api";
import { credentials } from "@/lib/credentials";

/** Public certificate verification: shows only the learner's display name, what was completed, issuer and date. */
export default function VerifyPage() {
  const { t, i18n } = useTranslation();
  const { code = "" } = useParams();
  const { data, error } = useQuery({ queryKey: ["verify", code], queryFn: () => credentials.verify(code), retry: false });
  return (
    <main className="mx-auto flex min-h-[80vh] max-w-xl items-center px-4 py-12">
      <Card className="w-full space-y-4 text-center">
        {error instanceof ApiError && error.data?.code === "revoked" ? (
          <>
            <ShieldX className="mx-auto h-12 w-12 text-bad" />
            <h1 className="font-display text-2xl font-bold">{t("cred.verify.revoked")}</h1>
            <p className="text-sm text-muted">{t("cred.verify.revokedSub", { date: new Date(String(error.data.revoked_at)).toLocaleDateString(localeOf(i18n.language), { dateStyle: "long" }) })}</p>
          </>
        ) : error ? (
          <>
            <ShieldQuestion className="mx-auto h-12 w-12 text-muted" />
            <h1 className="font-display text-2xl font-bold">{t("cred.verify.notFound")}</h1>
            <p className="text-sm text-muted">{t("cred.verify.notFoundSub")}</p>
          </>
        ) : !data ? <p className="text-muted">{t("common.loading")}</p> : (
          <>
            <p className="mx-auto flex w-fit items-center gap-1.5 rounded-full bg-good/15 px-3 py-1 text-sm font-bold text-good">
              <BadgeCheck className="h-5 w-5" /> {t("cred.verify.verified")}
            </p>
            <p className="text-sm text-muted">{t("cred.verify.certifies")}</p>
            <h1 className="font-display text-3xl font-extrabold">{data.learner}</h1>
            <p className="text-sm text-muted">{t(`cred.verify.did.${data.kind}`)}</p>
            <p className="font-display text-xl font-bold">{data.title}</p>
            {data.author && <p className="text-sm text-muted">{t("credSurvey2.courseBy", { name: data.author })}</p>}
            <div className="grid grid-cols-2 gap-2 border-t border-line pt-3 text-sm">
              <div><p className="text-xs text-muted">{t("cred.verify.issuer")}</p><p className="font-semibold">{data.issuer}</p>
                {data.issued_by_type === "organisation" && <p className="text-xs text-muted">{t("credSurvey2.orgOnAasan")}</p>}</div>
              <div><p className="text-xs text-muted">{t("cred.verify.date")}</p><p className="font-semibold">{new Date(data.issued_at).toLocaleDateString(localeOf(i18n.language), { dateStyle: "long" })}</p></div>
            </div>
            <p className="break-all text-xs text-muted">{t("cred.verify.id")}: {data.code}</p>
          </>
        )}
      </Card>
    </main>
  );
}
