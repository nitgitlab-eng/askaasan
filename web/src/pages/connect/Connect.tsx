import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Plug, Unplug } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { confirmDialog } from "@/lib/dialog";
import { Button, Card, Segmented } from "@/components/ui";
import { localeOf } from "@/i18n/languages";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { connect, type AuditRow, type ConnectedClient } from "@/lib/connect";
import { copyText } from "@/lib/guests";

const TOOL_KEYS = ["org_overview", "list_members", "list_assignments", "assignment_progress", "list_courses", "get_course_outline",
  "list_surveys", "survey_results", "create_guest_lesson"];
const EVENT_KEYS = ["approve", "deny", "code_exchange", "code_reuse", "refresh_reuse", "role_lost", "revoke", "client_revoke"];

function useDate() {
  const { i18n } = useTranslation();
  return (d: string) => new Date(d).toLocaleString(localeOf(i18n.language), { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

function ServerUrl({ url }: { url: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  return (
    <div className="space-y-1">
      <p className="text-sm font-medium">{t("mcpc.serverUrl")}</p>
      <div className="flex flex-wrap items-center gap-2">
        <code className="min-w-0 flex-1 break-all rounded-xl bg-surface-2 px-3 py-2.5 text-sm">{url}</code>
        <Button variant="outline" onClick={() => { copyText(url); setCopied(true); setTimeout(() => setCopied(false), 2000); }}>
          {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />} {copied ? t("mcpc.copied") : t("mcpc.copy")}
        </Button>
      </div>
    </div>
  );
}

function ClientRow({ c, slug }: { c: ConnectedClient; slug: string }) {
  const { t } = useTranslation();
  const fmt = useDate();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  async function revoke() {
    if (!(await confirmDialog(t("mcpc.revokeConfirm"), { danger: true }))) return;
    setBusy(true);
    try {
      await connect.revoke(slug, c.id);
      await qc.invalidateQueries({ queryKey: ["connect-clients", slug] });
    } finally {
      setBusy(false);
    }
  }
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-3">
      <div className="min-w-0">
        <p className="font-semibold">{c.client_name} <span className="text-sm font-normal text-muted">· {c.redirect_hosts.join(", ")}</span></p>
        <p className="text-sm text-muted">
          {t("mcpc.approvedBy", { name: c.approved_by })} · {t("mcpc.connectedOn", { date: fmt(c.created_at) })} ·{" "}
          {c.last_used_at ? t("mcpc.lastUsed", { date: fmt(c.last_used_at) }) : t("mcpc.neverUsed")} · {t("mcpc.calls", { count: c.calls })}
        </p>
      </div>
      <Button variant="outline" loading={busy} onClick={() => void revoke()}><Unplug className="h-4 w-4" /> {t("mcpc.revoke")}</Button>
    </li>
  );
}

function AuditLog({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const fmt = useDate();
  const [page, setPage] = useState(1);
  const { data } = useQuery({ queryKey: ["connect-audit", slug, page], queryFn: () => connect.audit(slug, page) });
  const toolName = (n: string) => (TOOL_KEYS.includes(n) ? t(`mcpc.tools.${n}`) : n);
  const action = (r: AuditRow) => (r.event === "tool" ? toolName(r.tool) : EVENT_KEYS.includes(r.event) ? t(`mcpc2.events.${r.event}`) : r.event);
  return (
    <Card className="space-y-3">
      <h2 className="font-display text-lg font-bold">{t("mcpc.auditTitle")}</h2>
      {!data ? <p className="text-muted">{t("common.loading")}</p> : !data.rows.length ? <p className="text-muted">{t("mcpc.noAudit")}</p> : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-muted">
              <tr>
                <th className="py-2 pr-3 font-medium">{t("mcpc.when")}</th>
                <th className="py-2 pr-3 font-medium">{t("mcpc.assistant")}</th>
                <th className="py-2 pr-3 font-medium">{t("mcpc.by")}</th>
                <th className="py-2 pr-3 font-medium">{t("mcpc.tool")}</th>
                <th className="py-2 pr-3 font-medium">{t("mcpc.details")}</th>
                <th className="py-2 font-medium">{t("mcpc.result")}</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.id} className="border-t border-line align-top">
                  <td className="whitespace-nowrap py-2 pr-3 tabular-nums">{fmt(r.created_at)}</td>
                  <td className="py-2 pr-3">{r.client_name}</td>
                  <td className="py-2 pr-3">{r.user}</td>
                  <td className="py-2 pr-3">{action(r)}</td>
                  <td className="max-w-xs break-words py-2 pr-3 text-muted">{r.args}</td>
                  <td className={cn("py-2", r.ok ? "text-emerald-700" : "text-bad")}>{r.ok ? t("mcpc.ok") : t("mcpc.failed", { code: r.error })}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && data.pages > 1 && (
        <div className="flex items-center gap-3">
          <Button variant="outline" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>{t("mcpc.prev")}</Button>
          <span className="text-sm text-muted">{t("mcpc.page", { page: data.page, pages: data.pages })}</span>
          <Button variant="outline" disabled={page >= data.pages} onClick={() => setPage((p) => p + 1)}>{t("mcpc.next")}</Button>
        </div>
      )}
    </Card>
  );
}

function Clients({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const { data } = useQuery({ queryKey: ["connect-clients", slug], queryFn: () => connect.clients(slug) });
  return (
    <Card className="space-y-1">
      <h2 className="font-display text-lg font-bold">{t("mcpc.clientsTitle")}</h2>
      {!data ? <p className="text-muted">{t("common.loading")}</p> : !data.length ? <p className="text-muted">{t("mcpc.noClients")}</p> : (
        <ul className="divide-y divide-line">{data.map((c) => <ClientRow key={c.id} c={c} slug={slug} />)}</ul>
      )}
    </Card>
  );
}

export default function ConnectPage() {
  const { t } = useTranslation();
  const { data, error, isLoading } = useQuery({ queryKey: ["connect-me"], queryFn: connect.me, retry: false });
  const [org, setOrg] = useState("");
  const slug = org || data?.orgs[0]?.slug || "";
  const forbidden = error instanceof ApiError && error.status === 403;
  return (
    <div className="mx-auto max-w-4xl space-y-5 p-4 md:p-8">
      <header className="space-y-2">
        <h1 className="flex items-center gap-2 font-display text-2xl font-extrabold"><Plug className="h-6 w-6" aria-hidden /> {t("mcpc.title")}</h1>
        <p className="text-muted">{t("mcpc.intro")}</p>
      </header>
      {isLoading && <p className="text-muted">{t("common.loading")}</p>}
      {forbidden && <Card><p>{t("mcpc.adminsOnly")}</p></Card>}
      {error && !forbidden && <Card><p role="alert" className="text-bad">{t("mcpc.error")}</p></Card>}
      {data && (
        <>
          {data.orgs.length > 1 && (
            <Segmented label={t("mcpc.org")} value={slug} onChange={setOrg} options={data.orgs.map((o) => ({ value: o.slug, label: o.name }))} />
          )}
          <Card className="space-y-4">
            <h2 className="font-display text-lg font-bold">{t("mcpc.howTitle")}</h2>
            <ServerUrl url={data.server_url} />
            <ol className="list-decimal space-y-1.5 pl-5">
              <li>{t("mcpc.step1")}</li>
              <li>{t("mcpc.step2")}</li>
              <li>{t("mcpc.step3")}</li>
            </ol>
            <p className="text-sm text-muted">{t("mcpc.note")}</p>
            <ul className="flex flex-wrap gap-2">
              {data.tools.map((x) => (
                <li key={x.name} className="rounded-full bg-surface-2 px-3 py-1 text-xs">{TOOL_KEYS.includes(x.name) ? t(`mcpc.tools.${x.name}`) : x.title}</li>
              ))}
            </ul>
          </Card>
          {slug && <Clients key={`c-${slug}`} slug={slug} />}
          {slug && <AuditLog key={`a-${slug}`} slug={slug} />}
        </>
      )}
    </div>
  );
}
