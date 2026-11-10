import { create } from "zustand";

/** The app's own confirm / prompt / alert: styled, translatable and accessible, unlike window.confirm(). */
export type Request = { id?: number } & (
  | { kind: "confirm"; message: string; danger?: boolean; ok?: string; resolve: (v: boolean) => void }
  | { kind: "prompt"; message: string; defaultValue?: string; ok?: string; allowEmpty?: boolean; resolve: (v: string | null) => void }
  | { kind: "alert"; message: string; resolve: () => void }
);

export const useDialog = create<{ queue: Request[] }>(() => ({ queue: [] }));
let seq = 0;
const push = (r: Request) => useDialog.setState((s) => ({ queue: [...s.queue, { ...r, id: ++seq }] }));
export const pop = () => useDialog.setState((s) => ({ queue: s.queue.slice(1) }));

/** Resolves true on OK, false on Cancel / Escape / backdrop. */
export const confirmDialog = (message: string, opts: { danger?: boolean; ok?: string } = {}) =>
  new Promise<boolean>((resolve) => push({ kind: "confirm", message, ...opts, resolve }));

/** Resolves the typed text (trimmed), or null when cancelled. */
export const promptDialog = (message: string, opts: { defaultValue?: string; ok?: string; allowEmpty?: boolean } = {}) =>
  new Promise<string | null>((resolve) => push({ kind: "prompt", message, ...opts, resolve }));

export const alertDialog = (message: string) => new Promise<void>((resolve) => push({ kind: "alert", message, resolve }));
