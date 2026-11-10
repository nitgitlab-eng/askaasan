import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, Save, Trash2, Upload } from "lucide-react";
import { useEffect, useState } from "react";

import { Button, Card, Toggle } from "@/components/ui";
import { postPdf } from "@/lib/admin";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { confirmDialog } from "@/lib/dialog";

export interface CertTemplate {
  id?: number;
  kind: string;
  language: string;
  layout: "classic" | "modern" | "minimal";
  colors: { ink: string; accent: string; gold: string; paper: string };
  headline: string;
  verb: string;
  logo: string;
  signature: string;
  signatory_name: string;
  signatory_title: string;
  footer_note: string;
  active: boolean;
}

const BLANK: CertTemplate = {
  kind: "",
  language: "",
  layout: "classic",
  colors: { ink: "#1f2a44", accent: "#c2410c", gold: "#b8860b", paper: "#fffaf2" },
  headline: "",
  verb: "",
  logo: "",
  signature: "",
  signatory_name: "",
  signatory_title: "",
  footer_note: "",
  active: true,
};
const KINDS: [string, string][] = [["", "Every kind"], ["course", "Course"], ["workshop", "Workshop"], ["test", "Test"], ["scenario", "Role-play"]];
const LANGS: [string, string][] = [["", "Every language"], ["en", "English"], ["ta", "தமிழ்"], ["hi", "हिन्दी"], ["te", "తెలుగు"], ["kn", "ಕನ್ನಡ"], ["ml", "മലയാളം"], ["bn", "বাংলা"], ["mr", "मराठी"], ["gu", "ગુજરાતી"]];
const ERRORS: Record<string, string> = {
  bad_logo: "The logo must be an image uploaded here.",
  bad_signature: "The signature must be an image uploaded here.",
  bad_colors: "Colours must look like #1f2a44.",
  scope_taken: "There is already a template for that kind and language.",
};
const input = "rounded-lg border-2 border-line bg-surface px-2 py-1.5 text-sm";

async function upload(file: File): Promise<string> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await api<{ url: string }>("/api/media/upload/", { method: "POST", body: fd });
  return r.url;
}

/** Certificate look: layout, colours, wording, logo, signature and signatory — per kind and language, with a live PDF
 * preview. `base` is "/api/admin/certificate-templates/" (platform) or "/api/credentials/orgs/<slug>/templates/". */
export function TemplateEditor({ base }: { base: string }) {
  const qc = useQueryClient();
  const key = ["cert-templates", base];
  const { data: list } = useQuery({ queryKey: key, queryFn: () => api<CertTemplate[]>(base) });
  const [t, setT] = useState<CertTemplate>(BLANK);
  const [preview, setPreview] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  const set = <K extends keyof CertTemplate>(k: K, v: CertTemplate[K]) => setT((x) => ({ ...x, [k]: v }));
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setMsg("");
    try { await fn(); } catch (e) {
      setMsg(ERRORS[e instanceof ApiError ? String(e.data?.code ?? "") : ""] ?? (e instanceof Error && e.message.startsWith("preview") ? "Preview failed." : "That didn't work."));
    } finally { setBusy(false); }
  };
  const { id: _id, ...body } = t;
  const save = () => run(async () => {
    const saved = await api<CertTemplate>(t.id ? `${base}${t.id}/` : base, { method: t.id ? "PATCH" : "POST", json: body });
    setT(saved);
    setMsg("Saved. New and existing certificates of this kind now use it.");
    void qc.invalidateQueries({ queryKey: key });
  });
  const show = () => run(async () => { setPreview(await postPdf(`${base}preview/`, { ...body, kind: t.kind || "course" })); });
  const pickImage = (field: "logo" | "signature") => (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) void run(async () => set(field, await upload(f)));
  };

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <select aria-label="Template" className={input} value={t.id ?? ""} onChange={(e) => setT(list?.find((x) => x.id === Number(e.target.value)) ?? BLANK)}>
            <option value="">New template…</option>
            {list?.map((x) => <option key={x.id} value={x.id}>{(KINDS.find((k) => k[0] === x.kind) ?? KINDS[0])[1]} · {(LANGS.find((l) => l[0] === x.language) ?? LANGS[0])[1]}{x.active ? "" : " (off)"}</option>)}
          </select>
          {t.id && <button type="button" aria-label="Delete template" className="text-muted hover:text-bad" onClick={async () => {
            if (!(await confirmDialog("Delete this template? Certificates fall back to the next matching one.", { danger: true }))) return;
            await api(`${base}${t.id}/`, { method: "DELETE" });
            setT(BLANK);
            void qc.invalidateQueries({ queryKey: key });
          }}><Trash2 className="h-4 w-4" /></button>}
        </div>
        <div className="flex flex-wrap gap-2">
          <label className="flex flex-col text-xs font-medium">For<select disabled={!!t.id} className={input} value={t.kind} onChange={(e) => set("kind", e.target.value)}>{KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
          <label className="flex flex-col text-xs font-medium">Language<select disabled={!!t.id} className={input} value={t.language} onChange={(e) => set("language", e.target.value)}>{LANGS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
          <label className="flex flex-col text-xs font-medium">Layout<select className={input} value={t.layout} onChange={(e) => set("layout", e.target.value as CertTemplate["layout"])}>
            <option value="classic">Classic frame</option><option value="modern">Modern band</option><option value="minimal">Minimal</option>
          </select></label>
        </div>
        <div className="flex flex-wrap gap-3">
          {(["ink", "accent", "gold", "paper"] as const).map((c) => (
            <label key={c} className="flex flex-col items-center text-xs font-medium capitalize">{c}
              <input type="color" value={t.colors[c]} onChange={(e) => set("colors", { ...t.colors, [c]: e.target.value })} className="h-9 w-12 cursor-pointer rounded border border-line" />
            </label>
          ))}
        </div>
        <label className="flex flex-col text-xs font-medium">Headline (empty = default)<input maxLength={80} className={input} value={t.headline} placeholder="CERTIFICATE OF COMPLETION" onChange={(e) => set("headline", e.target.value)} /></label>
        <label className="flex flex-col text-xs font-medium">Line before the title (empty = default)<input maxLength={120} className={input} value={t.verb} placeholder="has successfully completed the course" onChange={(e) => set("verb", e.target.value)} /></label>
        <div className="flex flex-wrap gap-2">
          <label className="flex flex-col text-xs font-medium">Signatory<input maxLength={80} className={input} value={t.signatory_name} placeholder="Dr. Meena Sundaram" onChange={(e) => set("signatory_name", e.target.value)} /></label>
          <label className="flex flex-col text-xs font-medium">Title<input maxLength={80} className={input} value={t.signatory_title} placeholder="Principal" onChange={(e) => set("signatory_title", e.target.value)} /></label>
        </div>
        <label className="flex flex-col text-xs font-medium">Footer note<input maxLength={160} className={input} value={t.footer_note} placeholder="Accredited by …" onChange={(e) => set("footer_note", e.target.value)} /></label>
        <div className="flex flex-wrap gap-4">
          {(["logo", "signature"] as const).map((f) => (
            <div key={f} className="space-y-1 text-xs font-medium capitalize">
              <span>{f}</span>
              {t[f] && <img src={t[f]} alt={f} className="h-10 rounded border border-line bg-white object-contain" />}
              <div className="flex gap-2">
                <label className="flex cursor-pointer items-center gap-1 rounded-lg border border-line px-2 py-1"><Upload className="h-3 w-3" /> Upload<input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" onChange={pickImage(f)} /></label>
                {t[f] && <button type="button" className="text-bad" onClick={() => set(f, "")}>Remove</button>}
              </div>
            </div>
          ))}
        </div>
        <Toggle checked={t.active} onChange={(v) => set("active", v)} label="In use" />
        <div className="flex gap-2">
          <Button onClick={() => void save()} loading={busy}><Save className="h-4 w-4" /> Save</Button>
          <Button variant="outline" onClick={() => void show()} disabled={busy}><Eye className="h-4 w-4" /> Preview</Button>
        </div>
        {msg && <p role="status" className="text-sm">{msg}</p>}
      </Card>
      <Card className={cn("flex min-h-80 items-center justify-center p-2", !preview && "text-sm text-muted")}>
        {preview ? <iframe title="Certificate preview" src={preview} className="h-[28rem] w-full rounded-lg" /> : "Press Preview to see a sample certificate."}
      </Card>
    </div>
  );
}
