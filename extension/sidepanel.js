/* Side panel: "Watching for…", the task's steps with ticks, and — once every step is observed — a confirmed submit of
   this tab's URL, title and screenshot plus the observed-step list. All text is set with textContent. */
"use strict";

const $ = (id) => document.getElementById(id);

const ERRORS = {
  network: "Can't reach Aasan. Check your internet connection.",
  steps_required: "This task needs its steps watched before sending.",
  steps_incomplete: "Aasan didn't accept the steps. Stop watching, refresh your tasks in the popup and try again.",
  steps_mismatch: "This task's steps changed. Stop watching, refresh your tasks in the popup and start again.",
  step_url_mismatch: "One step was on a page that doesn't match the task. Stop watching and try again.",
  step_text_missing: "A step's text wasn't found. Check the page and try again.",
  wrong_site: "Send from a tab on this task's website.",
  grading_budget_exceeded: "You've reached today's limit for AI-marked answers. Try again tomorrow.",
  grading_unavailable: "Marking is busy right now. Try again in a minute.",
  not_found: "This task isn't available any more.",
  bad_image: "Couldn't read the screenshot of this tab. Try again.",
  capture: "Couldn't capture this tab. Open the Aasan Companion popup and press “I've done it on this tab” — your observed steps are sent with it.",
  url_too_long: "This page's address is too long to send. Open the page again from the site's own menu, then try again.",
  bad_request: "Aasan couldn't read what was sent from this tab. Reload the page and try again.",
  not_browser_task: "This task can't be sent from the extension any more.",
  server: "Aasan had a problem on its side. Try again in a minute.",
};

function errorText(e) {
  const code = (e && e.data && e.data.code) || (e && e.message) || "";
  if (e && e.status === 401) return "This browser was disconnected from Aasan. Connect it again in the popup.";
  if (e && e.status === 429 && code !== "grading_budget_exceeded") return "Too many tries — wait a little and try again.";
  if (!ERRORS[code] && e && e.status >= 500) return ERRORS.server;
  return ERRORS[code] || "Something went wrong. Please try again.";
}

function showStatus(text, isError = false) {
  const el = $("status");
  el.textContent = text || "";
  el.hidden = !text;
  el.classList.toggle("error", !!isError);
}

function el(tag, props = {}, children = []) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "text") n.textContent = v;
    else if (k === "class") n.className = v;
    else n.setAttribute(k, v);
  }
  for (const c of children) if (c) n.append(c);
  return n;
}

async function getWatch() {
  return (await chrome.storage.local.get("watch")).watch || null;
}

async function render() {
  const w = await getWatch();
  $("idle").hidden = !!w;
  $("watching").hidden = !w;
  if (!w) return;
  $("result").hidden = true;
  $("task-title").textContent = w.title || "Browser task";
  const next = AASAN_STEPS.nextStep(w);
  const done = AASAN_STEPS.isDone(w);
  $("next").textContent = done ? "All steps observed." : `Watching for: ${next.label}`;
  $("step-list").replaceChildren(...w.steps.map((s, i) => {
    const ok = i < w.observed.length;
    const current = !ok && next && next.id === s.id;
    const details = [];
    if (s.text) details.push(current && w.waiting === s.id ? `Waiting for the page to show “${s.text}”` : `Page shows “${s.text}”`);
    if (ok && w.observed[i].title) details.push(`Seen on: ${w.observed[i].title}`);
    return el("li", { class: ok ? "ok" : current ? "current" : "", "aria-label": `Step ${i + 1}: ${s.label} — ${ok ? "done" : "not yet"}` }, [
      el("span", { class: "mark", "aria-hidden": "true", text: ok ? "✓" : String(i + 1) }),
      el("div", {}, [el("p", { class: "label", text: s.label }), details.length ? el("p", { class: "detail", text: details.join(" · ") }) : null]),
    ]);
  }));
  $("sites").textContent = `Watching only on: ${w.hosts.join(", ")}`;
  $("done").hidden = !done;
  $("check").hidden = done;
  const granted = await chrome.permissions.contains({ origins: w.origins });
  if (!granted) showStatus("Permission for this task's sites was not given, so nothing is watched. Choose Watch steps in the popup again.", true);
}

async function send() {
  const w = await getWatch();
  if (!w || !AASAN_STEPS.isDone(w)) return;
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab || !AASAN_STEPS.hostAllowed(tab.url, w.hosts)) return showStatus(ERRORS.wrong_site, true);
  const url = AASAN.submitUrl(tab.url);
  if (!url) return showStatus(ERRORS.url_too_long, true);
  // eslint-disable-next-line no-alert
  if (!window.confirm(`Send this tab to Aasan for marking?\n\n${tab.title || tab.url}\n\nIts address, title and a screenshot of what you can see will be shared.`)) return;
  showStatus("");
  const btn = $("send");
  btn.disabled = true;
  btn.textContent = "Checking…";
  try {
    let image;
    try {
      image = await AASAN.shrink(await chrome.tabs.captureVisibleTab(tab.windowId, { format: "jpeg", quality: 80 }));
    } catch {
      throw new AASAN.ApiError(0, { code: "capture" });
    }
    const res = await AASAN.call(`/api/ext/tasks/${encodeURIComponent(w.taskId)}/submit/`, {
      method: "POST",
      body: { url, title: (tab.title || "").slice(0, 500), image, observed: AASAN_STEPS.evidence(w) },
    });
    image = null; // only lives in memory for this request
    if (res.correct) await AASAN.stopWatching(); // done: give the site permissions back
    showResult(res);
    AASAN.refreshTasks().catch(() => {});
  } catch (e) {
    showStatus(errorText(e), true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Send for marking";
  }
}

function showResult(r) {
  $("result-score").textContent = `${Math.round((Number(r.score) || 0) * 100)}%`;
  $("result-verdict").textContent = r.correct ? "Well done — task complete!" : "Not quite yet — have another go.";
  $("result-feedback").textContent = r.feedback || "";
  $("result-card").className = `result ${r.correct ? "pass" : "fail"}`;
  $("result").hidden = false;
}

/** Show anything a handler didn't catch instead of leaving an unhandled rejection. */
function safely(fn) {
  return (...args) => {
    try { return Promise.resolve(fn(...args)).catch((e) => showStatus(errorText(e), true)); } catch (e) { showStatus(errorText(e), true); }
  };
}

$("check").addEventListener("click", safely(async () => {
  showStatus("");
  await chrome.runtime.sendMessage({ type: "aasan-check" }).catch(() => {});
}));
$("stop").addEventListener("click", safely(async () => {
  await AASAN.stopWatching();
  showStatus("Stopped watching. The extension no longer has access to this task's sites.");
}));
$("send").addEventListener("click", safely(send));
$("result-close").addEventListener("click", safely(() => { $("result").hidden = true; return render(); }));
chrome.storage.onChanged.addListener((changes, area) => { if (area === "local" && changes.watch) safely(render)(); });

safely(render)();
