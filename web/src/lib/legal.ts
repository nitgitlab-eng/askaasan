import { useQuery } from "@tanstack/react-query";

import { api } from "./api";

export interface SiteInfo {
  brand: string; legal_name: string; address: string; city: string; support_email: string; phone: string;
  grievance_officer: string; grievance_email: string; gstin: string; refund_days: number; terms_version: string; state: string; hsn_sac: string;
}

export const useSiteInfo = () => useQuery({ queryKey: ["site-info"], queryFn: () => api<SiteInfo>("/api/legal/site/"), staleTime: 10 * 60_000 });

export const legal = {
  consent: (body: { accept: boolean; age_band: "adult" | "minor"; guardian_email?: string }) => api("/api/legal/consent/", { method: "POST", json: body }),
  deleteAccount: (confirm: string, password: string, code = "") => api<{ ok?: boolean; code?: string }>("/api/legal/delete-account/", { method: "POST", json: { confirm, password, code } }),
};
