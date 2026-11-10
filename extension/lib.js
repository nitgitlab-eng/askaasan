/* Shared by the popup and the background service worker. No remote code, no page access. */
"use strict";

const AASAN = (() => {
  const DEFAULT_SERVER = "https://askaasan.com"; // the live site; developers point it at http://localhost:5173 in the popup
  const TASKS_TTL_MS = 10 * 60 * 1000;

  /** Only https:// origins, or http on localhost / 127.0.0.1 for development. Returns the origin or "". */
  function normalizeServer(input) {
    let u;
    try { u = new URL(String(input || "").trim()); } catch { return ""; }
    const local = u.hostname === "localhost" || u.hostname === "127.0.0.1";
    if (u.protocol !== "https:" && !(u.protocol === "http:" && local)) return "";
    if (u.username || u.password) return "";
    return u.origin;
  }

  async function getState() {
    const s = await chrome.storage.local.get(["server", "token", "displayName", "tasks", "tasksAt"]);
    return { server: normalizeServer(s.server) || DEFAULT_SERVER, token: s.token || "", displayName: s.displayName || "",
             tasks: Array.isArray(s.tasks) ? s.tasks : [], tasksAt: s.tasksAt || 0 };
  }

  class ApiError extends Error {
    constructor(status, data, retryAfter = 0) {
      super((data && data.code) || `HTTP ${status}`); this.status = status; this.data = data || {}; this.retryAfter = retryAfter;
    }
  }

  /** Seconds from a Retry-After header (delta-seconds or an HTTP date); 0 when absent or unreadable. */
  function retryAfterSeconds(value, now = Date.now()) {
    if (!value) return 0;
    const n = Number(value);
    if (Number.isFinite(n)) return Math.max(0, Math.ceil(n));
    const at = Date.parse(value);
    return Number.isFinite(at) ? Math.max(0, Math.ceil((at - now) / 1000)) : 0;
  }

  /** The server limits pairing attempts (429 pairing_busy): say how long to wait instead of a generic error. */
  function pairingBusyText(e) {
    if (!e || e.status !== 429 || !e.data || e.data.code !== "pairing_busy") return "";
    const n = e.retryAfter || 0;
    return n > 0 ? `Too many pairing attempts right now — try again in ${n} second${n === 1 ? "" : "s"}.`
                 : "Too many pairing attempts right now — try again in a minute.";
  }

  async function call(path, { method = "GET", body, token, server } = {}) {
    const st = await getState();
    const headers = { Accept: "application/json" };
    const tok = token === undefined ? st.token : token;
    if (tok) headers.Authorization = `AasanExt ${tok}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let res;
    try {
      res = await fetch(`${server || st.server}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body),
                                                          credentials: "omit", cache: "no-store" });
    } catch {
      throw new ApiError(0, { code: "network" });
    }
    let data = null;
    try { data = res.status === 204 ? null : await res.json(); } catch { data = null; }
    if (res.status === 401 && tok) await forgetToken(); // revoked from the web app (or expired) → pair again
    if (!res.ok) throw new ApiError(res.status, data, retryAfterSeconds(res.headers && res.headers.get && res.headers.get("Retry-After")));
    return data;
  }

  /** Stop live observation and give back the task's site permissions (never the Aasan server's own). */
  async function stopWatching() {
    const { watch, server } = await chrome.storage.local.get(["watch", "server"]);
    await chrome.storage.local.remove("watch");
    const own = normalizeServer(server) || DEFAULT_SERVER;
    const origins = (watch && Array.isArray(watch.origins) ? watch.origins : []).filter((o) => typeof o === "string" && !o.startsWith(`${own}/`));
    if (!origins.length) return;
    try { await chrome.permissions.remove({ origins }); } catch { /* already gone */ }
  }

  async function forgetToken() {
    await stopWatching();
    await chrome.storage.local.remove(["token", "displayName", "tasks", "tasksAt", "watch"]);
    try { await chrome.action.setBadgeText({ text: "" }); } catch { /* ignore */ }
  }

  async function refreshTasks() {
    const data = await call("/api/ext/tasks/");
    const tasks = Array.isArray(data && data.tasks) ? data.tasks : [];
    await chrome.storage.local.set({ tasks, tasksAt: Date.now() });
    return tasks;
  }

  function hostMatches(host, pattern) {
    host = String(host || "").toLowerCase();
    pattern = String(pattern || "").toLowerCase();
    if (!host || !pattern) return false;
    if (pattern.startsWith("*.")) return host === pattern.slice(2) || host.endsWith(pattern.slice(1));
    return host === pattern;
  }

  function globToRegExp(glob) {
    const esc = String(glob).replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".");
    return new RegExp(`^${esc}$`);
  }

  /** Does this page look like the place for the task? Strict rules first; else the task link's host (or its subdomains). */
  function taskMatchesUrl(task, url) {
    let u;
    try { u = new URL(url); } catch { return false; }
    if (u.protocol !== "https:" && u.protocol !== "http:") return false;
    if (task.target_host || task.url_pattern) {
      if (task.target_host && !hostMatches(u.hostname, task.target_host)) return false;
      if (task.url_pattern) { try { if (!globToRegExp(task.url_pattern).test(u.href)) return false; } catch { return false; } }
      return true;
    }
    return !!task.hint_host && (hostMatches(u.hostname, task.hint_host) || hostMatches(u.hostname, `*.${task.hint_host}`));
  }

  const MAX_URL = 2048; // the server refuses longer page addresses (api/apps/extension/api.py SubmitIn.url)

  /** The page address to send: as is when it fits, else without its query and fragment (often a huge tracking or
      state blob), else "" — the caller then explains that this page's address is too long. */
  function submitUrl(url) {
    url = String(url || "");
    if (url.length <= MAX_URL) return url;
    let u;
    try { u = new URL(url); } catch { return ""; }
    const short = `${u.origin}${u.pathname}`;
    return short.length <= MAX_URL ? short : "";
  }

  const MAX_DATA_URL = 2_600_000; // server accepts ~2 MB images (base64 ≈ 4/3 of that)

  /** JPEG data URL of a tab capture, shrunk until it fits the server's limit (extension pages only: needs FileReader). */
  async function shrink(dataUrl) {
    if (dataUrl.length <= MAX_DATA_URL) return dataUrl;
    const bmp = await createImageBitmap(await (await fetch(dataUrl)).blob());
    let scale = Math.min(1, 1600 / bmp.width);
    for (let quality = 0.7; ; quality -= 0.15, scale *= 0.8) {
      const w = Math.max(1, Math.round(bmp.width * scale)), h = Math.max(1, Math.round(bmp.height * scale));
      const canvas = new OffscreenCanvas(w, h);
      canvas.getContext("2d").drawImage(bmp, 0, 0, w, h);
      const blob = await canvas.convertToBlob({ type: "image/jpeg", quality: Math.max(0.35, quality) });
      const out = await new Promise((resolve, reject) => {
        const r = new FileReader();
        r.onload = () => resolve(r.result);
        r.onerror = reject;
        r.readAsDataURL(blob);
      });
      if (out.length <= MAX_DATA_URL || w < 400) return out;
    }
  }

  return { DEFAULT_SERVER, TASKS_TTL_MS, MAX_URL, normalizeServer, getState, call, ApiError, forgetToken, stopWatching, refreshTasks,
           taskMatchesUrl, submitUrl, shrink, retryAfterSeconds, pairingBusyText };
})();

if (typeof self !== "undefined") self.AASAN = AASAN;
if (typeof module !== "undefined" && module.exports) module.exports = AASAN;
