import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, CheckCircle2, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card, Toggle } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { confirmDialog } from "@/lib/dialog";
import { orgs } from "@/lib/orgs";
import { sso, type SsoConfig, type SsoPatch, type SsoProvider } from "@/lib/sso";

const input = "w-full rounded-lg border-2 border-line bg-surface px-3 py-1.5 text-sm";

/** Cockpit → Settings (admins): sign in with the organisation's Google Workspace or Microsoft Entra ID, limited to
 * email domains proved with a DNS TXT record. Only owners can require SSO (password sign-in off for the domain). */
export function SsoCard({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const key = ["org-sso", slug];
  const { data: cfg } = useQuery({ queryKey: key, queryFn: () => sso.config(slug) });
  const { data: org } = useQuery({ queryKey: ["org", slug], queryFn: () => orgs.get(slug) });
  const { data: groups } = useQuery({ queryKey: ["org-groups", slug], queryFn: () => orgs.groups(slug) });
  const [draft, setDraft] = useState<SsoPatch>({});
  const [domain, setDomain] = useState("");
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  if (!cfg) return null;
  const v = { ...cfg, ...draft } as SsoConfig & SsoPatch;
  const isOwner = org?.role === "owner";
  const verified = cfg.domains.filter((d) => d.verified);
  const why = (x: unknown) => {
    const code = x instanceof ApiError ? String(x.data?.code ?? x.data?.detail ?? "") : "";
    return code ? t(`orgx.sso.err.${code}`, { defaultValue: t("mentor.errors.generic") }) : t("mentor.errors.generic");
  };
  const set = (patch: SsoPatch) => setDraft((d) => ({ ...d, ...patch }));
  async function save(extra: SsoPatch = {}) {
    setErr("");
    setMsg("");
    try {
      qc.setQueryData(key, await sso.save(slug, { ...draft, ...extra }));
      setDraft({});
      setMsg(t("orgx.sso.saved"));
    } catch (x) {
      setErr(why(x));
    }
  }
  async function addDomain(e: FormEvent) {
    e.preventDefault();
    setErr("");
    try {
      await sso.addDomain(slug, domain.trim());
      setDomain("");
      void qc.invalidateQueries({ queryKey: key });
    } catch (x) {
      setErr(why(x));
    }
  }
  async function verify(id: number) {
    setErr("");
    try {
      await sso.verifyDomain(slug, id);
      void qc.invalidateQueries({ queryKey: key });
    } catch (x) {
      setErr(why(x));
    }
  }
  async function toggleEnforce(on: boolean) {
    if (on && !(await confirmDialog(t("orgx.sso.enforceConfirm"), { danger: true }))) return;
    await save({ enforced: on });
  }
  return (
    <Card className="space-y-4">
      <div>
        <h2 className="flex items-center gap-2 font-display text-lg font-bold"><Building2 className="h-5 w-5 text-accent" /> {t("orgx.sso.title")}</h2>
        <p className="text-sm text-muted">{t("orgx.sso.sub")}</p>
      </div>

      <section className="space-y-2">
        <h3 className="font-semibold">{t("orgx.sso.domains")}</h3>
        <p className="text-xs text-muted">{t("orgx.sso.domainsHint")}</p>
        {cfg.domains.map((d) => (
          <div key={d.id} className="space-y-1 rounded-lg border border-line p-2 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono">{d.domain}</span>
              {d.verified
                ? <span className="flex items-center gap-1 text-xs font-semibold text-good"><CheckCircle2 className="h-3.5 w-3.5" /> {t("orgx.sso.verified")}</span>
                : <span className="text-xs font-semibold text-amber-700">{t("orgx.sso.unverified")}</span>}
              {d.failing_since && <span className="text-xs text-bad">{t("orgx.sso.failing")}</span>}
              <span className="ml-auto flex gap-1">
                {!d.verified && <Button variant="outline" className="py-0.5 text-xs" onClick={() => void verify(d.id)}>{t("orgx.sso.verify")}</Button>}
                <Button variant="ghost" className="py-0.5 text-xs text-bad" aria-label={t("orgx.sso.remove", { domain: d.domain })}
                  onClick={async () => { if (await confirmDialog(t("orgx.sso.removeConfirm", { domain: d.domain }))) { await sso.removeDomain(slug, d.id); void qc.invalidateQueries({ queryKey: key }); } }}>
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </span>
            </div>
            {!d.verified && (
              <p className="text-xs text-muted">
                {t("orgx.sso.txtHowto", { name: d.txt_name, alt: d.txt_alt_name })}{" "}
                <code className="break-all rounded bg-surface-2 px-1 font-mono">{d.txt_value}</code>
              </p>
            )}
          </div>
        ))}
        <form onSubmit={(e) => void addDomain(e)} className="flex gap-2">
          <input value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="yourcompany.com" aria-label={t("orgx.sso.addDomain")} className={input} maxLength={253} />
          <Button type="submit" variant="outline" disabled={!domain.includes(".")}>{t("orgx.sso.addDomain")}</Button>
        </form>
      </section>

      <section className="space-y-2">
        <h3 className="font-semibold">{t("orgx.sso.provider")}</h3>
        <select value={v.provider} onChange={(e) => set({ provider: e.target.value as SsoProvider })} aria-label={t("orgx.sso.provider")} className={input}>
          <option value="google">{t("orgx.sso.google")}</option>
          <option value="microsoft">{t("orgx.sso.microsoft")}</option>
        </select>
        <label className="block text-sm">{t("orgx.sso.clientId")}
          <input value={v.client_id ?? ""} onChange={(e) => set({ client_id: e.target.value })} className={input} maxLength={200} />
        </label>
        <label className="block text-sm">{t("orgx.sso.clientSecret")}
          <input type="password" autoComplete="new-password" value={draft.client_secret ?? ""} onChange={(e) => set({ client_secret: e.target.value })}
            placeholder={cfg.client_secret ? t("orgx.sso.secretSaved", { masked: cfg.client_secret }) : ""} className={input} maxLength={500} />
        </label>
        {v.provider === "microsoft" && (
          <label className="block text-sm">{t("orgx.sso.tenantId")}
            <input value={v.tenant_id ?? ""} onChange={(e) => set({ tenant_id: e.target.value })} placeholder="00000000-0000-0000-0000-000000000000" className={input} maxLength={36} />
          </label>
        )}
        <p className="text-xs text-muted">{t("orgx.sso.redirectHint")} <code className="break-all rounded bg-surface-2 px-1 font-mono">{cfg.redirect_uri}</code></p>
      </section>

      <section className="space-y-2">
        <h3 className="font-semibold">{t("orgx.sso.hosted")}</h3>
        {!verified.length && <p className="text-xs text-muted">{t("orgx.sso.verifyFirst")}</p>}
        <div className="flex flex-wrap gap-3 text-sm">
          {verified.map((d) => (
            <label key={d.id} className="flex items-center gap-1.5">
              <input type="checkbox" checked={(v.hosted_domains ?? []).includes(d.domain)}
                onChange={(e) => set({ hosted_domains: e.target.checked ? [...(v.hosted_domains ?? []), d.domain] : (v.hosted_domains ?? []).filter((x) => x !== d.domain) })} />
              {d.domain}
            </label>
          ))}
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="text-sm">{t("orgx.sso.defaultRole")}
            <select value={v.default_role} onChange={(e) => set({ default_role: e.target.value as "learner" | "manager" })} className={input}>
              <option value="learner">{t("org.roles.learner")}</option>
              <option value="manager">{t("org.roles.manager")}</option>
            </select>
          </label>
          <label className="text-sm">{t("orgx.sso.defaultClass")}
            <select value={v.default_group_id ?? ""} onChange={(e) => set({ default_group_id: e.target.value ? Number(e.target.value) : null })} className={input}>
              <option value="">{t("orgx.sso.noClass")}</option>
              {groups?.filter((g) => g.name !== "Everyone").map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
          </label>
        </div>
      </section>

      <div className="flex flex-wrap items-center gap-4">
        <Toggle checked={!!v.enabled} onChange={(on) => set({ enabled: on })} label={t("orgx.sso.enable")} />
        <Button onClick={() => void save()}>{t("orgx.sso.save")}</Button>
      </div>
      <div className="space-y-1 rounded-xl border border-line p-3">
        <Toggle checked={cfg.enforced} onChange={(on) => void toggleEnforce(on)} label={t("orgx.sso.enforce")} />
        <p className="text-xs text-muted">{isOwner ? t("orgx.sso.enforceHint") : t("orgx.sso.ownerOnly")}</p>
      </div>
      {msg && <p role="status" className="text-sm text-good">{msg}</p>}
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
    </Card>
  );
}
