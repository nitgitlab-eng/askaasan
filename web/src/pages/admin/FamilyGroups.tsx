import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Pager } from "@/components/admin/Pager";
import { Button, Card } from "@/components/ui";
import { canSee, date, query, type Paged } from "@/lib/admin";
import { api } from "@/lib/api";
import { rupees } from "@/lib/billing";
import { cn } from "@/lib/cn";
import { useMe } from "@/lib/useMe";

interface GroupRow { id: number; owner: string; plan: string | null; active_until: string | null; max_members: number; members_count: number; members: string[]; pending_invites: number; created_at: string }
interface GiftRow { id: number; order_id: number; buyer: string; recipient: string; plan: string; amount_paise: number; mode: string; status: "unpaid" | "pending" | "sent" | "not_sent" | "claimed" | "void"; code_last4: string; expires_at: string | null; created_at: string; sent_at: string | null; claimed_at: string | null }
const input = "rounded-lg border-2 border-line bg-surface px-2 py-1.5 text-sm";
const GIFT_TONE: Record<GiftRow["status"], string> = { unpaid: "bg-surface-2", pending: "bg-surface-2", sent: "bg-accent/15", not_sent: "bg-amber-100 text-amber-800", claimed: "bg-good/15 text-good", void: "bg-bad/15 text-bad" };

/** Finance + support: every family group (owner, plan, members, pending invites); finance also sees gifted plans. */
export default function AdminFamilyGroups() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [giftPage, setGiftPage] = useState(1);
  const gq = query({ q: search, page });
  const { data } = useQuery({
    queryKey: ["admin-family-groups", gq],
    queryFn: () => api<Paged<GroupRow> & { groups: number; members: number }>(`/api/admin/family-groups/${gq}`),
  });
  const showGifts = !!me && canSee(me.staff_roles ?? ["superadmin"], "gifts");
  const fq = query({ q: search, page: giftPage });
  const { data: gifts } = useQuery({
    queryKey: ["admin-gifts", fq],
    queryFn: () => api<Paged<GiftRow>>(`/api/admin/gifts/${fq}`),
    enabled: showGifts,
  });

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("admin.family.title")}</h1>
        <p className="text-muted">{t("admin.family.sub")}</p>
      </header>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setSearch(q.trim()); setPage(1); setGiftPage(1); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("admin.family.searchPh")} aria-label={t("admin.family.search")} className={cn(input, "w-80")} />
        <Button type="submit" variant="outline"><Search className="h-4 w-4" /> {t("admin.family.search")}</Button>
      </form>

      <Card className="space-y-3">
        <div className="flex flex-wrap items-baseline gap-3">
          <h2 className="flex-1 font-display text-xl font-bold">{t("admin.family.groups")}</h2>
          {data && <span className="text-sm text-muted">{t("admin.family.totals", { groups: data.groups, members: data.members })}</span>}
        </div>
        {data && (data.results.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[36rem] text-sm">
              <thead className="text-left text-xs text-muted">
                <tr><th className="py-2">{t("admin.family.th.owner")}</th><th>{t("admin.family.th.plan")}</th><th>{t("admin.family.th.members")}</th><th>{t("admin.family.th.invites")}</th><th>{t("admin.family.th.until")}</th></tr>
              </thead>
              <tbody>
                {data.results.map((g) => (
                  <tr key={g.id} className="border-t border-line align-top">
                    <td className="py-2 font-medium">{g.owner}</td>
                    <td>{g.plan ?? <span className="text-muted">{t("admin.family.noPlan")}</span>}</td>
                    <td>{g.members_count}/{g.max_members || "—"}{!!g.members.length && <span className="block text-xs text-muted">{g.members.join(", ")}</span>}</td>
                    <td className="tabular-nums">{g.pending_invites}</td>
                    <td>{date(g.active_until)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="text-sm text-muted">{t("admin.family.none")}</p>)}
        {data && <Pager page={data.page} pages={data.pages} count={data.count} onPage={setPage} csvUrl={`/api/admin/family-groups/${query({ q: search, export: "csv" })}`} csvName="aasan-family-groups.csv" />}
      </Card>

      {showGifts && (
        <Card className="space-y-3">
          <h2 className="font-display text-xl font-bold">{t("admin.family.gifts")}</h2>
          {gifts && (gifts.results.length ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[36rem] text-sm">
                <thead className="text-left text-xs text-muted">
                  <tr><th className="py-2">{t("admin.family.th.buyer")}</th><th>{t("admin.family.th.recipient")}</th><th>{t("admin.family.th.plan")}</th><th>{t("admin.family.th.amount")}</th><th>{t("admin.family.th.status")}</th><th>{t("admin.family.th.code")}</th><th>{t("admin.family.th.when")}</th></tr>
                </thead>
                <tbody>
                  {gifts.results.map((g) => (
                    <tr key={g.id} className="border-t border-line">
                      <td className="py-2">{g.buyer}</td>
                      <td>{g.recipient}</td>
                      <td>{g.plan}</td>
                      <td className="tabular-nums">{rupees(g.amount_paise)}{g.mode === "test" && <span className="text-xs text-muted"> · {t("adminPay.testTag")}</span>}</td>
                      <td><span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", GIFT_TONE[g.status])}>{t(`admin.family.giftStatus.${g.status}`)}</span></td>
                      <td className="font-mono text-xs">{g.code_last4 ? `…${g.code_last4}` : "—"}</td>
                      <td>{date(g.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="text-sm text-muted">{t("admin.family.noGifts")}</p>)}
          {gifts && <Pager page={gifts.page} pages={gifts.pages} count={gifts.count} onPage={setGiftPage} csvUrl={`/api/admin/gifts/${query({ q: search, export: "csv" })}`} csvName="aasan-gifts.csv" />}
        </Card>
      )}
    </div>
  );
}
