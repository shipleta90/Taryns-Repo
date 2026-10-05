// Caches the app shell only. API responses are never cached by the service worker.
const SHELL = "agent-shell-v1";
const FILES = ["/", "/static/style.css", "/static/app.js", "/static/manifest.webmanifest"];

self.addEventListener("install", (e) => e.waitUntil(caches.open(SHELL).then((c) => c.addAll(FILES))));
self.addEventListener("activate", (e) =>
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== SHELL).map((k) => caches.delete(k))))));
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/")) return;
  e.respondWith(
    fetch(e.request).then((r) => { caches.open(SHELL).then((c) => c.put(e.request, r.clone())); return r; })
      .catch(() => caches.match(e.request)),
  );
});
