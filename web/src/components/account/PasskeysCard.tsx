import { browserSupportsWebAuthn, startRegistration } from "@simplewebauthn/browser";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { promptDialog } from "@/lib/dialog";
import { localeOf } from "@/i18n/languages";
import { Button, Card } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { reauthenticate, resendVerification } from "@/lib/auth";

type Passkey = { id: number; name: string; created_at: string; last_used_at: string | null };

/** Register, rename and remove passkeys (sign-in with fingerprint / face / screen lock). */
export function PasskeysCard() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["passkeys"], queryFn: () => api<Passkey[]>("/api/users/passkeys/") });
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [unverified, setUnverified] = useState(false);
  const date = (s: string) => new Date(s).toLocaleDateString(localeOf(i18n.language), { day: "numeric", month: "short", year: "numeric" });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["passkeys"] });

  async function add() {
    setMsg("");
    if (!browserSupportsWebAuthn()) return setMsg(t("passkeys.unsupported"));
    setBusy(true);
    try {
      const begin = () => api<{ key: string; options: string }>("/api/users/passkey/register/begin/", { method: "POST" });
      let started: { key: string; options: string };
      try {
        started = await begin();
      } catch (e) {
        const code = e instanceof ApiError && e.status === 403 ? (e.data?.code as string | undefined) : undefined;
        if (code === "email_unverified") {
          setMsg(t("passkeys.verifyFirst"));
          setUnverified(true);
          return;
        }
        // A passkey is a lasting sign-in key: the server wants proof it's really you first, then we ask again.
        if (code !== "reauth_required" || !(await reauthenticate((e as ApiError).data?.methods as string[] ?? []))) throw e;
        started = await begin();
      }
      const { key, options } = started;
      const credential = await startRegistration({ optionsJSON: JSON.parse(options) });
      const name = (await promptDialog(t("passkeys.namePrompt"), { defaultValue: navigator.platform || "Passkey" })) || "Passkey";
      await api("/api/users/passkey/register/complete/", { method: "POST", json: { key, credential, name } });
      setMsg(t("passkeys.added"));
      refresh();
    } catch (e) {
      setMsg(e instanceof ApiError ? t("mentor.errors.generic") : t("passkeys.cancelled"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-3">
      <h2 className="flex items-center gap-2 font-display text-xl font-bold"><KeyRound className="h-5 w-5 text-accent" /> {t("passkeys.title")}</h2>
      <p className="text-sm text-muted">{t("passkeys.sub")}</p>
      {!data?.length ? <p className="text-sm text-muted">{t("passkeys.none")}</p> : (
        <ul className="divide-y divide-line">
          {data.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div>
                <p className="font-semibold">{p.name}</p>
                <p className="text-xs text-muted">{t("passkeys.created", { date: date(p.created_at) })}{p.last_used_at ? ` · ${t("passkeys.used", { date: date(p.last_used_at) })}` : ""}</p>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" onClick={async () => {
                  const name = await promptDialog(t("passkeys.namePrompt"), { defaultValue: p.name });
                  if (name) { await api(`/api/users/passkeys/${p.id}/`, { method: "PATCH", json: { name } }); refresh(); }
                }}>{t("passkeys.rename")}</Button>
                <Button variant="outline" aria-label={t("passkeys.remove")} onClick={async () => {
                  try { await api(`/api/users/passkeys/${p.id}/`, { method: "DELETE" }); refresh(); }
                  catch (e) { setMsg(e instanceof ApiError && e.status === 409 ? t("passkeys.last") : t("mentor.errors.generic")); }
                }}><Trash2 className="h-4 w-4" /></Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <Button onClick={add} loading={busy}><KeyRound className="h-4 w-4" /> {t("passkeys.add")}</Button>
      {msg && <p role="status" className="text-sm text-muted">{msg}</p>}
      {unverified && <Button variant="outline" className="py-1.5 text-sm" onClick={() => void resendVerification().then(setMsg)}>{t("auth.resend")}</Button>}
    </Card>
  );
}
