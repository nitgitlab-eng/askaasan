import { api } from "./api";

export type CertKind = "course" | "scenario" | "test" | "workshop";
export interface PublicCertificate { code: string; learner: string; title: string; kind: CertKind; issuer: string; issued_by_type: "aasan" | "organisation"; org: string | null;
  author: string; issued_at: string; verified: boolean; verify_url: string }
export interface Certificate extends PublicCertificate { id: number; hidden: boolean; revoked: boolean; revoked_at: string | null; detail: { pct?: number } }
export interface OrgCertificate { id: number; learner: string; title: string; kind: CertKind; issued_at: string; revoked: boolean }
export interface EligibleItem { kind: CertKind; id: number; title: string; issued: boolean }

export interface CertificateFacts { kind: "certificate"; name: string; certificate: string; type: CertKind; issuer: string; issuer_type: "aasan" | "organisation"; course_by?: string; date: string; verify_url: string; score_pct?: number }
export interface ReviewFacts {
  kind: "review"; name: string; period: string; stats: Partial<Record<"minutes" | "lessons" | "active_days" | "streak" | "best_streak" | "first_try_accuracy" | "xp", number>>;
  courses: { title: string; lessons_completed: number }[]; skills: { name: string; mastery_pct: number | null }[]; certificates: string[];
}
export type ShareFacts = CertificateFacts | ReviewFacts;
export type ShareFormat = "manager" | "linkedin";
export interface ShareSource { source: "review" | "certificate"; certificateId?: number }

const b = "/api/credentials";
export const credentials = {
  mine: () => api<Certificate[]>(`${b}/`),
  setHidden: (id: number, hidden: boolean) => api<Certificate>(`${b}/${id}/`, { method: "PATCH", json: { hidden } }),
  revoke: (id: number) => api<Certificate>(`${b}/${id}/revoke/`, { method: "POST" }),
  pdfUrl: (id: number) => `${b}/${id}/pdf/`,
  verify: (code: string) => api<PublicCertificate>(`${b}/verify/${encodeURIComponent(code)}/`),
  facts: (s: ShareSource) => api<ShareFacts>(`${b}/share/facts/?source=${s.source}${s.certificateId ? `&id=${s.certificateId}` : ""}`),
  share: (s: ShareSource, format: ShareFormat) =>
    api<{ format: ShareFormat; text: string; hashtags: string[]; facts: ShareFacts }>(`${b}/share/`, { method: "POST", json: { source: s.source, certificate_id: s.certificateId, format } }),
  org: (slug: string) => api<OrgCertificate[]>(`${b}/orgs/${slug}/`),
  eligible: (slug: string, memberId: number) => api<Record<CertKind, EligibleItem[]>>(`${b}/orgs/${slug}/eligible/${memberId}/`),
  issue: (slug: string, memberId: number, kind: CertKind, id: number) => api<OrgCertificate>(`${b}/orgs/${slug}/`, { method: "POST", json: { member_id: memberId, kind, id } }),
  orgRevoke: (slug: string, id: number) => api<OrgCertificate>(`${b}/orgs/${slug}/${id}/revoke/`, { method: "POST" }),
};

/** The text that goes to the clipboard: the edited post plus hashtags (LinkedIn) as #Tags on the last line. */
export function composePost(text: string, hashtags: string[]): string {
  const tags = hashtags.map((h) => h.replace(/[^\p{L}\p{N}_]/gu, "")).filter(Boolean);
  const body = text.trim();
  return tags.length ? `${body}\n\n${tags.map((h) => `#${h}`).join(" ")}` : body;
}
