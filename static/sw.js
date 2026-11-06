// Nudibranch service worker: installability + offline fallback.
// Served from /sw.js (see config/urls.py) so its scope covers the whole site.
const CACHE_NAME = 'nudibranch-v5';
const PRECACHE = [
  '/static/manifest.json',
  '/static/icons/icon.svg',
  '/static/js/app.js',
  '/static/js/charts.js',
  '/static/css/tailwind.css',
  '/static/vendor/htmx.min.js',
  '/static/vendor/chart.umd.js',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      // Add one by one so a single missing file can't abort the whole install.
      Promise.all(PRECACHE.map((url) => cache.add(url).catch(() => null)))
    )
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Network-first for same-origin GETs; keep a copy of good responses for offline use.
// POSTs, API calls, cross-origin requests (CDNs, webcams), photos and backups are left alone:
// a phone doesn't need a second copy of every photo and backup file taking up its storage.
self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (['/api/', '/admin/', '/media/', '/backups/'].some((prefix) => url.pathname.startsWith(prefix))) return;

  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok && res.type === 'basic') {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req).then((hit) => hit || new Response('Offline', { status: 503 })))
  );
});
