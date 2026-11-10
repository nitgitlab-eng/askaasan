import { useQueryClient } from "@tanstack/react-query";
import { Bell, Download, ShieldCheck, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { LegalLinks } from "@/components/LegalLinks";
import { ExtensionCard } from "@/components/account/ExtensionCard";
import { FamilyCard } from "@/components/account/FamilyCard";
import { GuardianCard } from "@/components/account/GuardianCard";
import { PasskeysCard } from "@/components/account/PasskeysCard";
import { PushCard } from "@/components/account/PushCard";
import { TrainingRecordCard } from "@/components/account/TrainingRecordCard";
import { Button, Card, Toggle } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { legal } from "@/lib/legal";
import { clearOfflineData } from "@/lib/offline";
import { useMe, useUpdatePreferences } from "@/lib/useMe";
import { useAuth } from "@/stores/auth";

export default function AccountPage() {
  const qc = useQueryClient();
  const { t } = useTranslation();
  const { data: me } = useMe();
  const update = useUpdatePreferences();
  const [exporting, setExporting] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<{ code: string; orgs?: { slug: string; name: string }[] } | null>(null);

  async function download() {
    setExporting(true);
    try {
      const r = await fetch("/api/legal/export/", { headers: { Authorization: `Bearer ${useAuth.getState().access}` } });
      if (!r.ok) throw new Error();
      const url = URL.createObjectURL(await r.blob());
      Object.assign(document.createElement("a"), { href: url, download: `aasan-my-data-${new Date().toISOString().slice(0, 10)}.json` }).click();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  }

  async function remove(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await legal.deleteAccount(confirm, password, otp);
      if (r?.code === "otp_sent") {
        setOtpSent(true);
        return;
      }
      useAuth.getState().clear();
      qc.clear();
      await clearOfflineData(); // saved lessons, queued answers and guest tokens must not outlive the account
      location.replace("/login");
    } catch (x) {
      const data = x instanceof ApiError ? (x.data as { code?: string; detail?: string; orgs?: { slug: string; name: string }[] } | null) : null;
      setErr({ ...data, code: data?.code ?? (data?.detail === "too_many_attempts" ? "too_many_attempts" : "generic") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("account.title")}</h1>
        <p className="text-muted">{me?.email}</p>
      </header>
      <FamilyCard />
      <PasskeysCard />
      <ExtensionCard />
      <GuardianCard />
      <TrainingRecordCard />

      <Card className="space-y-2">
        <h2 className="flex items-center gap-2 font-display text-lg font-bold"><ShieldCheck className="h-5 w-5 text-accent" /> {t("account.privacyTitle")}</h2>
        <p className="text-sm text-muted">{t("account.privacySub")}</p>
        {me?.consent.age_band === "minor" && <p className="text-sm">{t("account.guardianOnFile")}</p>}
        <LegalLinks className="justify-start text-sm" />
      </Card>

      <Card className="space-y-3">
        <h2 className="flex items-center gap-2 font-display text-lg font-bold"><Bell className="h-5 w-5 text-accent" /> {t("account.notifTitle")}</h2>
        {me && (["email_study", "email_plan", "email_workshops", "email_winback", "kili_nudges"] as const).map((k) => (
          <div key={k} className="flex items-center justify-between gap-3">
            <div><p className="font-medium">{t(`account.notif.${k}`)}</p><p className="text-xs text-muted">{t(`account.notifSub.${k}`)}</p></div>
            <Toggle checked={me.preferences.notifications[k] ?? true} onChange={(v) => update.mutate({ notifications: { [k]: v } })} label={t(`account.notif.${k}`)} />
          </div>
        ))}
        <p className="text-xs text-muted">{t("account.notifAlways")}</p>
      </Card>
      <PushCard />

      <Card className="space-y-3">
        <h2 className="flex items-center gap-2 font-display text-lg font-bold"><Download className="h-5 w-5 text-accent" /> {t("account.exportTitle")}</h2>
        <p className="text-sm text-muted">{t("account.exportSub")}</p>
        <Button variant="outline" loading={exporting} onClick={download}>{t("account.exportBtn")}</Button>
      </Card>

      <Card className="space-y-3 border-2 border-bad/40">
        <h2 className="flex items-center gap-2 font-display text-lg font-bold text-bad"><Trash2 className="h-5 w-5" /> {t("account.deleteTitle")}</h2>
        <p className="text-sm text-muted">{t("account.deleteSub")}</p>
        <form onSubmit={remove} className="space-y-2">
          <label className="block text-sm">{t("account.typeDelete")}
            <input value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" className="mt-1 w-full rounded-xl border-2 border-line bg-surface px-3 py-2 font-mono" />
          </label>
          {me?.has_password && (
            <label className="block text-sm">{t("auth.password")}
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" className="mt-1 w-full rounded-xl border-2 border-line bg-surface px-3 py-2" />
            </label>
          )}
          {otpSent && (
            <label className="block text-sm">{t("account.otpLabel")}
              <input value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" className="mt-1 w-full rounded-xl border-2 border-line bg-surface px-3 py-2 font-mono tracking-widest" />
            </label>
          )}
          {err && (
            <p role="alert" className="text-sm text-bad">
              {err.code === "email_not_configured" ? t("mailSetup.notReady") : err.code === "send_failed" ? t("mailSetup.sendFailed") : t(`account.err.${err.code}`, { defaultValue: t("mentor.errors.generic") })}
              {err.orgs?.map((o) => <Link key={o.slug} to={`/org/${o.slug}`} className="ml-2 underline">{o.name}</Link>)}
            </p>
          )}
          <Button type="submit" className="bg-bad text-white" loading={busy} disabled={confirm.trim().toUpperCase() !== "DELETE" || (me?.has_password && !password) || (otpSent && otp.length !== 6)}>{!me?.has_password && !otpSent ? t("account.sendCode") : t("account.deleteBtn")}</Button>
        </form>
      </Card>
    </div>
  );
}
