/* ============================================================
   The Ones AI Feed — Service Worker
   PWA offline support, smart caching strategies
   ============================================================ */

const VERSION = 'feed-v1.2.0';
const STATIC_CACHE = `${VERSION}-static`;
const RUNTIME_CACHE = `${VERSION}-runtime`;
const IMAGE_CACHE = `${VERSION}-images`;
const ARTICLE_CACHE = `${VERSION}-articles`;

// Core static assets to pre-cache on install
const PRECACHE_URLS = [
    '/',
    '/static/css/style.css',
    '/static/js/main.js',
    '/static/manifest.json',
    '/static/img/icon-192.png',
    '/static/img/icon-512.png',
    '/static/img/apple-touch-icon.png',
    '/offline.html',
];

// ============================================================
// INSTALL — pre-cache core assets
// ============================================================
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(STATIC_CACHE)
            .then(cache => {
                console.log('[SW] Pre-caching core assets');
                return cache.addAll(PRECACHE_URLS).catch(err => {
                    console.warn('[SW] Satme assets failed to precache', err);
                });
            })
            .then(() => self.skipWaiting())
    );
});

// ============================================================
// ACTIVATE — clean up old caches
// ============================================================
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys => {
            return Promise.all(
                keys.filter(key => !key.startsWith(VERSION))
                    .map(key => {
                        console.log('[SW] Deleting old cache:', key);
                        return caches.delete(key);
                    })
            );
        }).then(() => self.clients.claim())
    );
});

// ============================================================
// FETCH — smart caching strategies
// ============================================================
self.addEventListener('fetch', event => {
    const req = event.request;
    const url = new URL(req.url);

    // Only handle GET requests
    if (req.method !== 'GET') return;
    // Don't cache cross-origin (except images CDN)
    if (url.origin !== self.location.origin && !isImageCDN(url)) return;

    // Strategy: Images → Cache-first, long TTL
    if (isImage(req)) {
        event.respondWith(cacheFirst(req, IMAGE_CACHE));
        return;
    }

    // Strategy: Article API & pages → Network-first, fallback to cache
    if (url.pathname.startsWith('/api/article/') || url.pathname.startsWith('/a/')) {
        event.respondWith(networkFirst(req, ARTICLE_CACHE));
        return;
    }

    // Strategy: News API → Network-first (always fresh), short cache fallback
    if (url.pathname.startsWith('/api/news') || url.pathname.startsWith('/api/category')) {
        event.respondWith(networkFirst(req, RUNTIME_CACHE));
        return;
    }

    // Strategy: Static assets → Cache-first
    if (url.pathname.startsWith('/static/') || url.pathname === '/static/manifest.json') {
        event.respondWith(cacheFirst(req, STATIC_CACHE));
        return;
    }

    // Strategy: HTML pages → Network-first with offline fallback
    if (req.mode === 'navigate' || (req.headers.get('accept') || '').includes('text/html')) {
        event.respondWith(
            networkFirst(req, RUNTIME_CACHE)
                .catch(() => caches.match('/offline.html'))
        );
        return;
    }

    // Default: try network, fallback to cache
    event.respondWith(
        fetch(req).catch(() => caches.match(req))
    );
});

// ============================================================
// HELPERS
// ============================================================
function isImage(req) {
    return req.destination === 'image' ||
           /\.(png|jpg|jpeg|gif|webp|svg|avif)(\?|$)/i.test(req.url);
}

function isImageCDN(url) {
    const cdns = ['images.pexels.com', 'images.unsplash.com', 'lh3.googleusercontent.com',
                  'cdn.cnn.com', 'media.vogue.com', 'fonts.gstatic.com', 'fonts.googleapis.com'];
    return cdns.some(cdn => url.hostname.includes(cdn));
}

async function cacheFirst(req, cacheName) {
    const cache = await caches.open(cacheName);
    const cached = await cache.match(req);
    if (cached) return cached;
    try {
        const fresh = await fetch(req);
        if (fresh.ok || fresh.type === 'opaque') {
            cache.put(req, fresh.clone()).catch(() => {});
        }
        return fresh;
    } catch (err) {
        return cached || Response.error();
    }
}

async function networkFirst(req, cacheName) {
    const cache = await caches.open(cacheName);
    try {
        const fresh = await fetch(req);
        if (fresh.ok) {
            cache.put(req, fresh.clone()).catch(() => {});
        }
        return fresh;
    } catch (err) {
        const cached = await cache.match(req);
        if (cached) return cached;
        throw err;
    }
}

// ============================================================
// MESSAGE handler — for skipWaiting from page
// ============================================================
self.addEventListener('message', event => {
    if (event.data && event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
});

// ============================================================
// PUSH NOTIFICATIONS
// ============================================================
self.addEventListener('push', event => {
    let data = {};
    try {
        data = event.data ? event.data.json() : {};
    } catch (e) {
        data = { title: 'The Ones AI Feed', body: event.data ? event.data.text() : 'Nowe newsy' };
    }

    const title = data.title || '🌙 The Ones AI Feed';
    const options = {
        body: data.body || 'Sprawdź najnowsze newsy ze świata piękna ✨',
        icon: data.icon || '/static/img/icon-192.png',
        badge: data.badge || '/static/img/icon-192.png',
        image: data.image || undefined,
        tag: data.tag || 'feed-theones',
        renotify: data.renotify || false,
        requireInteraction: false,
        data: { url: data.url || '/' },
        vibrate: [200, 100, 200],
    };

    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', event => {
    event.notification.close();
    const url = (event.notification.data && event.notification.data.url) || '/';
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
            // If a feed tab is already open, focus it and navigate
            for (const client of windowClients) {
                if (client.url.includes(self.location.origin) && 'focus' in client) {
                    client.navigate(url);
                    return client.focus();
                }
            }
            // Otherwise open new window
            if (clients.openWindow) {
                return clients.openWindow(url);
            }
        })
    );
});
