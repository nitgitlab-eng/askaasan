# Aasan Companion (Chrome / Edge extension)

Aasan lessons sometimes ask the learner to do something on a real website ("browser tasks"), such as asking a chatbot
for a study plan or building a sheet with a SUM formula. Without the extension, the learner takes a screenshot and uploads it.
With Aasan Companion, they open the website, do the task, click **I've done it on this tab**, and see their mark.
For tasks with **live observation steps**, the extension can also watch the learner do each step and tick it off in a side panel.

Plain Manifest V3: no build step, no libraries, no remote code.

| File | What it does |
| --- | --- |
| `manifest.json` | Permissions: `activeTab`, `storage`, `tabs`, `scripting`, `sidePanel`. Host access only for the Aasan address; a task's websites are asked for at runtime (see below). Version `0.2.0`. |
| `popup.html/.css/.js` | Pairing, the task list, **Watch steps**, capture and submit, the result, settings and disconnect. |
| `sidepanel.html/.css/.js` | "Watching for…", the task's steps with ticks, and **Send for marking** once every step is observed. |
| `background.js` | Badge with the number of tasks for the current site; live observation of the watched task's steps. |
| `lib.js` | Shared helpers: storage, API calls, URL matching, screenshot shrinking. |
| `steps.js` | Step matching for live observation (same rules as `api/apps/extension/steps.py`). |
| `test/` | `node --test extension/test/*.test.js` (from the repo root; the glob is needed on Node 22+) — unit tests for step matching and the shared helpers, no dependencies. |
| `package.sh` | Builds the store zip with a production server baked in (see Publishing). |
| `icons/` | PNG icons. `python3 icons/make_icons.py` redraws them using only the standard library. |

## Load it unpacked (development)

1. Start Aasan locally (`api` on :8000 and `web` on :5173). The extension talks to `http://localhost:5173`, which proxies `/api`.
2. Chrome: open `chrome://extensions`. Edge: open `edge://extensions`.
3. Turn on **Developer mode**, click **Load unpacked**, and choose this `extension/` folder.
4. Pin **Aasan Companion** to the toolbar.

If Aasan runs at another address, open the popup, go to **Settings**, enter the address (`https://…`, or `http://localhost…`),
and click **Save**. The browser then asks for permission to reach that address. Changing the address disconnects the
extension, because a device token only works on the server that issued it.

## How pairing works

1. In Aasan, go to **Account → Browser companion → Connect the extension**. The server (`POST /api/ext/pair/start/`)
   creates a 6-digit code. The code works once and expires after 10 minutes. Asking for a new code cancels the old one.
2. Type the code into the extension popup. The extension sends it to `POST /api/ext/pair/claim/` and gets back a long
   random device token. Your password is never typed into the extension.
3. The token is stored in `chrome.storage.local` and sent as `Authorization: AasanExt <token>`. The server keeps only a
   SHA-256 hash of it. **The token works only on `/api/ext/` endpoints** (list tasks, submit, disconnect). It can't
   read your profile, courses or anything else.
4. Every connected browser appears on the Account page, where you can **Remove** it. **Disconnect** in the popup also
   revokes the token on the server.

## Permissions

| Permission | Why |
| --- | --- |
| `storage` | The device token, the task list and the task being watched (`chrome.storage.local`). |
| `tabs` | Read tab URLs and titles: for the badge, and to notice when you reach a step's page. |
| `activeTab` | Take the screenshot of the tab you are on when you click **I've done it on this tab**. |
| `scripting` | Only for a step's "page shows this text" check, only on the watched task's websites (see below). |
| `sidePanel` | The "Watching for…" panel. |
| Host: the Aasan address | Talk to your Aasan server. Other Aasan addresses are asked for when you save them in Settings. |
| Optional host: a task's websites | Asked for **at runtime, for exactly the hosts in that task's steps** (for example `https://docs.google.com/*`) when you click **Watch steps**, and removed again when watching stops. The extension never asks for `<all_urls>` or for a whole public suffix. You can also remove them any time in the browser's extension settings. |

## Live observation (multi-step tasks)

Authors can give a browser task 1–8 steps in the Lab (**Live observation steps** under the activity editor). Each step has:

- a label ("Open a new spreadsheet"),
- a page address pattern, which must start with `https://`. The host can start with `*.` to include subdomains, and
  `*` matches anything in the path (for example `https://docs.google.com/spreadsheets/d/*/edit*`). A `*` never matches
  inside the host, so `https://*.google.com/*` does not match `https://evil.com/x.google.com/`. Patterns can't contain
  a query (`?…`) or fragment (`#…`); the query of the page is ignored. A wildcard can't cover a public suffix or a bare
  TLD (`*.co.in`, `*.github.io`, `*.blogspot.com`, `*.com` are refused), so a task can never ask for everybody's sites.
  The list is `public_suffixes.json`; the API keeps an identical copy in `api/apps/extension/`, and tests check they match.
  URLs with backslashes, spaces or control characters are refused (parsers disagree on their host).
- optionally, text the page must show ("Total").

In the popup, **Watch steps** asks the browser for permission to see exactly those hosts and opens the side panel.
While a task is watched, the background worker looks only at tabs whose host is one of that task's hosts:

1. When such a tab loads a page or changes its URL or title, the extension compares the URL with the next step's pattern.
2. If the step has a text check, the extension runs one small function in that tab with
   `chrome.scripting.executeScript`. It checks whether the page's visible text contains the step's text and returns
   only `true` or `false`. **The page's content never leaves the tab and is never sent to Aasan.** If the text appears
   without a page load (for example after typing), click **Check this page now**.
3. Steps are ticked in order. When all are ticked, the side panel offers **Send for marking**. After you confirm, it
   sends the tab's URL, title and a screenshot, plus the list of observed steps (step id, the page's `https://host/path`
   only — no query or fragment —, the page title cut to 120 characters, and whether the text check passed) to the same
   submit endpoint.

The server checks every observed URL against the step's pattern again, checks that every step is there in order and that
the final page is on one of the task's sites. It refuses a mismatch (`422`) before spending any AI grading. The AI grader
still marks the screenshot; the step list is shown to it as client-reported and unverified. By default a task with steps
**requires** the observed steps (a plain screenshot gets `422 steps_required`); the author can tick "Learners may also send
a plain screenshot" to make them optional.

**Stop watching** in the side panel, **Disconnect**, a passed submission, or watching a different task forgets the
watched task **and removes the site permissions** it asked for (`chrome.permissions.remove`). The Aasan address itself is
never removed this way.

If the side panel can't take the screenshot (some Chrome versions only allow it right after clicking the toolbar
button), open the popup and click **I've done it on this tab**. The observed steps are sent with it.

## Privacy: what is captured

The extension captures something only when you click **I've done it on this tab** (popup) or confirm **Send for marking**
(side panel), and only from the active tab:

- the tab's **URL** and **page title** (an address longer than 2,048 characters is sent without its query and fragment)
- a **screenshot of the visible part of the tab** (`chrome.tabs.captureVisibleTab`). It is JPEG and shrunk to stay under about 2 MB.

These go to your Aasan server. An AI grader checks the screenshot against the task's rubric, using the same grading
path as an uploaded screenshot. **The screenshot is not stored.** The attempt record keeps the URL, the title, the score
and the feedback, and puts `[screenshot not stored]` where the image would be. Before you click, hide passwords and
personal details on the page.

- with live observation: the list of observed steps (step id, page address without query or fragment, page title up to
  120 characters, and whether the text check passed).

The background worker reads tab URLs and titles to light the badge and, while you are watching a task, to notice when you
reach a step's page. Those checks run locally. The extension injects code only for a step's text check, only into tabs
on the watched task's websites, and only after you allowed those websites. The check returns yes/no and reads nothing
else. When no task is being watched, nothing is injected anywhere. The extension never reads or sends the page's
content.

## Site rules (optional, for authors)

A browser task's activity source can include these fields:

- `target_host`: `"docs.google.com"` or `"*.google.com"`
- `url_pattern`: a glob on the full URL, such as `"https://docs.google.com/spreadsheets/*"`

When they are set, the badge lights only on matching pages, and the server refuses submissions from other sites with
`422 wrong_site` before spending any AI grading. Without them, the badge uses the host of the task's link as a hint and
no site check is enforced.

## Publishing to the Chrome Web Store (later)

1. Build the store zip with your production address: `sh extension/package.sh https://aasan.example.com`
   (needs `node` and `zip`). The zip in `extension/dist/` gets that origin as `DEFAULT_SERVER` and as its only
   `host_permissions` entry, has no localhost entries, and leaves out the tests, the README, `package.sh` and
   `icons/make_icons.py`. The source folder keeps the development defaults, so **Load unpacked** still talks to
   `http://localhost:5173`, and any build can point at another server from **Settings**.
2. Increase `version` in `manifest.json` for each upload (now `0.2.0`: live observation, side panel).
3. `optional_host_permissions` keeps `https://*/*`: it is only ever requested at runtime, for exactly one task's hosts
   or a self-hosted Aasan address the learner types in Settings. Narrow it if you don't need self-hosted servers.
4. Sign in to the Chrome Web Store Developer Dashboard with the publisher's Google developer account. Registration
   costs a one-time fee. Create a new item and upload the zip.
5. Fill in the listing: description, screenshots, a 128×128 icon, and the **privacy practices** form. Declare that it
   handles website content (the screenshot), explain the single purpose ("submit Aasan browser-task evidence"), and justify
   `tabs`, `activeTab`, `scripting` (yes/no text check on the task's own sites only), `sidePanel` and the optional host
   permissions (asked for per task, at runtime). Link the Aasan privacy policy.
6. Submit for review. For Edge, upload the same zip to the Microsoft Partner Center (Edge Add-ons).
