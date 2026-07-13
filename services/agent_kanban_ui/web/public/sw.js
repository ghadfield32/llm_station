const STATIC_CACHE = "agent-kanban-static-v2";
const STATIC_ASSETS = [
  "/",
  "/manifest.webmanifest",
  "/icons/cockpit-icon.svg",
  "/icons/cockpit-icon-192.png",
  "/icons/cockpit-icon-512.png",
  "/icons/cockpit-maskable.svg",
  "/icons/cockpit-maskable-512.png",
  "/icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(STATIC_ASSETS)),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys
        .filter((key) => key.startsWith("agent-kanban-") && key !== STATIC_CACHE)
        .map((key) => caches.delete(key)),
    )),
  );
  self.clients.claim();
});

function isApiRequest(url) {
  return url.origin === self.location.origin && url.pathname.startsWith("/api/");
}

function isStaticRequest(request, url) {
  if (request.method !== "GET") return false;
  if (url.origin !== self.location.origin) return false;
  if (isApiRequest(url)) return false;
  if (url.pathname.startsWith("/assets/")) return true;
  return ["script", "style", "image", "font", "manifest"].includes(request.destination);
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || isApiRequest(url)) return;

  if (event.request.mode === "navigate") {
    event.respondWith(fetch(event.request).catch(() => caches.match("/")));
    return;
  }

  if (!isStaticRequest(event.request, url)) return;

  event.respondWith((async () => {
    const cache = await caches.open(STATIC_CACHE);
    const cached = await cache.match(event.request);
    try {
      const response = await fetch(event.request);
      if (response.ok) await cache.put(event.request, response.clone());
      return response;
    } catch (err) {
      if (cached) return cached;
      throw err;
    }
  })());
});
