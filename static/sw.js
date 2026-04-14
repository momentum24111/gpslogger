/* GPSLogger Service Worker — App-Shell & Leaflet-CDN, APIs immer live */
const CACHE_VERSION = "gpslogger-v1";
const CACHE_NAME = `gpslogger-static-${CACHE_VERSION}`;

const PRECACHE_SAME_ORIGIN = [
  "/",
  "/index.html",
  "/static/components.css",
  "/static/app.js",
  "/static/ui-components.js",
  "/static/ripple.js",
  "/static/manifest.webmanifest",
  "/static/favicon.svg",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/icon-maskable-512.png",
  "/static/icons/apple-touch-icon.png",
  "/themes/light/theme.css",
  "/themes/dark/theme.css",
];

const PRECACHE_EXTERNAL = [
  "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
  "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
];

async function precacheUrls(cache, urls) {
  await Promise.all(
    urls.map((url) =>
      cache.add(url).catch(() => {
        /* Offline oder einzelner Fehler — Installation trotzdem erlauben */
      }),
    ),
  );
}

async function precacheExternal(cache) {
  for (const url of PRECACHE_EXTERNAL) {
    try {
      const res = await fetch(url, { mode: "cors", credentials: "omit" });
      if (res.ok) {
        await cache.put(url, res);
      }
    } catch {
      /* ignorieren */
    }
  }
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE_NAME);
      await precacheUrls(cache, PRECACHE_SAME_ORIGIN);
      await precacheExternal(cache);
    })().then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys.map((key) => {
          if (key.startsWith("gpslogger-static-") && key !== CACHE_NAME) {
            return caches.delete(key);
          }
          return Promise.resolve();
        }),
      );
      await self.clients.claim();
    })(),
  );
});

function isApiPath(pathname) {
  return pathname.startsWith("/api/");
}

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") {
    return;
  }

  const url = new URL(event.request.url);

  if (url.origin === self.location.origin && isApiPath(url.pathname)) {
    event.respondWith(fetch(event.request));
    return;
  }

  if (url.origin !== self.location.origin) {
    if (url.href.startsWith("https://unpkg.com/leaflet")) {
      event.respondWith(
        (async () => {
          const cache = await caches.open(CACHE_NAME);
          const cached = await cache.match(event.request);
          if (cached) {
            return cached;
          }
          try {
            const res = await fetch(event.request);
            if (res.ok) {
              await cache.put(event.request, res.clone());
            }
            return res;
          } catch {
            return cached;
          }
        })(),
      );
    }
    return;
  }

  event.respondWith(
    (async () => {
      try {
        const res = await fetch(event.request);
        return res;
      } catch {
        const cache = await caches.open(CACHE_NAME);
        const fallback = await cache.match(event.request);
        if (fallback) {
          return fallback;
        }
        if (event.request.mode === "navigate" || event.request.destination === "document") {
          const doc = await cache.match("/");
          if (doc) {
            return doc;
          }
        }
        return new Response("Offline", { status: 503, statusText: "Service Unavailable" });
      }
    })(),
  );
});
