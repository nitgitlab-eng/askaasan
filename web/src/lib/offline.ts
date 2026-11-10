import { useEffect, useState, useSyncExternalStore } from "react";

import { SESSION_ENDED, api } from "./api";
import { clearGuestTokens } from "./guests";
import type { CourseDetail, Lesson } from "./learn";

/**
 * B2 offline-first lessons. The service worker keeps a network-first copy of lesson/course API reads (per browser,
 * cleared on logout). "Save for offline" pre-reads every ready lesson so it's in that cache. Answers given while
 * offline are queued here and sent (and graded) automatically when the connection returns.
 */
const QUEUE = "aasan-offline-queue";
const SAVED = "aasan-offline-courses";

function read<T>(key: string, fallback: T): T {
  try {
    return JSON.parse(localStorage.getItem(key) ?? "") as T;
  } catch {
    return fallback;
  }
}
function write(key: string, v: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(v));
  } catch {
    /* storage full / private mode: offline features degrade gracefully */
  }
}

/** A POST made while offline, replayed in order later. `key` dedupes (latest answer per activity wins). */
export interface Queued { key: string; url: string; json: unknown; at: number }

export const offlineQueue = {
  list: (): Queued[] => read<Queued[]>(QUEUE, []),
  add(q: Omit<Queued, "at">) {
    const rest = this.list().filter((x) => x.key !== q.key);
    write(QUEUE, [...rest, { ...q, at: Date.now() }].slice(-300));
    window.dispatchEvent(new Event("aasan:queue"));
  },
  has: (key: string) => read<Queued[]>(QUEUE, []).some((x) => x.key === key),
  clear: () => write(QUEUE, []),
};

/** True when a request failed because there's no connection (not because the server said no). */
export const isOfflineError = (e: unknown) => !navigator.onLine || (e instanceof TypeError && /fetch|network/i.test(e.message));

let flushing = false;
/** Send queued answers; keeps the ones that still fail (except permanent 4xx). Returns how many were sent. */
export async function flushQueue(): Promise<number> {
  if (flushing || !navigator.onLine) return 0;
  flushing = true;
  let sent = 0;
  try {
    const keep: Queued[] = [];
    for (const q of offlineQueue.list()) {
      try {
        await api(q.url, { method: "POST", json: q.json });
        sent++;
      } catch (e) {
        const status = (e as { status?: number }).status;
        if (!status || status >= 500 || status === 429) keep.push(q); // network/server trouble → try again later
      }
    }
    write(QUEUE, keep);
    window.dispatchEvent(new Event("aasan:queue"));
  } finally {
    flushing = false;
  }
  return sent;
}

export function useOnline(): boolean {
  return useSyncExternalStore(
    (cb) => { window.addEventListener("online", cb); window.addEventListener("offline", cb); return () => { window.removeEventListener("online", cb); window.removeEventListener("offline", cb); }; },
    () => navigator.onLine,
    () => true,
  );
}

export function useQueuedCount(): number {
  const [n, setN] = useState(() => offlineQueue.list().length);
  useEffect(() => {
    const on = () => setN(offlineQueue.list().length);
    window.addEventListener("aasan:queue", on);
    return () => window.removeEventListener("aasan:queue", on);
  }, []);
  return n;
}

export const savedCourses = {
  list: (): Record<string, { title: string; lessons: number; at: number }> => read(SAVED, {}),
  has: (id: number) => String(id) in read<Record<string, unknown>>(SAVED, {}),
  remove(id: number) {
    const all = this.list();
    delete all[String(id)];
    write(SAVED, all);
  },
};

/** Read the course and every ready lesson once (also in the chosen reading language) so the service worker keeps them. */
export async function saveCourseOffline(c: CourseDetail, lang: string, onProgress?: (done: number, total: number) => void): Promise<number> {
  await api(`/api/learn/curriculums/${c.id}/`);
  const ids = c.sections.flatMap((s) => s.subsections.filter((b) => b.lesson_status === "ready").map((b) => b.id));
  let done = 0;
  for (const id of ids) {
    await api<Lesson>(`/api/learn/subsections/${id}/`);
    if (lang) await api<Lesson>(`/api/learn/subsections/${id}/?lang=${lang}`).catch(() => null);
    onProgress?.(++done, ids.length);
  }
  const all = savedCourses.list();
  all[String(c.id)] = { title: c.title, lessons: ids.length, at: Date.now() };
  write(SAVED, all);
  return ids.length;
}

/** On logout: forget this person's offline copies and queued answers (shared devices are common). */
export async function clearOfflineData() {
  write(SAVED, {});
  offlineQueue.clear();
  clearGuestTokens();
  try {
    if ("caches" in window) {
      await caches.delete("aasan-api-v1");
      setTimeout(() => void caches.delete("aasan-api-v1"), 3000); // a response still in flight may re-create it
    }
  } catch {
    /* ignore */
  }
}

if (typeof window !== "undefined") window.addEventListener(SESSION_ENDED, () => void clearOfflineData());
