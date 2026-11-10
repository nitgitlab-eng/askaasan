/* Aasan Companion popup. Everything from web pages (URL, title) and from the server is treated as text:
   the DOM is built with textContent only — no innerHTML, no eval, no remote scripts. */
"use strict";

const $ = (id) => document.getElementById(id);
let lastLessonPath = "";
let currentWindowId; // known before any click, so "Watch steps" can open the side panel within the user gesture
let watching = null; // the task being observed live (see steps.js / background.js)

const ERRORS = {
  network: "Can't reach Aasan. Check your internet connection and the address in Settings.",
  bad_code: "That code didn't work. Codes last 10 minutes and work once — get a new one in Aasan.",
  bad_image: "Couldn't read the screenshot of this tab. Try again.",
  bad_url: "Open the website for this task in this tab first.",
  wrong_site: "This task must be done on a different website.",
  grading_budget_exceeded: "You've reached today's limit for AI-marked answers. Try again tomorrow.",
  grading_unavailable: "Marking is busy right now. Try again in a minute.",
  not_found: "This task isn't available any more. Refresh the list.",
  permission: "Allow Aasan Companion to talk to that address to continue.",
  watch_permission: "To watch the steps, allow Aasan Companion to see this task's websites.",
  steps_incomplete: "Not every step was observed yet. Keep going.",
  steps_required: "This task needs its steps watched. Click \u201cWatch steps\u201d, do each step, then send.",
  steps_mismatch: "This task's steps changed. Stop watching and start again.",
  step_url_mismatch: "One step was on a page that doesn't match the task. Stop watching and try again.",
  step_text_missing: "A step's text wasn't found. Check the page and try again.",
  capture: "Couldn't capture this tab. Click on the page once, then try again (browser pages like settings can't be captured).",
  url_too_long: "This page's address is too long to send. Open the page again from the site's own menu, then try again.",
  bad_request: "Aasan couldn't read what was sent from this tab. Reload the page and try again.",
  not_browser_task: "This task can't be sent from the extension any more. Refresh the list.",
  server: "Aasan had a problem on its side. Try again in a minute.",
};

function showStatus(text, isError = false) {
  const el = $("status");
  el.textContent = text || "";
  el.hidden = !text;
  el.classList.toggle("error", !!isError);
}

function errorText(e) {
  const busy = AASAN.pairingBusyText(e);
  if (busy) return busy;
  const code = (e && e.data && e.data.code) || (e && e.message) || "";
  if (code === "wrong_site" && e.data.target_host) return `This task must be done on ${e.data.target_host}. Open it in this tab and try again.`;
  if (e && e.status === 401) return "This browser was disconnected from Aasan. Connect it again with a new code.";
  if (e && e.status === 429 && code !== "grading_budget_exceeded") return "Too many tries — wait a little and try again.";
  if (!ERRORS[code] && e && e.status >= 500) return ERRORS.server;
  return ERRORS[code] || "Something went wrong. Please try again.";
}

/** Last resort for anything a handler didn't catch: say so in the popup instead of an unhandled rejection. */
function safely(fn) {
  return (...args) => {
    // Called synchronously, so handlers can still use ev.preventDefault() before their first await.
    try { return Promise.resolve(fn(...args)).catch((e) => showStatus(errorText(e), true)); } catch (e) { showStatus(errorText(e), true); }
  };
}

function show(view) {
  for (const v of ["pair", "tasks", "result"]) $(`view-${v}`).hidden = v !== view;
}

function el(tag, props = {}, children = []) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "text") n.textContent = v;
    else if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const c of children) if (c) n.append(c);
  return n;
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function openAasan(path) {
  const { server } = await AASAN.getState();
  if (typeof path === "string" && path.startsWith("/")) await chrome.tabs.create({ url: server + path });
}

async function ensurePermission(origin) {
  const want = { origins: [`${origin}/*`] };
  if (await chrome.permissions.contains(want)) return true;
  try { return await chrome.permissions.request(want); } catch { return false; }
}

// ── Render ────────────────────────────────────────────────────────

async function render() {
  const st = await AASAN.getState();
  $("server").value = st.server;
  $("who").textContent = st.displayName ? `Hi, ${st.displayName}` : "";
  $("disconnect").hidden = !st.token;
  showStatus("");
  if (!st.token) {
    show("pair");
    $("code").focus();
    return;
  }
  show("tasks");
  watching = (await chrome.storage.local.get("watch")).watch || null;
  const tab = await activeTab();
  currentWindowId = tab && tab.windowId;
  renderTasks(st.tasks, tab);
  try {
    renderTasks(await AASAN.refreshTasks(), await activeTab());
  } catch (e) {
    if (e.status === 401) return render();
    showStatus(errorText(e), true);
  }
}

function renderTasks(tasks, tab) {
  const url = (tab && tab.url) || "";
  let host = "";
  try { host = /^https?:/.test(url) ? new URL(url).hostname : ""; } catch { host = ""; }
  $("tab-info").textContent = host ? `This tab: ${host}` : "Open the task's website in this tab.";
  const here = (t) => !!url && AASAN.taskMatchesUrl(t, url);
  const sorted = [...tasks].sort((a, b) => Number(here(b)) - Number(here(a)));
  const list = $("task-list");
  list.replaceChildren(...sorted.map((t) => taskItem(t, here(t), !!host)));
  $("empty").hidden = tasks.length > 0;
}

function taskItem(t, isHere, canCapture) {
  const steps = Array.isArray(t.steps) ? t.steps : [];
  const details = el("details", isHere ? { open: "" } : {}, [
    el("summary", { text: "What to do" }),
    t.prompt ? el("p", { text: t.prompt }) : null,
    steps.length ? el("ol", {}, steps.map((s) => el("li", { text: String(s) }))) : null,
    t.proof ? el("p", { class: "proof", text: `Your screenshot must show: ${t.proof}` }) : null,
  ]);
  const actions = el("div", { class: "actions" }, [
    el("button", { type: "button", class: "primary", text: "I've done it on this tab", ...(canCapture ? {} : { disabled: "" }),
                   onclick: safely((ev) => submit(t, ev.currentTarget)) }),
    t.link && /^https:\/\//.test(t.link) ? el("button", { type: "button", class: "secondary", text: "Open site",
                                                         onclick: safely(() => chrome.tabs.update({ url: t.link })) }) : null,
    el("button", { type: "button", class: "secondary", text: "Lesson", onclick: safely(() => openAasan(t.lesson_path)) }),
    t.observe ? el("button", { type: "button", class: "secondary", text: watchingThis(t) ? "Show steps" : "Watch steps", onclick: safely(() => watch(t)) }) : null,
  ]);
  return el("li", { class: `task${isHere ? " here" : ""}` }, [
    isHere ? el("span", { class: "tag", text: "✓ Matches this site" }) : null,
    watchingThis(t) ? el("span", { class: "tag", text: ` 👀 Watching: ${watching.observed.length}/${watching.steps.length} steps` }) : null,
    el("h2", { text: t.title || "Browser task" }),
    el("p", { class: "crumb", text: [t.course_title, t.lesson_title].filter(Boolean).join(" › ") }),
    t.last_score != null ? el("p", { class: "small muted", text: `Last try: ${Math.round(t.last_score * 100)}%` }) : null,
    details,
    actions,
  ]);
}

// ── Capture + submit ─────────────────────────────────────────────

async function submit(task, button) {
  showStatus("");
  if (task.observe && !task.observe.optional && !(watchingThis(task) && AASAN_STEPS.isDone(watching))) {
    return showStatus(ERRORS.steps_required, true); // the server would refuse it anyway (422 steps_required)
  }
  const tab = await activeTab();
  if (!tab || !/^https?:\/\//.test(tab.url || "")) return showStatus(ERRORS.bad_url, true);
  const url = AASAN.submitUrl(tab.url);
  if (!url) return showStatus(ERRORS.url_too_long, true);
  button.disabled = true;
  const label = button.textContent;
  button.textContent = "Checking…";
  try {
    let image;
    try {
      image = await AASAN.shrink(await chrome.tabs.captureVisibleTab(tab.windowId, { format: "jpeg", quality: 80 }));
    } catch {
      throw new AASAN.ApiError(0, { code: "capture" });
    }
    const body = { url, title: (tab.title || "").slice(0, 500), image };
    if (watchingThis(task) && AASAN_STEPS.isDone(watching)) body.observed = AASAN_STEPS.evidence(watching);
    const res = await AASAN.call(`/api/ext/tasks/${encodeURIComponent(task.id)}/submit/`, { method: "POST", body });
    if (body.observed && res.correct) await AASAN.stopWatching(); // done: give the site permissions back
    image = null; // the screenshot only lives in memory for this request
    showResult(res);
    AASAN.refreshTasks().catch(() => {});
  } catch (e) {
    if (e.status === 401) return render();
    showStatus(errorText(e), true);
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

function watchingThis(t) {
  return !!watching && watching.taskId === t.id;
}

/** Start (or show) live observation: ask for exactly this task's sites, then open the side panel. */
async function watch(task) {
  showStatus("");
  // Open the panel first, while this click still counts as a user gesture.
  const opening = chrome.sidePanel && currentWindowId !== undefined ? chrome.sidePanel.open({ windowId: currentWindowId }).catch(() => {}) : null;
  if (watchingThis(task)) return opening;
  const w = AASAN_STEPS.newWatch(task);
  if (!w) return;
  let granted = false;
  try { granted = await chrome.permissions.request({ origins: w.origins }); } catch { granted = false; }
  if (!granted) return showStatus(ERRORS.watch_permission, true);
  const { server } = await AASAN.getState();
  const stale = (watching && watching.origins ? watching.origins : []).filter((o) => !w.origins.includes(o) && !o.startsWith(`${server}/`));
  if (stale.length) await chrome.permissions.remove({ origins: stale }).catch(() => {}); // the previous task's sites
  await chrome.storage.local.set({ watch: w });
  watching = w;
  await opening;
  const tab = await activeTab();
  if (tab) await chrome.runtime.sendMessage({ type: "aasan-check" }).catch(() => {}); // maybe the first page is already open
  renderTasks((await AASAN.getState()).tasks, tab);
}

function showResult(r) {
  const pct = Math.round((Number(r.score) || 0) * 100);
  $("result-score").textContent = `${pct}%`;
  $("result-verdict").textContent = r.correct ? "Well done — task complete!" : "Not quite yet — have another go.";
  $("result-feedback").textContent = r.feedback || "";
  $("result-card").className = `result ${r.correct ? "pass" : "fail"}`;
  lastLessonPath = r.lesson_path || "";
  $("open-lesson").hidden = !lastLessonPath;
  show("result");
}

// ── Events ───────────────────────────────────────────────────────

$("pair-form").addEventListener("submit", safely(async (ev) => {
  ev.preventDefault();
  const code = $("code").value.replace(/\D/g, "");
  if (code.length !== 6) return showStatus("Type the 6-digit code from Aasan.", true);
  const st = await AASAN.getState();
  if (!(await ensurePermission(st.server))) return showStatus(ERRORS.permission, true);
  $("pair-btn").disabled = true;
  try {
    const r = await AASAN.call("/api/ext/pair/claim/", { method: "POST", body: { code }, token: "" });
    if (!r || typeof r.token !== "string") throw new AASAN.ApiError(500, {});
    await chrome.storage.local.set({ token: r.token, displayName: String((r.user && r.user.display_name) || "").slice(0, 60) });
    $("code").value = "";
    await render();
  } catch (e) {
    showStatus(errorText(e), true);
  } finally {
    $("pair-btn").disabled = false;
  }
}));

$("settings-form").addEventListener("submit", safely(async (ev) => {
  ev.preventDefault();
  const origin = AASAN.normalizeServer($("server").value);
  if (!origin) return showStatus("Use an https:// address (or http://localhost for development).", true);
  if (!(await ensurePermission(origin))) return showStatus(ERRORS.permission, true);
  const st = await AASAN.getState();
  if (origin !== st.server) {
    await AASAN.forgetToken(); // a token only belongs to the server that issued it
    await chrome.storage.local.set({ server: origin });
  }
  $("settings").open = false;
  await render();
  showStatus(`Saved. Aasan address: ${origin}`);
}));

$("disconnect").addEventListener("click", safely(async () => {
  try { await AASAN.call("/api/ext/disconnect/", { method: "POST" }); } catch { /* still forget it locally */ }
  await AASAN.forgetToken();
  await render();
}));

$("refresh").addEventListener("click", safely(render));
$("back").addEventListener("click", safely(render));
$("open-lesson").addEventListener("click", safely(() => openAasan(lastLessonPath)));

safely(render)();
