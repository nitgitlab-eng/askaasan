import { Building2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button, Field } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { isProviderUrl, sso } from "@/lib/sso";

/** "Sign in with your organisation": work email → does the domain use SSO? → off to the organisation's sign-in page. */
export function OrgSignIn({ initialEmail = "", openInitially = false }: { initialEmail?: string; openInitially?: boolean }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(openInitially);
  const [email, setEmail] = useState(initialEmail);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  async function go(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg("");
    try {
      const found = await sso.lookup(email.trim());
      if (!found.sso) {
        setMsg(t("auth.sso.notSetUp"));
        return;
      }
      const { url } = await sso.start(email.trim());
      if (!isProviderUrl(url)) throw new Error("unexpected_redirect");
      window.location.assign(url);
    } catch (err) {
      setMsg(err instanceof ApiError && err.status === 429 ? t("auth.tooMany") : t("mentor.errors.generic"));
    } finally {
      setBusy(false);
    }
  }
  if (!open) {
    return (
      <Button variant="outline" className="mt-3 w-full" onClick={() => setOpen(true)}>
        <Building2 className="h-4 w-4" /> {t("auth.sso.button")}
      </Button>
    );
  }
  return (
    <form onSubmit={(e) => void go(e)} className="mt-3 space-y-2 rounded-xl border border-line p-3" aria-label={t("auth.sso.button")}>
      <Field label={t("auth.sso.workEmail")} name="sso-email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      <Button type="submit" className="w-full" loading={busy} disabled={!email.includes("@")}>{t("auth.sso.continue")}</Button>
      {msg && <p role="status" className="text-sm text-muted">{msg}</p>}
    </form>
  );
}
