// Nudibranch service worker: installability, plus a clear message when the server can't be reached.
// Served from /sw.js (see config/urls.py) so its scope covers the whole site.
const CACHE_NAME = 'nudibranch-v6';
const PRECACHE = [
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

// Pages always come from the server. When it can't be reached, this says so plainly, rather than showing
// a saved copy that could be days old (old readings, missing features, charts that can't load).
const OFFLINE_PAGE = `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Can't reach Nudibranch</title>
<style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#020617;color:#e2e8f0;
font-family:system-ui,-apple-system,sans-serif;padding:24px;box-sizing:border-box}main{max-width:22rem;text-align:center}
h1{font-size:1.25rem;margin:.5rem 0}p{font-size:.9rem;color:#94a3b8;line-height:1.5}
button{margin-top:1rem;padding:.75rem 1.5rem;border:0;border-radius:.75rem;background:#06b6d4;color:#020617;font-weight:800;font-size:1rem}</style>
</head><body><main><div style="font-size:2.5rem">📡</div><h1>Can't reach Nudibranch</h1>
<p>Your device couldn't connect to the app. If you're away from home, check that Tailscale is switched on and connected, then try again.</p>
<button onclick="location.reload()">Try again</button></main></body></html>`;

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).catch(() => new Response(OFFLINE_PAGE, {
      status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' },
    })));
    return;
  }
  // Only the app's own scripts, styles and icons are kept, so the message above has what it needs.
  // API calls, photos and backups are left alone.
  if (!url.pathname.startsWith('/static/')) return;

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
