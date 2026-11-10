import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { orgs, type Brand } from "@/lib/orgs";
import { Kili } from "@/mascot/Kili";

function JoinCard({ org, line, open, onJoin }: { org: Brand; line: string; open: boolean; onJoin: () => Promise<{ slug: string }> }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  return (
    <div className="mx-auto max-w-md px-4 py-12">
      <Card className="flex flex-col items-center gap-3 text-center">
        {org.logo_url ? <img src={org.logo_url} alt="" className="h-16 w-16 rounded-2xl object-contain" /> : <Kili mood="wave" size={100} />}
        <h1 className="font-display text-2xl font-extrabold" style={org.brand_color ? { color: org.brand_color } : undefined}>{org.name}</h1>
        <p className="text-muted">{line}</p>
        {open ? (
          <Button loading={busy} onClick={async () => {
            setBusy(true);
            setErr("");
            try {
              await onJoin();
              navigate("/", { replace: true });
            } catch (e) {
              setErr(e instanceof ApiError ? t(`orgx.joinErr.${e.data?.code}`, { defaultValue: t("mentor.errors.generic") }) : t("mentor.errors.generic"));
            } finally {
              setBusy(false);
            }
          }}>{t("orgx.joinNow")}</Button>
        ) : <p className="text-sm text-bad">{t("orgx.joinErr.campaign_closed")}</p>}
        {err && <p role="alert" className="text-sm text-bad">{err}</p>}
      </Card>
    </div>
  );
}

export function JoinCampaignPage() {
  const { t } = useTranslation();
  const { token = "" } = useParams();
  const { data, error } = useQuery({ queryKey: ["campaign", token], queryFn: () => orgs.campaignInfo(token), retry: false });
  if (error) return <p className="p-8 text-muted">{t("orgx.badLink")}</p>;
  if (!data) return <p className="p-8 text-muted">{t("common.loading")}</p>;
  return <JoinCard org={data.org} line={data.member ? t("orgx.alreadyMember") : t("orgx.campaignLine", { name: data.campaign })} open={data.open || data.member} onJoin={() => orgs.joinCampaign(token)} />;
}

export function JoinReferralPage() {
  const { t } = useTranslation();
  const { code = "" } = useParams();
  const { data, error } = useQuery({ queryKey: ["referral", code], queryFn: () => orgs.referralInfo(code), retry: false });
  if (error) return <p className="p-8 text-muted">{t("orgx.badLink")}</p>;
  if (!data) return <p className="p-8 text-muted">{t("common.loading")}</p>;
  return <JoinCard org={data.org} line={t("orgx.referralLine")} open={data.open} onJoin={() => orgs.joinReferral(code)} />;
}
