import { useEffect } from "react";
import { create } from "zustand";

import { useMe } from "@/lib/useMe";

export type TourName = "app" | "lab" | "cockpit" | "admin";

/** Each step points at an element (CSS selector); steps whose element isn't on screen are skipped. */
export const STEPS: Record<TourName, { sel?: string; key: string }[]> = {
  app: [
    { key: "welcome" }, { sel: "aside [data-tour=section-home]", key: "home" }, { sel: "aside [data-tour=section-learn]", key: "learn" },
    { sel: "aside [data-tour=section-practice]", key: "practice" }, { sel: "aside [data-tour=section-progress]", key: "progress" },
    { sel: "aside [data-tour=you-menu]", key: "you" },
  ],
  lab: [{ key: "labWelcome" }, { sel: "[data-tour=lab-new]", key: "labNew" }, { sel: "[data-tour=lab-templates]", key: "labTemplates" },
        { sel: "[data-tour=lab-import]", key: "labImport" }, { sel: "[data-tour=lab-presets]", key: "labPresets" }],
  cockpit: [{ key: "cockpitWelcome" }, { sel: "[data-tour=setup]", key: "cockpitSetup" }, { sel: "[role=tablist]", key: "cockpitTabs" },
            { sel: "[data-tour-tab=assignments]", key: "cockpitAssign" }, { sel: "[data-tour-tab=surveys]", key: "cockpitSurveys" }, { sel: "[data-tour-tab=settings]", key: "cockpitSettings" }],
  admin: [{ key: "adminWelcome" }, { sel: 'a[href="/admin/providers"]', key: "adminProviders" }, { sel: 'a[href="/admin/payments"]', key: "adminPayments" },
          { sel: 'a[href="/admin/codes"]', key: "adminCodes" }, { sel: 'a[href="/admin/support"]', key: "adminSupport" }, { sel: 'a[href="/admin/site"]', key: "adminSite" }],
};

export const useTour = create<{ name: TourName | null; step: number; set: (n: TourName | null, s?: number) => void }>((set) => ({
  name: null, step: 0, set: (name, step = 0) => set({ name, step }),
}));

export const startTour = (name: TourName) => useTour.getState().set(name, 0);

/** Starts `name` once per account (first visit), unless already done/skipped. */
export function useAutoTour(name: TourName, when = true) {
  const { data: me } = useMe();
  useEffect(() => {
    if (!me || !when || useTour.getState().name) return;
    const done = me.preferences.learning.tours_done ?? [];
    if (done.includes(name)) return;
    const timer = setTimeout(() => startTour(name), 1200);
    return () => clearTimeout(timer);
  }, [me, name, when]);
}

