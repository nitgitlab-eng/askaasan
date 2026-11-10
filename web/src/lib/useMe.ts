import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { setLanguage, setMascotName } from "@/i18n";
import { companionName } from "@/mascot/name";
import { setSfxEnabled } from "@/mascot/sfx";
import { useAuth } from "@/stores/auth";

import { api } from "./api";
import { applyTheme } from "./theme";
import type { DeepPartial, Me, Preferences, Profile } from "./types";

export const meKey = ["me"] as const;

export function useMe() {
  const access = useAuth((s) => s.access);
  return useQuery({ queryKey: meKey, queryFn: () => api<Me>("/api/users/me/"), enabled: !!access, staleTime: 60_000 });
}

function deepMerge<T>(base: T, patch: DeepPartial<T>): T {
  const out: Record<string, unknown> = { ...(base as Record<string, unknown>) };
  for (const [k, v] of Object.entries(patch as Record<string, unknown>)) {
    const cur = out[k];
    out[k] = v && typeof v === "object" && !Array.isArray(v) && cur && typeof cur === "object" ? deepMerge(cur, v as never) : v;
  }
  return out as T;
}

/** Optimistic preferences update: UI changes instantly, server validates. */
export function useUpdatePreferences() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: DeepPartial<Preferences>) => api<Preferences>("/api/users/preferences/", { method: "PATCH", json: patch }),
    onMutate: async (patch) => {
      await qc.cancelQueries({ queryKey: meKey });
      const prev = qc.getQueryData<Me>(meKey);
      if (prev) qc.setQueryData<Me>(meKey, { ...prev, preferences: deepMerge(prev.preferences, patch) });
      return { prev };
    },
    onError: (_e, _p, ctx) => ctx?.prev && qc.setQueryData(meKey, ctx.prev),
    onSuccess: (prefs) => qc.setQueryData<Me>(meKey, (m) => (m ? { ...m, preferences: prefs } : m)),
  });
}

export function useUpdateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<Profile>) => api<Me>("/api/users/profile/", { method: "PATCH", json: patch }),
    onSuccess: (me) => qc.setQueryData(meKey, me),
  });
}

/** Push appearance prefs onto <html> so CSS tokens update live. */
export function useApplyAppearance(me: Me | undefined) {
  const a = me?.preferences.appearance;
  const lang = me?.profile.language;
  useEffect(() => {
    if (!a) return;
    const root = document.documentElement;
    const stopTheme = applyTheme(a.theme); // "system" keeps following the device until the next change/unmount
    root.dataset.font = a.font;
    root.dataset.reducedMotion = String(a.reduced_motion);
    root.style.setProperty("--accent", a.accent);
    root.style.setProperty("--scale", String(a.font_scale));
    setSfxEnabled(a.sound_effects);
    return stopTheme;
  }, [a]);
  useEffect(() => {
    if (lang) setLanguage(lang);
  }, [lang]);
  const mc = me?.preferences.mascot;
  useEffect(() => {
    if (mc) setMascotName(companionName(mc.character, mc.name, lang ?? "en"));
  }, [mc?.character, mc?.name, lang]); // eslint-disable-line react-hooks/exhaustive-deps
}
