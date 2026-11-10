/* Live observation of multi-step browser tasks — pure helpers shared by the background worker, the side panel and the
   popup (and node unit tests). Mirrors api/apps/extension/steps.py: keep the matching rules in sync.
   A step: {id, label, url_pattern: "https://host/path-glob" ("*." host prefix allowed, but never over a public suffix such
   as *.co.in or *.github.io; "*" is the only wildcard and only in the path; no query or fragment), text: "" | text the
   page must show}. Evidence carries scheme://host/path only. */
"use strict";

const AASAN_STEPS = (() => {
  const HOST_RE = /^(\*\.)?([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/;
  const PATTERN_RE = /^https:\/\/([^/?#\\]+)(\/[^?#\\]*)?$/;
  const BAD_URL_CHARS = /[\\\s\x00-\x1f\x7f]/;
  const MAX_TITLE = 120;
  // Keep identical to public_suffixes.json (a node test checks it; the API ships the same file).
  const PUBLIC_SUFFIXES = new Set([
    "000webhostapp.com", "ac.in", "ac.uk", "amazonaws.com", "appspot.com", "azurestaticapps.net", "azurewebsites.net", "bitbucket.io",
    "blogspot.com", "carrd.co", "cloudfront.net", "co.ae", "co.id", "co.in", "co.jp", "co.ke",
    "co.kr", "co.nz", "co.uk", "co.za", "com.ar", "com.au", "com.bd", "com.br",
    "com.cn", "com.eg", "com.hk", "com.lk", "com.mx", "com.my", "com.ng", "com.np",
    "com.ph", "com.pk", "com.sa", "com.sg", "com.tr", "com.tw", "edu.au", "edu.in",
    "edu.sg", "firebaseapp.com", "firm.in", "fly.dev", "gen.in", "gitbook.io", "github.io", "gitlab.io",
    "glitch.me", "gov.au", "gov.in", "gov.sg", "gov.uk", "herokuapp.com", "ind.in", "ltd.uk",
    "me.uk", "mil.in", "myshopify.com", "neocities.org", "net.au", "net.in", "netlify.app", "ngrok-free.app",
    "ngrok.io", "nic.in", "notion.site", "onrender.com", "org.au", "org.in", "org.nz", "org.uk",
    "org.za", "pages.dev", "plc.uk", "r2.dev", "readthedocs.io", "repl.co", "replit.app", "replit.dev",
    "res.in", "s3.amazonaws.com", "surge.sh", "translate.goog", "trycloudflare.com", "vercel.app", "web.app", "webflow.io",
    "weebly.com", "wixsite.com", "wordpress.com", "workers.dev",
  ]);

  function isPublicSuffix(domain) {
    domain = String(domain || "").toLowerCase().replace(/^\.+|\.+$/g, "");
    return !domain.includes(".") || PUBLIC_SUFFIXES.has(domain);
  }

  /** "https://*.google.com/sheets/*" → ["*.google.com", "/sheets/*"]; null if not a valid step pattern. */
  function splitPattern(pattern) {
    const m = PATTERN_RE.exec(String(pattern || ""));
    if (!m) return null;
    const host = m[1].toLowerCase();
    const rest = m[2] || "/*";
    if (!HOST_RE.test(host) || host.slice(2).includes("*")) return null;
    if (host.startsWith("*.") && isPublicSuffix(host.slice(2))) return null; // would cover everybody's sites
    return [host, rest];
  }

  function hostMatches(host, pattern) {
    host = String(host || "").toLowerCase().replace(/\.$/, "");
    pattern = String(pattern || "").toLowerCase();
    if (!host || !pattern) return false;
    if (pattern.startsWith("*.")) return host === pattern.slice(2) || host.endsWith(pattern.slice(1));
    return host === pattern;
  }

  function globMatch(glob, s) {
    const esc = glob.split("*").map((p) => p.replace(/[.+?^${}()|[\]\\]/g, "\\$&")).join(".*");
    return new RegExp(`^${esc}$`, "s").test(s);
  }

  /** Refuse anything parsers could read differently (backslashes, whitespace, control characters). */
  function parseUrl(url) {
    const raw = String(url || "");
    if (!raw || BAD_URL_CHARS.test(raw)) return null;
    try { return new URL(raw); } catch { return null; }
  }

  /** scheme://host/path only — no query, fragment, credentials or port leave the browser as evidence. */
  function stripUrl(url) {
    const u = parseUrl(url);
    return u ? `${u.protocol}//${u.hostname}${u.pathname || "/"}` : "";
  }

  /** https only, no credentials, default port; the host must match the host part and the path the glob. */
  function urlMatches(url, pattern) {
    const parts = splitPattern(pattern);
    const u = parseUrl(url);
    if (!parts || !u || u.protocol !== "https:" || u.username || u.password || u.port) return false;
    return hostMatches(u.hostname, parts[0]) && globMatch(parts[1], u.pathname || "/");
  }

  function hostsOf(steps) {
    const out = [];
    for (const s of steps || []) {
      const p = splitPattern(s && s.url_pattern);
      if (p && !out.includes(p[0])) out.push(p[0]);
    }
    return out;
  }

  /** Chrome match patterns for exactly these hosts (used for chrome.permissions.request — never <all_urls>). */
  function originsOf(steps) {
    return hostsOf(steps).map((h) => `https://${h}/*`);
  }

  /** Is this tab one we may look at for the active watch? */
  function hostAllowed(url, hosts) {
    const u = parseUrl(url);
    return !!u && u.protocol === "https:" && (hosts || []).some((h) => hostMatches(u.hostname, h));
  }

  function newWatch(task) {
    const steps = (task && task.observe && Array.isArray(task.observe.steps) ? task.observe.steps : [])
      .filter((s) => s && typeof s.id === "string" && splitPattern(s.url_pattern))
      .map((s) => ({ id: s.id, label: String(s.label || "").slice(0, 120), url_pattern: s.url_pattern, text: String(s.text || "").slice(0, 80) }));
    if (!steps.length) return null;
    return { taskId: task.id, title: String(task.title || "").slice(0, 160), steps, hosts: hostsOf(steps), origins: originsOf(steps),
             observed: [], waiting: "", startedAt: Date.now() };
  }

  const nextStep = (w) => (w && w.steps[w.observed.length]) || null;
  const isDone = (w) => !!w && w.steps.length > 0 && w.observed.length >= w.steps.length;

  /**
   * Tick as many steps (in order) as this page satisfies. `hasText(text)` resolves to a boolean (the page check runs
   * in the tab and returns true/false only). Returns {watch, changed}. Never mutates the input.
   */
  async function advance(watch, tab, hasText) {
    let w = { ...watch, observed: [...watch.observed] };
    let changed = false;
    if (!tab || !hostAllowed(tab.url, w.hosts)) return { watch: w, changed };
    for (let step = nextStep(w); step && urlMatches(tab.url, step.url_pattern); step = nextStep(w)) {
      if (step.text) {
        let ok = false;
        try { ok = (await hasText(step.text)) === true; } catch { ok = false; }
        if (!ok) {
          if (w.waiting !== step.id) { w = { ...w, waiting: step.id }; changed = true; }
          return { watch: w, changed };
        }
      }
      w.observed.push({ step: step.id, url: stripUrl(tab.url).slice(0, 2048), title: String(tab.title || "").slice(0, MAX_TITLE),
                        text_found: step.text ? true : null, at: Date.now() });
      w.waiting = "";
      changed = true;
    }
    return { watch: w, changed };
  }

  /** What the submit endpoint receives as evidence (the server re-checks every URL against the patterns). */
  function evidence(w) {
    return (w ? w.observed : []).map((o) => ({ step: o.step, url: stripUrl(o.url), title: String(o.title || "").slice(0, MAX_TITLE),
                                               text_found: o.text_found }));
  }

  return { PUBLIC_SUFFIXES, isPublicSuffix, splitPattern, hostMatches, urlMatches, stripUrl, hostsOf, originsOf, hostAllowed, newWatch,
           nextStep, isDone, advance, evidence };
})();

if (typeof self !== "undefined") self.AASAN_STEPS = AASAN_STEPS;
if (typeof module !== "undefined" && module.exports) module.exports = AASAN_STEPS;
