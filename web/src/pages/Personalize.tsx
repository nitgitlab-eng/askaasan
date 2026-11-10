import { CompanionPicker } from "@/components/CompanionPicker";
import { LanguageSelect } from "@/components/LanguageSelect";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Card, Segmented, Toggle } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { DeepPartial, Preferences } from "@/lib/types";
import { useGame } from "@/lib/game";
import { useMe, useUpdatePreferences, useUpdateProfile } from "@/lib/useMe";
import { Link } from "react-router-dom";
import { effectiveColor, swatchesFor } from "@/mascot/companions";
import { Kili } from "@/mascot/Kili";
import { sfx } from "@/mascot/sfx";
import { mascot, type MascotMood } from "@/mascot/store";

const COLORS = ["#22c55e", "#0ea5e9", "#a855f7", "#f43f5e", "#f59e0b", "#14b8a6", "#8b9bb4", "#2563eb"];
const ACCENTS = ["#f97316", "#e11d48", "#7c3aed", "#0891b2", "#16a34a", "#ca8a04"];
const MOODS: MascotMood[] = ["cheer", "hmm", "thinking", "talking", "sleepy", "fire", "celebrate", "wave"];

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card className="space-y-4">
      <h2 className="font-display text-xl font-bold">{title}</h2>
      {children}
    </Card>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <p className="text-sm font-medium text-muted">{label}</p>
      {children}
    </div>
  );
}

export default function PersonalizePage() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const update = useUpdatePreferences();
  const updateProfile = useUpdateProfile();
  const [previewMood, setPreviewMood] = useState<MascotMood>("idle");
  const { data: game } = useGame();
  const owned = new Set(["none", ...(game?.owned_items ?? [])]);
  if (!me) return null;
  const p = me.preferences;
  const o = (key: string) => t(`personalize.opts.${key}`, { returnObjects: true }) as Record<string, string>;

  const save = (patch: DeepPartial<Preferences>) => {
    update.mutate(patch);
    sfx("pop");
  };
  const toggleAccessory = (a: string) =>
    save({ mascot: { accessories: p.mascot.accessories.includes(a) ? p.mascot.accessories.filter((x) => x !== a) : [...p.mascot.accessories, a] } });

  const tryMood = (m: MascotMood) => {
    setPreviewMood(m);
    mascot.react(m, 2500);
    setTimeout(() => setPreviewMood("idle"), 2500);
  };

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <header className="mb-6">
        <h1 className="font-display text-3xl font-extrabold">{t("personalize.title")}</h1>
        <p className="text-muted">{t("personalize.sub")}</p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        {/* Live preview */}
        <div className="lg:sticky lg:top-6 lg:self-start">
          <Card className="flex flex-col items-center gap-3 text-center">
            <p className="text-sm font-medium text-muted">{t("personalize.preview")}</p>
            <div className="flex h-56 items-end justify-center">
              <Kili character={p.mascot.character} mood={previewMood} color={p.mascot.color} accessories={p.mascot.accessories} outfit={p.mascot.outfit} size={200} />
            </div>
            <p className="font-display text-2xl font-bold">{p.mascot.name}</p>
            <p className="text-sm text-muted">{t("personalize.tryMoods")}</p>
            <div className="flex flex-wrap justify-center gap-1.5">
              {MOODS.map((m) => (
                <button key={m} onClick={() => tryMood(m)} className="rounded-full border border-line px-2.5 py-1 text-xs hover:border-accent">
                  {o("moods")[m]}
                </button>
              ))}
            </div>
          </Card>
        </div>

        <div className="space-y-6">
          <Section title={t("personalize.mascot")}>
            <Row label={t("personalize.companion")}>
              <CompanionPicker prefs={p.mascot} onPick={(patch) => save({ mascot: patch })} />
            </Row>
            <Row label={t("personalize.mascotName")}>
              <input
                key={p.mascot.name}
                defaultValue={p.mascot.name}
                maxLength={24}
                onBlur={(e) => e.target.value.trim() && e.target.value !== p.mascot.name && save({ mascot: { name: e.target.value.trim() } })}
                className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2 outline-none focus:border-accent"
                aria-label={t("personalize.mascotName")}
              />
            </Row>
            <Row label={t("personalize.color")}>
              <div className="flex flex-wrap gap-2">
                {swatchesFor(p.mascot.character, COLORS).map((c) => {
                  const on = effectiveColor(p.mascot.character, p.mascot.color) === c;
                  return (
                    <button
                      key={c}
                      onClick={() => save({ mascot: { color: c } })}
                      className={cn("h-9 w-9 rounded-full border-4 transition", on ? "scale-110 border-ink" : "border-transparent")}
                      style={{ background: c }}
                      aria-label={c}
                      aria-pressed={on}
                    />
                  );
                })}
              </div>
            </Row>
            <Row label={t("personalize.outfit")}>
              <Segmented label={t("personalize.outfit")} value={p.mascot.outfit} onChange={(v) => save({ mascot: { outfit: v } })} options={Object.entries(o("outfit")).filter(([value]) => owned.has(value)).map(([value, label]) => ({ value, label }))} />
              <Link to="/shop" className="text-sm font-semibold text-accent">🛍️ {t("shop.more")}</Link>
            </Row>
            <Row label={t("personalize.accessories")}>
              <div className="flex flex-wrap gap-2">
                {Object.entries(o("accessories")).filter(([a]) => owned.has(a)).map(([a, label]) => (
                  <button
                    key={a}
                    onClick={() => toggleAccessory(a)}
                    aria-pressed={p.mascot.accessories.includes(a)}
                    className={cn("rounded-full border-2 px-3 py-1.5 text-sm", p.mascot.accessories.includes(a) ? "border-accent bg-accent/15" : "border-line")}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </Row>
            <Row label={t("personalize.position")}>
              <Segmented label={t("personalize.position")} value={p.mascot.position} onChange={(v) => save({ mascot: { position: v } })} options={(["bottom-right", "bottom-left"] as const).map((value) => ({ value, label: o("position")[value] }))} />
            </Row>
            <Row label={t("personalize.chattiness")}>
              <input type="range" min={0} max={3} value={p.mascot.chattiness} onChange={(e) => save({ mascot: { chattiness: Number(e.target.value) } })} className="w-full accent-[var(--accent)]" aria-label={t("personalize.chattiness")} />
            </Row>
            <Toggle label={t("personalize.show")} checked={p.mascot.enabled} onChange={(v) => save({ mascot: { enabled: v } })} />
          </Section>

          <Section title={t("personalize.mentor")}>
            <Row label={t("personalize.personality")}>
              <Segmented label={t("personalize.personality")} value={p.mentor.personality} onChange={(v) => save({ mentor: { personality: v } })} options={Object.entries(o("personality")).map(([value, label]) => ({ value: value as Preferences["mentor"]["personality"], label }))} />
            </Row>
            <Row label={t("personalize.depth")}>
              <Segmented label={t("personalize.depth")} value={p.mentor.depth} onChange={(v) => save({ mentor: { depth: v } })} options={Object.entries(o("depth")).map(([value, label]) => ({ value: value as "simple" | "detailed", label }))} />
            </Row>
            <Row label={t("personalize.replyLanguage")}>
              <Segmented label={t("personalize.replyLanguage")} value={p.mentor.reply_language} onChange={(v) => save({ mentor: { reply_language: v } })} options={Object.entries(o("replyLanguage")).map(([value, label]) => ({ value: value as Preferences["mentor"]["reply_language"], label }))} />
              <p className="text-xs text-muted">{t("personalize.replyLanguageHint")}</p>
            </Row>
            <Row label={t("personalize.examples")}>
              <Segmented label={t("personalize.examples")} value={p.mentor.example_style} onChange={(v) => save({ mentor: { example_style: v } })} options={Object.entries(o("examples")).map(([value, label]) => ({ value: value as Preferences["mentor"]["example_style"], label }))} />
            </Row>
          </Section>

          <Section title={t("personalize.look")}>
            <Row label={t("personalize.language")}>
              <LanguageSelect value={me.profile.language} onChange={(v) => updateProfile.mutate({ language: v })} />
            </Row>
            <Row label={t("personalize.theme")}>
              <Segmented label={t("personalize.theme")} value={p.appearance.theme} onChange={(v) => save({ appearance: { theme: v } })} options={Object.entries(o("theme")).map(([value, label]) => ({ value: value as Preferences["appearance"]["theme"], label }))} />
            </Row>
            <Row label={t("personalize.accent")}>
              <div className="flex gap-2">
                {ACCENTS.map((c) => (
                  <button key={c} onClick={() => save({ appearance: { accent: c } })} className={cn("h-9 w-9 rounded-xl border-4", p.appearance.accent === c ? "border-ink" : "border-transparent")} style={{ background: c }} aria-label={c} aria-pressed={p.appearance.accent === c} />
                ))}
              </div>
            </Row>
            <Row label={t("personalize.font")}>
              <Segmented label={t("personalize.font")} value={p.appearance.font} onChange={(v) => save({ appearance: { font: v } })} options={Object.entries(o("font")).map(([value, label]) => ({ value: value as Preferences["appearance"]["font"], label }))} />
            </Row>
            <Row label={`${t("personalize.fontSize")} · ${Math.round(p.appearance.font_scale * 100)}%`}>
              <input type="range" min={0.8} max={1.6} step={0.05} value={p.appearance.font_scale} onChange={(e) => save({ appearance: { font_scale: Number(e.target.value) } })} className="w-full accent-[var(--accent)]" aria-label={t("personalize.fontSize")} />
            </Row>
            <Toggle label={t("personalize.reducedMotion")} checked={p.appearance.reduced_motion} onChange={(v) => save({ appearance: { reduced_motion: v } })} />
            <Toggle label={t("personalize.sounds")} checked={p.appearance.sound_effects} onChange={(v) => save({ appearance: { sound_effects: v } })} />
          </Section>

          <Section title={t("personalize.learning")}>
            <Toggle label={t("paths.adaptive")} checked={p.learning.adaptive ?? true} onChange={(v) => save({ learning: { adaptive: v } })} />
            <p className="-mt-2 text-xs text-muted">{t("paths.adaptiveHint")}</p>
            <Row label={`${t("personalize.dailyGoal")} · ${p.learning.daily_goal_minutes}`}>
              <input type="range" min={5} max={120} step={5} value={p.learning.daily_goal_minutes} onChange={(e) => save({ learning: { daily_goal_minutes: Number(e.target.value) } })} className="w-full accent-[var(--accent)]" aria-label={t("personalize.dailyGoal")} />
            </Row>
            <Row label={t("personalize.pace")}>
              <Segmented label={t("personalize.pace")} value={p.learning.pace} onChange={(v) => save({ learning: { pace: v } })} options={Object.entries(o("pace")).map(([value, label]) => ({ value: value as Preferences["learning"]["pace"], label }))} />
            </Row>
            <Row label={t("personalize.difficulty")}>
              <Segmented label={t("personalize.difficulty")} value={p.learning.difficulty} onChange={(v) => save({ learning: { difficulty: v } })} options={Object.entries(o("difficulty")).map(([value, label]) => ({ value: value as Preferences["learning"]["difficulty"], label }))} />
            </Row>
            <Row label={t("courseMap.view")}>
              <Segmented label={t("courseMap.view")} value={p.learning.course_view ?? "map"} onChange={(v) => save({ learning: { course_view: v } })}
                options={(["map", "path"] as const).map((value) => ({ value, label: t(`courseMap.views.${value}`) }))} />
            </Row>
          </Section>

          <Section title={t("lj.redo.title")}>
            <p className="text-sm text-muted">{t("lj.redo.sub")}</p>
            <Link to="/onboarding?redo=1" className="inline-flex items-center gap-2 rounded-xl border-2 border-line px-4 py-2 font-semibold hover:border-accent">
              🔁 {t("lj.redo.button")}
            </Link>
          </Section>
        </div>
      </div>
    </div>
  );
}
