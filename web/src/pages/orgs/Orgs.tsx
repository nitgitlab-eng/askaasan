import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, KeyRound, Plus } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { Button, Card, Segmented } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { resendVerification } from "@/lib/auth";
import { orgs } from "@/lib/orgs";

export default function OrgsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data } = useQuery({ queryKey: ["orgs"], queryFn: orgs.list });
  const [name, setName] = useState("");
  const [kind, setKind] = useState("school");
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState("");
  const [createErr, setCreateErr] = useState("");

  async function create(e: FormEvent) {
    e.preventDefault();
    setCreateErr("");
    try {
      const o = await orgs.create(name.trim(), kind);
      void qc.invalidateQueries({ queryKey: ["orgs"] });
      navigate(`/org/${o.slug}`);
    } catch {
      setCreateErr(t("mentor.errors.generic")); // e.g. the 5-org limit or a reserved name: say so instead of doing nothing
    }
  }
  async function join(e: FormEvent) {
    e.preventDefault();
    setMsg("");
    try {
      const o = await orgs.join(code.trim());
      setMsg(t("org.joined", { org: o.name, group: o.group }));
      setCode("");
      void qc.invalidateQueries({ queryKey: ["orgs"] });
    } catch (err) {
      setMsg(err instanceof ApiError && err.status === 404 ? t("org.badCode") : t("mentor.errors.generic"));
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("org.title")}</h1>
        <p className="text-muted">{t("org.sub")}</p>
      </header>
      <div className="grid gap-4 sm:grid-cols-2">
        {data?.map((o) => (
          <Link key={o.id} to={o.role === "learner" ? "/learn" : `/org/${o.slug}`}>
            <Card className="flex items-center gap-3 transition hover:border-accent">
              <Building2 className="h-8 w-8 text-accent" />
              <div className="min-w-0 flex-1">
                <p className="truncate font-display text-lg font-bold">{o.name}</p>
                <p className="text-xs text-muted">{t(`org.roles.${o.role}`)} · {t("org.membersN", { count: o.members })}</p>
              </div>
            </Card>
          </Link>
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <form onSubmit={join} className="space-y-3">
            <h2 className="flex items-center gap-2 font-display text-xl font-bold"><KeyRound className="h-5 w-5 text-accent" /> {t("org.joinTitle")}</h2>
            <input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} maxLength={10} placeholder="ABC2345" className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2.5 font-mono tracking-widest outline-none focus:border-accent" aria-label={t("org.code")} />
            <p className="text-xs text-muted">{t("org.privacyNote")}</p>
            <Button type="submit" disabled={code.trim().length < 5}>{t("org.join")}</Button>
            {msg && <p role="status" className="text-sm">{msg}</p>}
          </form>
        </Card>
        <Card>
          <form onSubmit={create} className="space-y-3">
            <h2 className="flex items-center gap-2 font-display text-xl font-bold"><Plus className="h-5 w-5 text-accent" /> {t("org.createTitle")}</h2>
            <input value={name} onChange={(e) => setName(e.target.value)} minLength={2} maxLength={120} placeholder={t("org.namePlaceholder")} className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2.5 outline-none focus:border-accent" aria-label={t("org.name")} />
            <Segmented label={t("org.kind")} value={kind} onChange={setKind} options={["school", "college", "coaching", "company"].map((k) => ({ value: k, label: t(`org.kinds.${k}`) }))} />
            <Button type="submit" disabled={name.trim().length < 2}>{t("org.create")}</Button>
            {createErr && <p role="alert" className="text-sm text-bad">{createErr}</p>}
          </form>
        </Card>
      </div>
    </div>
  );
}

export function JoinOrInvite({ mode }: { mode: "code" | "invite" }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const value = location.pathname.split("/").filter(Boolean)[1] ?? "";
  // A join code / invite token is one-time: POST it exactly once (a query would re-send it on remount or refetch).
  const { mutate, data, error, isPending, isIdle } = useMutation({
    mutationFn: () => (mode === "code" ? orgs.join(value) : orgs.acceptInvite(value)),
  });
  const sent = useRef("");
  const [resent, setResent] = useState("");
  useEffect(() => {
    const key = `${mode}:${value}`;
    if (sent.current === key) return; // StrictMode runs effects twice in development
    sent.current = key;
    mutate();
  }, [mode, value, mutate]);
  const code = error instanceof ApiError ? (error.data?.code as string) : null;
  return (
    <div className="mx-auto max-w-md px-4 py-16 text-center">
      <Card className="space-y-3">
        {(isPending || isIdle) && <p>{t("common.loading")}</p>}
        {data && (
          <>
            <p className="text-5xl">🎉</p>
            <p className="font-display text-2xl font-bold">{t("org.welcome", { org: data.name })}</p>
            <p className="text-sm text-muted">{t("org.privacyNote")}</p>
            <Button onClick={() => navigate(data.role === "learner" ? "/" : `/org/${data.slug}`)}>{t("org.go")}</Button>
          </>
        )}
        {error && <p className="text-bad">{t(`org.joinErrors.${code ?? "generic"}`, { defaultValue: t("mentor.errors.generic") })}</p>}
        {code === "verify_email_first" && (
          <>
            <Button variant="outline" onClick={() => void resendVerification().then(setResent)}>{t("auth.resend")}</Button>
            {resent && <p role="status" className="text-sm text-muted">{resent}</p>}
          </>
        )}
      </Card>
    </div>
  );
}
