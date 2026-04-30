/**
 * AIOS Service Worker v3.1.0
 * Cache strategy:
 *   /static/*      → Cache-first (immutable assets)
 *   HTML pages     → Network-first, cache fallback, then /offline.html
 *   /api/*         → Network only (never cache)
 *   /login|/otp    → Network only (never serve stale auth)
 *   POST requests  → Network; respond 503+offline JSON on failure so sync-manager.js queues them
 */

const STATIC_CACHE  = 'aios-static-v3.1';
const PAGE_CACHE    = 'aios-pages-v3.1';
const ALL_CACHES    = [STATIC_CACHE, PAGE_CACHE];

const PRECACHE = [
  '/static/css/aios.css',
  '/static/css/subpages.css',
  '/static/css/admin.css',
  '/static/js/aios.js',
  '/static/js/offline-db.js',
  '/static/js/sync-manager.js',
  '/offline',
];

const NETWORK_ONLY_PATHS = ['/login', '/otp', '/logout', '/api/'];
const NEVER_CACHE_METHODS = ['PUT', 'PATCH', 'DELETE'];

// ── Install ───────────────────────────────────────────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then(cache => cache.addAll(PRECACHE).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

// ── Activate: prune old caches ────────────────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => !ALL_CACHES.includes(k)).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

// ── Fetch ─────────────────────────────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const req  = event.request;
  const url  = new URL(req.url);

  // Only handle same-origin requests
  if (url.origin !== location.origin) return;

  const path = url.pathname;

  // Network-only: auth pages and API endpoints
  if (NETWORK_ONLY_PATHS.some(p => path.startsWith(p))) return;

  // Static assets: cache-first
  if (path.startsWith('/static/')) {
    event.respondWith(cacheFirst(req));
    return;
  }

  // Non-GET requests: attempt network; on failure return offline sentinel
  if (req.method !== 'GET') {
    event.respondWith(
      fetch(req).catch(() => _offlineResponse(path))
    );
    return;
  }

  // GET pages: network-first with cache fallback
  event.respondWith(networkFirstPage(req, path));
});

// ── Helpers ───────────────────────────────────────────────────────────────────
async function cacheFirst(req) {
  const cached = await caches.match(req);
  if (cached) return cached;
  try {
    const resp = await fetch(req);
    if (resp.ok) {
      const cache = await caches.open(STATIC_CACHE);
      cache.put(req, resp.clone());
    }
    return resp;
  } catch {
    return new Response('Asset unavailable offline.', { status: 503 });
  }
}

async function networkFirstPage(req, path) {
  try {
    const resp = await fetch(req);
    if (resp.ok) {
      const cache = await caches.open(PAGE_CACHE);
      cache.put(req, resp.clone());
      // Tell all clients we're back online
      _broadcast({ type: 'ONLINE' });
    }
    return resp;
  } catch {
    const cached = await caches.match(req);
    if (cached) {
      _broadcast({ type: 'OFFLINE_CACHE_HIT', path });
      return cached;
    }
    const fallback = await caches.match('/offline');
    if (fallback) {
      _broadcast({ type: 'OFFLINE_FALLBACK', path });
      return fallback;
    }
    return new Response('<h1>Offline</h1><p>No cached version available.</p>', {
      status: 503, headers: { 'Content-Type': 'text/html' }
    });
  }
}

function _offlineResponse(path) {
  _broadcast({ type: 'POST_OFFLINE', path });
  return new Response(
    JSON.stringify({ ok: false, offline: true, queued: false,
                     error: 'No internet connection — change queued for sync.' }),
    { status: 503, headers: { 'Content-Type': 'application/json' } }
  );
}

function _broadcast(msg) {
  self.clients.matchAll({ includeUncontrolled: true })
    .then(clients => clients.forEach(c => c.postMessage(msg)));
}

// ── Message handler (from main thread) ───────────────────────────────────────
self.addEventListener('message', event => {
  if (event.data?.type === 'SKIP_WAITING') self.skipWaiting();
});
