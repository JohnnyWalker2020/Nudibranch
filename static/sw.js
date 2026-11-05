// Nudibranch Service Worker (PWA installability and asset caching)
const CACHE_NAME = 'nudibranch-v2';
const ASSETS_TO_CACHE = [
  '/',
  '/static/manifest.json',
  '/static/icons/icon.svg',
  '/static/icons/nudibranch/cyberpunk.svg',
  '/static/icons/nudibranch/dragon.svg',
  '/static/icons/nudibranch/kpop_hunter.svg',
  '/static/icons/nudibranch/medieval_knight.svg',
  '/static/icons/nudibranch/ninja_turtle.svg',
  '/static/icons/nudibranch/robot.svg',
  '/static/icons/nudibranch/superhero.svg',
  '/static/icons/nudibranch/unicorn.svg',
  '/static/icons/nudibranch/witch.svg',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    })
  );
  self.clients.claim();
});

// Network-first strategy with cache fallback
self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;

  event.respondWith(
    fetch(event.request)
      .then((networkResponse) => {
        return networkResponse;
      })
      .catch(() => {
        return caches.match(event.request);
      })
  );
});
