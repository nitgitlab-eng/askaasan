/* Aasan service worker: installable app + offline fallback + offline lessons.
   Only lesson/course reads are kept (network-first, per browser; the app deletes this cache on logout).
   Never caches sockets, payments, uploads, or any other API. */
const VERSION = "aasan-v3";
const API_CACHE = "aasan-api-v1";
const OFFLINE_API = [
  /^\/api\/users\/me\/$/,
  /^\/api\/learn\/curriculums\/$/,
  /^\/api\/learn\/curriculums\/\d+\/$/,
  /^\/api\/learn\/subsections\/\d+\/$/,
  /^\/api\/game\/status\/$/,
];
const SHELL = ["/", "/offline.html", "/favicon.svg", "/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION && k !== API_CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") && OFFLINE_API.some((re) => re.test(url.pathname))) {
    // Lessons: network first (always fresh when online), last good copy when offline.
    e.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok && (res.headers.get("content-type") || "").includes("application/json")) {
            const copy = res.clone();
            caches.open(API_CACHE).then((c) => c.put(req.url, copy));
          }
          return res;
        })
        .catch(async () => (await caches.match(req.url, { cacheName: API_CACHE })) || new Response(JSON.stringify({ code: "offline" }), {
          status: 503, headers: { "Content-Type": "application/json" },
        })),
    );
    return;
  }
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws/")) return;

  // Pages: always try the network so a new deploy shows up immediately; fall back to the cached shell, then the offline page.
  if (req.mode === "navigate") {
    e.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(VERSION).then((c) => c.put("/", copy));
          return res;
        })
        .catch(async () => (await caches.match("/")) || caches.match("/offline.html")),
    );
    return;
  }

  // Hashed build assets never change: cache first.
  if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/icons/")) {
    e.respondWith(
      caches.match(req).then(
        (hit) =>
          hit ||
          fetch(req).then((res) => {
            if (res.ok) {
              const copy = res.clone();
              caches.open(VERSION).then((c) => c.put(req, copy));
            }
            return res;
          }),
      ),
    );
  }
});

// Web push: show what the server sent (title, short body, an in-app path). Nothing secret is ever in a push.
self.addEventListener("push", (e) => {
  let data = {};
  try {
    data = e.data ? e.data.json() : {};
  } catch {
    data = { body: e.data ? e.data.text() : "" };
  }
  const title = typeof data.title === "string" && data.title ? data.title.slice(0, 120) : "Aasan";
  e.waitUntil(
    self.registration.showNotification(title, {
      body: typeof data.body === "string" ? data.body.slice(0, 240) : "",
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      tag: typeof data.tag === "string" ? data.tag : undefined,
      data: { url: typeof data.url === "string" ? data.url : "/", ...(typeof data.id === "string" ? { id: data.id } : {}) },
    }),
  );
});

// Tell the server a notification was tapped, so ignored reminders can be sent less often. The worker has no session:
// the push's own random id is the only thing sent (no cookies), and only when it looks like one.
const PUSH_ID = /^[A-Za-z0-9_-]{16,32}$/;
function reportOpened(id) {
  if (typeof id !== "string" || !PUSH_ID.test(id)) return Promise.resolve();
  return fetch("/api/users/push/opened/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
    credentials: "omit",
    keepalive: true,
  }).catch(() => undefined);
}

// Tapping a notification opens the app at its path: same origin only (an absolute or protocol-relative URL is ignored).
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  let target = new URL("/", self.location.origin);
  try {
    const raw = (e.notification.data && e.notification.data.url) || "/";
    const u = new URL(raw, self.location.origin);
    if (u.origin === self.location.origin && raw.startsWith("/") && !raw.startsWith("//")) target = u;
  } catch {
    /* keep "/" */
  }
  e.waitUntil(
    Promise.all([
      self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
        const mine = wins.find((w) => new URL(w.url).origin === self.location.origin);
        if (mine) return mine.navigate(target.href).then((w) => (w || mine).focus()).catch(() => mine.focus());
        return self.clients.openWindow(target.href);
      }),
      reportOpened(e.notification.data && e.notification.data.id),
    ]),
  );
});
