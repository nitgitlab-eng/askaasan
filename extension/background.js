/* 1. Lights the toolbar badge when the current tab matches one of the learner's open browser tasks (tab URLs only).
   2. Live observation (only while the learner is watching a task): on tabs whose host is one of that task's step hosts
      — and only if the learner granted host permission for exactly those hosts — ticks steps as pages load. For a step
      with a text check it runs a tiny function in that tab that returns true/false; page content never leaves the tab.
   Nothing is injected into any other tab, and nothing runs when no task is being watched. */
"use strict";
importScripts("lib.js", "steps.js");

async function tasksForBadge() {
  const st = await AASAN.getState();
  if (!st.token) return [];
  if (Date.now() - st.tasksAt > AASAN.TASKS_TTL_MS) {
    try { return await AASAN.refreshTasks(); } catch { return st.tasks; }
  }
  return st.tasks;
}

async function updateBadge(tabId, url) {
  if (tabId === undefined || tabId < 0) return;
  let n = 0;
  if (url) {
    const tasks = await tasksForBadge();
    n = tasks.filter((t) => AASAN.taskMatchesUrl(t, url)).length;
  }
  try {
    await chrome.action.setBadgeBackgroundColor({ tabId, color: "#16a34a" });
    await chrome.action.setBadgeText({ tabId, text: n ? String(n) : "" });
    await chrome.action.setTitle({ tabId, title: n ? `Aasan Companion — ${n} task(s) for this site` : "Aasan Companion" });
  } catch { /* the tab may have closed */ }
}

// ── Live observation ─────────────────────────────────────────────

/** Runs inside the page. Returns ONLY a boolean — never the page text. */
function pageContains(needle) {
  try {
    const text = (document.body && document.body.innerText) || "";
    return text.toLocaleLowerCase().includes(String(needle).toLocaleLowerCase());
  } catch {
    return false;
  }
}

async function pageHasText(tabId, text) {
  const [res] = await chrome.scripting.executeScript({ target: { tabId }, func: pageContains, args: [text] });
  return !!res && res.result === true;
}

let queue = Promise.resolve(); // one observation at a time, so two quick page loads can't tick a step twice

function observe(tabId, tab) {
  queue = queue.then(() => observeNow(tabId, tab)).catch(() => {});
  return queue;
}

async function observeNow(tabId, tab) {
  const { watch } = await chrome.storage.local.get("watch");
  if (!watch || AASAN_STEPS.isDone(watch) || !tab || !tab.url) return;
  if (!AASAN_STEPS.hostAllowed(tab.url, watch.hosts)) return; // not one of this task's sites: don't look
  if (!(await chrome.permissions.contains({ origins: watch.origins }))) return;
  const res = await AASAN_STEPS.advance(watch, tab, (text) => pageHasText(tabId, text));
  if (!res.changed) return;
  const now = (await chrome.storage.local.get("watch")).watch; // the learner may have stopped watching meanwhile
  if (now && now.taskId === watch.taskId && now.startedAt === watch.startedAt) await chrome.storage.local.set({ watch: res.watch });
}

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  try {
    const tab = await chrome.tabs.get(tabId);
    await updateBadge(tabId, tab.url);
    await observe(tabId, tab);
  } catch { /* ignore */ }
});

chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if (info.url || info.status === "complete") updateBadge(tabId, tab.url).catch(() => {});
  if (info.url || info.title || info.status === "complete") void observe(tabId, tab); // observe() never rejects
});

// "Check this page now" from the side panel (e.g. after typing the text without a page load).
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id || !msg || msg.type !== "aasan-check") return false;
  (async () => {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (tab) await observe(tab.id, tab);
    sendResponse({ ok: true });
  })().catch(() => sendResponse({ ok: false }));
  return true;
});

// Task list changed (popup refreshed it, paired, or disconnected) → repaint the active tab.
chrome.storage.onChanged.addListener(async (changes, area) => {
  if (area !== "local" || !(changes.tasks || changes.token)) return;
  try {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (tab) await updateBadge(tab.id, tab.url);
  } catch { /* no window, or the tab closed meanwhile */ }
});

// The toolbar button keeps opening the popup; the side panel is opened from the popup's "Watch steps".
if (chrome.sidePanel && chrome.sidePanel.setPanelBehavior) chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: false }).catch(() => {});
