import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, KeyRound, Loader2, Mic, Play, Save, XCircle } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card, Toggle } from "@/components/ui";
import i18n from "@/i18n";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useAuth } from "@/stores/auth";
import { BCP47, BrowserRecognition, pickBrowserVoice } from "@/voice/engines";

interface ProviderSpec {
  models: string[];
  default_model: string;
  no_key?: boolean;
  voices?: { en: string[]; ta: string[] };
  /** Per-model voices when a provider's models use different speakers (e.g. Sarvam Bulbul v2 / v3 / v4-flash). */
  voices_by_model?: Record<string, { en: string[]; ta: string[] }>;
  /** Suggested [host A, host B] podcast voices per language (two clearly different speakers). */
  host_voices?: { en?: string[]; ta?: string[] };
  host_voices_by_model?: Record<string, { en?: string[]; ta?: string[] }>;
}
interface Capability {
  label: string;
  providers: Record<string, ProviderSpec>;
  default: string;
  recommended?: string;
}
interface Config {
  capability: string;
  label: string;
  provider: string;
  model: string;
  /** Narrator voice per language ("en", "ta") and the podcast hosts ("en_host_a", "ta_host_b", ...). */
  voices: Partial<Record<string, string>>;
  enabled: boolean;
  limits: Record<string, number>;
  source: "db" | "env" | "default";
  key: { needed: boolean; set: boolean; from: "admin" | "env" | null; masked: string | null; env_var: string | null };
}
interface Listing {
  catalog: Record<string, Capability>;
  configs: Config[];
}

/** Product names stay as they are in every language; the browser option is a sentence, so it lives in admin.providers.browserName. */
const PROVIDER_NAMES: Record<string, string> = {
  anthropic: "Anthropic Claude",
  openai: "OpenAI",
  gemini: "Google Gemini",
  google: "Google Cloud",
  sarvam: "Sarvam AI",
  deepgram: "Deepgram",
};
const providerName = (p: string) => (p === "browser" ? i18n.t("admin.providers.browserName") : PROVIDER_NAMES[p] ?? p);
const LIMITS = ["stt_seconds_per_day", "tts_chars_per_day", "vision_frames_per_day", "images_per_day"];
const SAMPLE = { en: "Hello! I am Aasan, your learning companion.", ta: "வணக்கம்! நான் ஆசான், உங்கள் கற்றல் துணை." };

type TestResult = { ok: boolean; detail: string; image?: string } | null;

function ProviderCard({ cfg, spec }: { cfg: Config; spec: Capability }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [draft, setDraft] = useState(cfg);
  const [keyInput, setKeyInput] = useState<string | null>(null); // null = unchanged
  const [result, setResult] = useState<TestResult>(null);
  const [testing, setTesting] = useState<string | null>(null);

  const pSpec = spec.providers[draft.provider];
  const isTts = cfg.capability === "tts" || cfg.capability === "tts_ta";
  const isVoice = cfg.capability === "stt" || isTts;
  const ttsLangs: ("en" | "ta")[] = cfg.capability === "tts_ta" ? ["ta"] : ["en", "ta"];
  const providerChanged = draft.provider !== cfg.provider;
  const dirty = providerChanged || draft.model !== cfg.model || draft.enabled !== cfg.enabled || keyInput !== null ||
    JSON.stringify(draft.voices) !== JSON.stringify(cfg.voices) || JSON.stringify(draft.limits) !== JSON.stringify(cfg.limits);
  const langName = (lang: "en" | "ta") => (lang === "ta" ? t("admin.providers.tamil") : t("admin.providers.english"));

  const save = useMutation({
    mutationFn: () =>
      api<Config>(`/api/admin/providers/${cfg.capability}/`, {
        method: "PATCH",
        json: {
          provider: draft.provider,
          model: draft.model,
          enabled: draft.enabled,
          ...(isVoice ? { limits: draft.limits } : {}),
          ...(isTts ? { voices: draft.voices } : {}),
          ...(keyInput !== null ? { api_key: keyInput } : {}),
        },
      }),
    onSuccess: (updated) => {
      setKeyInput(null);
      setResult(null);
      qc.setQueryData<Listing>(["admin-providers"], (l) => l && { ...l, configs: l.configs.map((c) => (c.capability === updated.capability ? updated : c)) });
    },
  });

  async function runTest(kind: "default" | "en" | "ta" | "mic", role: "narrator" | "host_a" | "host_b" = "narrator") {
    setTesting(role === "narrator" ? kind : `${kind}_${role}`);
    setResult(null);
    try {
      if (draft.provider === "browser") {
        setResult(await browserTest(cfg.capability, kind === "ta" ? "ta" : "en"));
        return;
      }
      if (isTts) {
        const res = await fetch(`/api/admin/providers/${cfg.capability}/test/`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${useAuth.getState().access}` },
          body: JSON.stringify({ lang: kind === "ta" ? "ta" : "en", role }),
        });
        if (!res.ok) {
          const d = await res.json();
          setResult({ ok: false, detail: `${d.code}: ${d.detail ?? ""}` });
          return;
        }
        const url = URL.createObjectURL(await res.blob());
        await new Audio(url).play();
        const lang = langName(kind === "ta" ? "ta" : "en");
        setResult({ ok: true, detail: role === "narrator" ? t("admin.providers.playing", { lang }) : t("admin.providers.playingHost", { lang, host: role === "host_a" ? "A" : "B" }) });
        return;
      }
      if (cfg.capability === "stt") {
        const blob = await recordSeconds(4);
        const form = new FormData();
        form.append("audio", blob, "test.webm");
        const res = await fetch(`/api/admin/providers/stt/test/`, { method: "POST", body: form, headers: { Authorization: `Bearer ${useAuth.getState().access}` } });
        const d = await res.json();
        setResult({ ok: !!d.ok, detail: d.ok ? t("admin.providers.heard", { text: d.detail }) : `${d.code}: ${d.detail ?? ""}` });
        return;
      }
      const d = await api<{ ok: boolean; detail: string; image?: string }>(`/api/admin/providers/${cfg.capability}/test/`, { method: "POST", json: {} });
      setResult({ ok: d.ok, detail: cfg.capability === "image" ? d.detail : t("admin.providers.replied", { text: d.detail }), image: d.image });
    } catch (e) {
      const d = e instanceof ApiError ? e.data : null;
      setResult({ ok: false, detail: d ? `${d.code}: ${d.detail ?? ""}` : (e as Error).message });
    } finally {
      setTesting(null);
    }
  }

  const voiceOptions = (lang: "en" | "ta") => (pSpec?.voices_by_model?.[draft.model] ?? pSpec?.voices)?.[lang] ?? [];
  const hostOptions = (lang: "en" | "ta") => (pSpec?.host_voices_by_model?.[draft.model] ?? pSpec?.host_voices)?.[lang] ?? [];

  return (
    <Card className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="font-display text-xl font-bold">{cfg.label}</h2>
          <p className="text-xs text-muted">{t(`admin.providers.source.${cfg.source}`)}</p>
        </div>
        <Toggle label={t("admin.providers.enabled")} checked={draft.enabled} onChange={(v) => setDraft({ ...draft, enabled: v })} />
      </header>

      <div className="grid gap-4 sm:grid-cols-2">
        <label className="space-y-1">
          <span className="text-sm font-medium">{t("admin.providers.provider")}</span>
          <select
            value={draft.provider}
            onChange={(e) => setDraft({ ...draft, provider: e.target.value, model: spec.providers[e.target.value].default_model, voices: {} })}
            className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2.5"
          >
            {Object.keys(spec.providers).map((p) => (
              <option key={p} value={p}>{providerName(p)}</option>
            ))}
          </select>
        </label>
        {pSpec && pSpec.models.length > 0 && (
          <label className="space-y-1">
            <span className="text-sm font-medium">{t("admin.providers.model")}</span>
            <input
              list={`models-${cfg.capability}`}
              value={draft.model}
              onChange={(e) => setDraft({ ...draft, model: e.target.value })}
              className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2.5"
            />
            <datalist id={`models-${cfg.capability}`}>
              {pSpec.models.map((m) => <option key={m} value={m} />)}
            </datalist>
          </label>
        )}
      </div>

      {!pSpec?.no_key && (
        <div className="space-y-1">
          <span className="flex items-center gap-2 text-sm font-medium"><KeyRound className="h-4 w-4" /> {t("admin.providers.apiKey")}</span>
          {keyInput === null && !providerChanged ? (
            <div className="flex flex-wrap items-center gap-2">
              <code className="rounded-lg bg-surface-2 px-3 py-2 text-sm">
                {cfg.key.set ? `${cfg.key.masked} (${cfg.key.from === "admin" ? t("admin.providers.keySavedHere") : t("admin.providers.keyFromEnv", { var: cfg.key.env_var })})` : t("admin.providers.notSet")}
              </code>
              <Button variant="outline" type="button" onClick={() => setKeyInput("")} className="py-1.5 text-sm">{cfg.key.set ? t("admin.providers.replaceKey") : t("admin.providers.addKey")}</Button>
              {cfg.key.from === "admin" && (
                <Button variant="ghost" type="button" className="py-1.5 text-sm text-bad" onClick={() => setKeyInput("")}>{t("admin.providers.remove")}</Button>
              )}
            </div>
          ) : (
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              placeholder={providerChanged ? t("admin.providers.pasteKeyFor", { provider: providerName(draft.provider) }) : t("admin.providers.pasteNewKey")}
              value={keyInput ?? ""}
              onChange={(e) => setKeyInput(e.target.value)}
              className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2.5 font-mono text-sm"
            />
          )}
          <p className="text-xs text-muted">{t("admin.providers.encrypted")}</p>
        </div>
      )}

      {cfg.capability === "tts" && draft.provider === "deepgram" && (
        <p className="rounded-xl bg-surface-2 px-3 py-2 text-sm text-muted" data-testid="deepgram-note">{t("admin.providers.deepgramNote")}</p>
      )}
      {spec.recommended && draft.provider !== spec.recommended && (
        <p className="text-xs text-muted">{t("admin.providers.recommended", { provider: `${providerName(spec.recommended)}${cfg.capability === "tts_ta" ? " (bulbul:v4-flash)" : " (Aura-2)"}` })}</p>
      )}
      {isTts && pSpec?.voices && !pSpec.no_key && (
        <div className="space-y-4">
          {ttsLangs.filter((lang) => (pSpec.voices?.[lang]?.length ?? 1) > 0).map((lang) => {
            const name = langName(lang);
            const field = (key: string, label: string, options: string[], placeholder: string) => (
              <label key={key} className="space-y-1">
                <span className="text-sm font-medium">{label}</span>
                <input
                  list={`voices-${cfg.capability}-${key}`}
                  value={draft.voices[key] ?? ""}
                  placeholder={placeholder}
                  onChange={(e) => setDraft({ ...draft, voices: { ...draft.voices, [key]: e.target.value } })}
                  className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2.5"
                />
                <datalist id={`voices-${cfg.capability}-${key}`}>{options.map((v) => <option key={v} value={v} />)}</datalist>
              </label>
            );
            const hosts = hostOptions(lang);
            return (
              <div key={lang} className="grid gap-4 sm:grid-cols-3">
                {field(lang, t("admin.providers.narrator", { lang: name }), voiceOptions(lang), t("admin.providers.providerDefault"))}
                {field(`${lang}_host_a`, t("admin.providers.hostA", { lang: name }), voiceOptions(lang), hosts[0] ?? t("admin.providers.suggested"))}
                {field(`${lang}_host_b`, t("admin.providers.hostB", { lang: name }), voiceOptions(lang), hosts[1] ?? t("admin.providers.suggested"))}
              </div>
            );
          })}
          <p className="text-xs text-muted">{t("admin.providers.hostsHint")}</p>
        </div>
      )}

      {(isVoice || cfg.capability === "vision" || cfg.capability === "image") && (
        <div className="grid gap-4 sm:grid-cols-2">
          {Object.entries(draft.limits).filter(([k]) => k.startsWith({ stt: "stt", tts: "tts", tts_ta: "tts", vision: "vision", image: "images" }[cfg.capability] ?? "~")).map(([k, v]) => (
            <label key={k} className="space-y-1">
              <span className="text-sm font-medium">{LIMITS.includes(k) ? t(`admin.providers.limits.${k}`) : k}</span>
              <input type="number" min={0} value={v} onChange={(e) => setDraft({ ...draft, limits: { ...draft.limits, [k]: Number(e.target.value) } })} className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2.5" />
            </label>
          ))}
        </div>
      )}

      <footer className="flex flex-wrap items-center gap-2 border-t border-line pt-4">
        <Button type="button" onClick={() => save.mutate()} disabled={!dirty} loading={save.isPending}>
          <Save className="h-4 w-4" /> {t("admin.common.save")}
        </Button>
        {isTts ? (
          <>
            {ttsLangs.map((lang) => (
              <Button key={lang} variant="outline" type="button" disabled={dirty || !!testing} onClick={() => runTest(lang)}><Play className="h-4 w-4" /> {t("admin.providers.testLang", { lang: langName(lang) })}</Button>
            ))}
            {!pSpec?.no_key && (["host_a", "host_b"] as const).map((role) => (
              <Button key={role} variant="outline" type="button" disabled={dirty || !!testing} onClick={() => runTest(ttsLangs[0], role)}>
                <Play className="h-4 w-4" /> {role === "host_a" ? t("admin.providers.testHostA") : t("admin.providers.testHostB")}
              </Button>
            ))}
          </>
        ) : cfg.capability === "stt" ? (
          <Button variant="outline" type="button" disabled={dirty || !!testing} onClick={() => runTest("mic")}>
            <Mic className="h-4 w-4" /> {testing === "mic" ? t("admin.providers.recording") : t("admin.providers.testStt")}
          </Button>
        ) : (
          <Button variant="outline" type="button" disabled={dirty || !!testing} onClick={() => runTest("default")}>{t("admin.providers.testConn")}</Button>
        )}
        {testing && testing !== "mic" && <Loader2 className="h-4 w-4 animate-spin text-muted" />}
        {dirty && <span className="text-xs text-muted">{t("admin.providers.saveFirst")}</span>}
        {save.isError && <span className="text-sm text-bad">{(save.error as ApiError).data ? JSON.stringify((save.error as ApiError).data) : t("admin.providers.saveFailed")}</span>}
      </footer>
      {result && (
        <p role="status" className={cn("flex items-start gap-2 rounded-xl px-3 py-2 text-sm", result.ok ? "bg-good/10 text-good" : "bg-bad/10 text-bad")}>
          {result.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0" />}
          <span className="break-words">{result.detail}</span>
        </p>
      )}
      {result?.image && <img src={result.image} alt={t("admin.providers.testImage")} className="h-40 w-40 rounded-xl border border-line object-cover" />}
    </Card>
  );
}

async function recordSeconds(seconds: number): Promise<Blob> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const rec = new MediaRecorder(stream);
  const chunks: Blob[] = [];
  rec.ondataavailable = (e) => chunks.push(e.data);
  rec.start();
  await new Promise((r) => setTimeout(r, seconds * 1000));
  await new Promise<void>((r) => {
    rec.onstop = () => r();
    rec.stop();
  });
  stream.getTracks().forEach((t) => t.stop());
  return new Blob(chunks, { type: rec.mimeType });
}

async function browserTest(capability: string, lang: "en" | "ta"): Promise<{ ok: boolean; detail: string }> {
  const t = (key: string, vars?: Record<string, unknown>) => i18n.t(`admin.providers.browser.${key}`, vars);
  if (capability === "tts" || capability === "tts_ta") {
    const voice = pickBrowserVoice(lang);
    const u = new SpeechSynthesisUtterance(SAMPLE[lang]);
    u.lang = BCP47[lang];
    if (voice) u.voice = voice;
    speechSynthesis.speak(u);
    return voice
      ? { ok: true, detail: t("speakingWith", { voice: voice.name }) }
      : { ok: lang === "en", detail: lang === "ta" ? t("noTamil") : t("defaultVoice") };
  }
  if (!BrowserRecognition) return { ok: false, detail: t("noRecognition") };
  return new Promise((resolve) => {
    const r = new BrowserRecognition!();
    r.lang = BCP47.en;
    r.continuous = false;
    r.interimResults = false;
    r.onresult = (e) => resolve({ ok: true, detail: i18n.t("admin.providers.heard", { text: e.results[0][0].transcript }) });
    r.onerror = (e) => resolve({ ok: false, detail: t("error", { error: e.error }) });
    r.onend = () => resolve({ ok: false, detail: t("noSpeech") });
    r.start();
  });
}

export default function AdminProviders() {
  const { t } = useTranslation();
  const { data, isLoading, error } = useQuery({ queryKey: ["admin-providers"], queryFn: () => api<Listing>("/api/admin/providers/") });
  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("admin.providers.title")}</h1>
        <p className="text-muted">{t("admin.providers.sub")}</p>
      </header>
      {isLoading && <p className="text-muted">{t("admin.common.loading")}</p>}
      {error && <p className="text-bad">{t("admin.providers.loadFailed")}</p>}
      {data?.configs.map((cfg) => (
        <ProviderCard key={`${cfg.capability}:${cfg.provider}:${cfg.model}:${cfg.key.masked ?? ""}:${cfg.enabled}`} cfg={cfg} spec={data.catalog[cfg.capability]} />
      ))}
    </div>
  );
}
