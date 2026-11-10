import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * The short-lived access token lives in memory only. The 30-day refresh token is an HttpOnly cookie the
 * page can't read (set by the API), so an injected script can't steal a long-lived session.
 * Only a "was signed in" hint is persisted, to know whether to try a silent refresh on page load.
 */
interface AuthState {
  access: string | null;
  signedIn: boolean;
  /** Pre-cookie browsers still hold their refresh token here; it's exchanged once for a cookie, then dropped. */
  legacyRefresh: string | null;
  ready: boolean;
  setAccess: (access: string) => void;
  clear: () => void;
  markReady: () => void;
}

export const useAuth = create<AuthState>()(
  persist(
    (set) => ({
      access: null,
      signedIn: false,
      legacyRefresh: null,
      ready: false,
      setAccess: (access) => set({ access, signedIn: true, legacyRefresh: null }),
      clear: () => set({ access: null, signedIn: false, legacyRefresh: null }),
      markReady: () => set({ ready: true }),
    }),
    {
      name: "aasan-auth",
      version: 1,
      partialize: (s) => ({ signedIn: s.signedIn, legacyRefresh: s.legacyRefresh }),
      migrate: (old) => {
        const o = (old ?? {}) as { access?: string | null; refresh?: string | null };
        return { signedIn: !!(o.refresh || o.access), legacyRefresh: o.refresh ?? null };
      },
    },
  ),
);
