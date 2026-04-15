// TASUKARU Service Worker - キャッシュ無効化バージョン
const CACHE_VERSION = 'tasukaru-v6';
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const DATA_CACHE = `${CACHE_VERSION}-data`;

self.addEventListener('install', e => { self.skipWaiting(); });
self.addEventListener('activate', e => {
    e.waitUntil(
        caches.keys().then(keys => Promise.all(keys.map(k => caches.delete(k))))
        .then(() => self.clients.claim())
    );
});
self.addEventListener('fetch', e => { e.respondWith(fetch(e.request)); });
