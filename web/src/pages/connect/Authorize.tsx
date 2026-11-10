import { useQuery } from "@tanstack/react-query";
import { Check, ShieldAlert, TriangleAlert } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";

import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { localeOf } from "@/i18n/languages";
import { authParams, connect, relativeAge, safeRedirect } from "@/lib/connect";

/** OAuth consent screen for Connect Claude (/connect/authorize?...). The user is signed in normally (RequireAuth). */
export default function ConnectAuthorize() {
  const { t, i18n } = useTranslation();
  const { search } = useLocation();
  const params = useMemo(() => authParams(search), [search]);
  const [org, setOrg] = useState("");
  const [busy, setBusy] = useState<"" | "approve" | "deny">("");
  const [leaving, setLeaving] = useState(false);
  const [err, setErr] = useState("");

  const go = (url: unknown) => {
    const safe = safeRedirect(url);
    if (!safe) return false;
    setLeaving(true);
    window.location.assign(safe);
    return true;
  };

  const { data, error, isLoading } = useQuery({
    queryKey: ["connect-consent", search],
    queryFn: () => connect.consentInfo(params),
    retry: false,
  });

  // Never redirect automatically on an error (the client isn't approved, so its redirect URI isn't trusted):
  // show the error, and at most an explicit "Return to <host>" button.
  const errData = error instanceof ApiError ? error.data : null;
  const returnUrl = safeRedirect(errData?.return_url);
  const returnHost = typeof errData?.redirect_host === "string" ? errData.redirect_host : "";

  const orgs = data?.orgs ?? [];
  const chosen = org || orgs[0]?.slug || "";

  async function decide(decision: "approve" | "deny") {
    setErr("");
    setBusy(decision);
    try {
      const r = await connect.decide(params, decision, chosen || undefined);
      if (!go(r.redirect)) setErr(t("mcpc.consent.invalid"));
    } catch {
      setErr(t("mcpc.error"));
    } finally {
      setBusy("");
    }
  }

  return (
    <main className="flex min-h-dvh items-center justify-center bg-bg p-4">
      <Card className="w-full max-w-md space-y-5">
        <h1 className="font-display text-2xl font-extrabold">{t("mcpc.consent.title")}</h1>
        {isLoading && <p className="text-muted">{t("common.loading")}</p>}
        {leaving && <p role="status" className="text-muted">{t("mcpc.consent.redirecting")}</p>}
        {error && (
          <div className="space-y-3">
            <p role="alert" className="text-bad">{t("mcpc.consent.invalid")}</p>
            {returnUrl && returnHost && (
              <Button variant="outline" onClick={() => go(returnUrl)}>{t("mcpc2.returnTo", { host: returnHost })}</Button>
            )}
          </div>
        )}
        {data && !leaving && (
          <>
            <div className="space-y-2">
              <p className="text-lg font-semibold">{t("mcpc.consent.wants", { name: data.client.name })}</p>
              <p className="text-sm text-muted">
                {t("mcpc2.registered", { when: relativeAge(data.client.registered_at, localeOf(i18n.language)) })}
              </p>
              {data.client.name_mismatch && (
                <p role="alert" className="flex gap-2 rounded-xl border-2 border-bad bg-bad/10 p-3 text-sm text-bad">
                  <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                  <span>{t("mcpc2.nameMismatch", { name: data.client.name, host: data.client.redirect_host })}</span>
                </p>
              )}
              {data.client.new && (
                <p role="alert" className="flex gap-2 rounded-xl border-2 border-amber-400 bg-amber-50 p-3 text-sm text-amber-900">
                  <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                  <span>{t("mcpc2.newWarning")}</span>
                </p>
              )}
              <p className="flex gap-2 rounded-xl bg-surface-2 p-3 text-sm text-muted">
                <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                <span>{t("mcpc.consent.unverified")}</span>
              </p>
            </div>
            <div>
              <p className="mb-2 font-medium">{t("mcpc.consent.canTitle")}</p>
              <ul className="space-y-1.5 text-sm">
                {(["can1", "can2", "can3"] as const).map((k) => (
                  <li key={k} className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden />{t(`mcpc.consent.${k}`)}</li>
                ))}
              </ul>
            </div>
            {orgs.length ? (
              <label className="block space-y-1">
                <span className="text-sm font-medium">{t("mcpc.consent.chooseOrg")}</span>
                <select value={chosen} onChange={(e) => setOrg(e.target.value)}
                  className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2.5 outline-none focus:border-accent">
                  {orgs.map((o) => <option key={o.slug} value={o.slug}>{o.name}</option>)}
                </select>
              </label>
            ) : (
              <p role="alert" className="rounded-xl bg-surface-2 p-3 text-sm">{t("mcpc.consent.noOrgs")}</p>
            )}
            <div className="space-y-1 text-xs text-muted">
              <p>{t("mcpc.consent.sendsTo", { host: data.client.redirect_host })}</p>
              <p>{t("mcpc2.fullAddress")} <code className="break-all">{data.client.redirect_uri}</code></p>
            </div>
            {err && <p role="alert" className="text-sm text-bad">{err}</p>}
            <div className="flex gap-3">
              <Button variant="outline" className="flex-1" loading={busy === "deny"} disabled={!!busy} onClick={() => void decide("deny")}>
                {t("mcpc.consent.deny")}
              </Button>
              <Button className="flex-1" loading={busy === "approve"} disabled={!!busy || !chosen} onClick={() => void decide("approve")}>
                {t("mcpc.consent.approve")}
              </Button>
            </div>
          </>
        )}
      </Card>
    </main>
  );
}
