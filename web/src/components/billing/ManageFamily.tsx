import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Users, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card } from "@/components/ui";
import { localeOf } from "@/i18n/languages";
import { ApiError } from "@/lib/api";
import { billing, type FamilyInviteResult, type FamilyState } from "@/lib/billing";
import { cn } from "@/lib/cn";
import { confirmDialog } from "@/lib/dialog";

const KNOWN = ["bad_email", "invite_self", "no_family_plan", "family_full", "family_already", "invite_limit", "invite_invalid", "invite_used",
  "invite_expired", "invite_not_for_you", "verify_email_first", "seat_covered", "family_inactive", "too_many_attempts", "not_in_family"];

/** Family plan on the Plans page: the owner's panel (members, invites, seats), the member's banner, or a code box. */
export function ManageFamily() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["billing-family"], queryFn: billing.family.get });
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [shared, setShared] = useState<FamilyInviteResult["links"]>([]);
  if (!data) return null;
  const date = (d: string) => new Date(d).toLocaleDateString(localeOf(i18n.language), { day: "numeric", month: "short", year: "numeric" });
  const errText = (e: unknown) => {
    const c = e instanceof ApiError ? String(e.data?.code ?? "") : "";
    return KNOWN.includes(c) ? t(`billing.family.errors.${c}`) : t("billing.family.errors.generic");
  };

  async function run(fn: () => Promise<unknown>, ok?: string) {
    setBusy(true);
    setMsg(null);
    try {
      const out = await fn();
      if (out && typeof out === "object" && "role" in out) qc.setQueryData(["billing-family"], out as FamilyState);
      else void qc.invalidateQueries({ queryKey: ["billing-family"] });
      void qc.invalidateQueries({ queryKey: ["billing"] });
      if (ok) setMsg({ ok: true, text: ok });
      return out;
    } catch (e) {
      setMsg({ ok: false, text: errText(e) });
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function invite(e: FormEvent) {
    e.preventDefault();
    const out = (await run(() => billing.family.invite(email.trim()))) as FamilyInviteResult | null;
    if (!out) return;
    setEmail("");
    setShared(out.links);
    setMsg({ ok: true, text: out.emailed ? t("billing.family.invited", { email: out.invite.email }) : t("billing.family.shareByHand") });
  }

  const status = msg && <p role="status" className={cn("text-sm", msg.ok ? "text-good" : "text-bad")}>{msg.text}</p>;

  if (data.role === "member") {
    return (
      <Card id="family" className="space-y-2 border-2 border-accent/40">
        <p className="flex items-center gap-2 font-semibold"><Users className="h-5 w-5 text-accent" /> {t("billing.family.memberBanner", { owner: data.owner_name, plan: data.plan?.name ?? "" })}</p>
        {data.plan ? <p className="text-sm text-muted">{data.active_until ? t("billing.family.until", { date: date(data.active_until) }) : null}</p> : <p className="text-sm text-muted">{t("billing.family.lapsed")}</p>}
        <Button variant="outline" loading={busy} onClick={async () => { if (await confirmDialog(t("billing.family.leaveConfirm"), { danger: true })) void run(billing.family.leave, t("billing.family.left")); }}>{t("billing.family.leave")}</Button>
        {status}
      </Card>
    );
  }

  if (data.role === "owner" || data.can_create) {
    const members = data.members ?? [];
    const invites = data.invites ?? [];
    const left = data.role === "owner" ? (data.seats_left ?? 0) : Math.max(0, data.max_members - 1);
    return (
      <Card id="family" className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Users className="h-5 w-5 text-accent" />
          <h2 className="flex-1 font-display text-lg font-bold">{t("billing.family.title")}</h2>
          <span className="text-sm text-muted">{t("billing.family.seats", { used: Math.max(1, members.length) + invites.length, max: data.max_members })}</span>
        </div>
        {!data.plan && <p className="text-sm text-amber-800 dark:text-amber-200">{t("billing.family.ownerLapsed")}</p>}
        <p className="text-sm text-muted">{t("billing.family.ownerHint", { count: data.max_members })}</p>
        {!!members.length && (
          <ul className="divide-y divide-line text-sm">
            {members.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center gap-2 py-2">
                <span className="flex-1 font-medium">{m.name}{m.email && <span className="font-normal text-muted"> · {m.email}</span>}</span>
                {m.is_owner ? <span className="rounded-full bg-accent/15 px-2 py-0.5 text-xs font-semibold">{t("billing.family.owner")}</span> : (
                  <Button variant="ghost" className="py-1 text-sm" disabled={busy} onClick={async () => { if (await confirmDialog(t("billing.family.removeConfirm", { name: m.name }), { danger: true })) void run(() => billing.family.remove(m.id), t("billing.family.removed")); }}>{t("billing.family.remove")}</Button>
                )}
              </li>
            ))}
          </ul>
        )}
        {!!invites.length && (
          <div className="space-y-1">
            <p className="text-sm font-semibold">{t("billing.family.pending")}</p>
            <ul className="space-y-1 text-sm">
              {invites.map((i) => (
                <li key={i.id} className="flex items-center gap-2">
                  <span className="flex-1">{i.email} <span className="text-xs text-muted">· {t("billing.family.expires", { date: date(i.expires_at) })}</span></span>
                  <button type="button" aria-label={t("billing.family.revoke", { email: i.email })} title={t("billing.family.revoke", { email: i.email })} disabled={busy} onClick={() => void run(() => billing.family.revokeInvite(i.id))} className="rounded p-1 text-muted hover:text-bad"><X className="h-4 w-4" /></button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {data.plan && left > 0 && (
          <form onSubmit={invite} className="flex flex-wrap items-end gap-2">
            <label className="flex flex-1 flex-col text-sm font-medium">{t("billing.family.inviteLabel")}
              <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} maxLength={254} className="rounded-xl border-2 border-line bg-surface px-3 py-2" /></label>
            <Button type="submit" loading={busy} disabled={!email.trim()}>{t("billing.family.invite")}</Button>
          </form>
        )}
        {shared.map((s) => (
          <div key={s.link} className="space-y-1 rounded-xl bg-surface-2 p-3 text-sm">
            <p>{t("billing.family.shareLine", { email: s.email, code: s.code })}</p>
            <p className="flex items-center gap-2 break-all font-mono text-xs">{s.link}
              <button type="button" aria-label={t("billing.family.copy")} title={t("billing.family.copy")} onClick={() => void navigator.clipboard?.writeText(s.link)} className="shrink-0 text-accent"><Copy className="h-4 w-4" /></button></p>
          </div>
        ))}
        {data.role === "owner" && members.length > 1 && (
          <button type="button" className="text-sm font-semibold text-bad" disabled={busy} onClick={async () => { if (await confirmDialog(t("billing.family.disbandConfirm"), { danger: true })) void run(billing.family.leave, t("billing.family.disbanded")); }}>{t("billing.family.disband")}</button>
        )}
        {status}
      </Card>
    );
  }

  return (
    <Card id="family" className="space-y-2">
      <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); void run(() => billing.family.accept({ code }), t("billing.family.joined")).then((r) => r && setCode("")); }}>
        <label className="flex flex-col text-sm font-medium">{t("billing.family.codeLabel")}
          <input value={code} onChange={(e) => setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))} maxLength={6} placeholder="ABC234" className="w-36 rounded-xl border-2 border-line bg-surface px-3 py-2 font-mono uppercase" /></label>
        <Button type="submit" variant="outline" loading={busy} disabled={code.length !== 6}>{t("billing.family.join")}</Button>
      </form>
      {status}
    </Card>
  );
}
