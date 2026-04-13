// TASUKARU Service Worker
// バージョンを上げると古いキャッシュが自動削除される
const CACHE_VERSION = 'tasukaru-v2';
const STATIC_CACHE  = `${CACHE_VERSION}-static`;
const DATA_CACHE    = `${CACHE_VERSION}-data`;

// 静的ファイル（オフラインでも使えるようにキャッシュ）
const STATIC_FILES = [
    '/',
    '/top',
    '/login',
    '/input',
    '/daily_view',
    '/vitals',
    '/calendar',
    '/static/manifest.json',
    '/static/admin.js',
    'https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200',
];

// ===== インストール =====
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(STATIC_CACHE).then(cache => {
            return cache.addAll(STATIC_FILES).catch(err => {
                console.log('[SW] 一部ファイルのキャッシュに失敗:', err);
            });
        }).then(() => self.skipWaiting())
    );
});

// ===== アクティベート（古いキャッシュ削除） =====
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(
                keys.filter(k => k.startsWith('tasukaru-') && k !== STATIC_CACHE && k !== DATA_CACHE)
                    .map(k => caches.delete(k))
            )
        ).then(() => self.clients.claim())
    );
});

// ===== フェッチ処理 =====
self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);

    // POSTリクエスト（フォーム送信など）は必ずネットワーク優先・Service Worker非介入
    if (event.request.method !== 'GET') {
        event.respondWith(
            fetch(event.request.clone()).catch(() => {
                // オフライン時のみキューに保存（APIのみ）
                if (url.pathname.startsWith('/api/')) {
                    return networkFirstWithOfflineQueue(event.request);
                }
                return new Response(JSON.stringify({
                    status: 'offline',
                    message: 'オフラインです'
                }), { headers: { 'Content-Type': 'application/json' } });
            })
        );
        return;
    }

    // GETのAPIリクエスト
    if (url.pathname.startsWith('/api/')) {
        return; // Service Worker非介入でそのままネットワークへ
    }

    // 静的ファイル・ページはキャッシュファースト
    event.respondWith(
        caches.match(event.request).then(cached => {
            if (cached) return cached;
            return fetch(event.request).then(response => {
                if (response.ok && event.request.method === 'GET') {
                    const clone = response.clone();
                    caches.open(STATIC_CACHE).then(cache => cache.put(event.request, clone));
                }
                return response;
            }).catch(() => {
                return caches.match('/top') || new Response(
                    getOfflinePage(),
                    { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
                );
            });
        })
    );
});

// ===== オフライン時のAPIキューイング =====
async function networkFirstWithOfflineQueue(request) {
    try {
        const response = await fetch(request.clone());
        return response;
    } catch (err) {
        // オフライン時：POSTリクエストをIndexedDBに保存
        if (request.method === 'POST') {
            try {
                const body = await request.clone().text();
                await saveOfflineRequest({
                    url: request.url,
                    method: request.method,
                    body: body,
                    headers: Object.fromEntries(request.headers.entries()),
                    timestamp: new Date().toISOString()
                });
                return new Response(JSON.stringify({
                    status: 'queued',
                    message: 'オフラインのため記録を一時保存しました。ネット接続後に自動送信されます。'
                }), { headers: { 'Content-Type': 'application/json' } });
            } catch(e) {
                return new Response(JSON.stringify({
                    status: 'error',
                    message: 'オフライン保存に失敗しました'
                }), { headers: { 'Content-Type': 'application/json' } });
            }
        }
        // GETはキャッシュを返す
        return caches.match(request) || new Response(
            JSON.stringify({ status: 'offline', message: 'オフラインです' }),
            { headers: { 'Content-Type': 'application/json' } }
        );
    }
}

// ===== IndexedDBにオフラインリクエストを保存 =====
function saveOfflineRequest(data) {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open('tasukaru-offline', 1);
        req.onupgradeneeded = e => {
            e.target.result.createObjectStore('queue', { autoIncrement: true });
        };
        req.onsuccess = e => {
            const db = e.target.result;
            const tx = db.transaction('queue', 'readwrite');
            tx.objectStore('queue').add(data);
            tx.oncomplete = resolve;
            tx.onerror = reject;
        };
        req.onerror = reject;
    });
}

// ===== バックグラウンド同期 =====
self.addEventListener('sync', event => {
    if (event.tag === 'sync-offline-records') {
        event.waitUntil(syncOfflineRecords());
    }
});

async function syncOfflineRecords() {
    const db = await openDB();
    const items = await getAllItems(db);
    for (const item of items) {
        try {
            await fetch(item.data.url, {
                method: item.data.method,
                body: item.data.body,
                headers: item.data.headers
            });
            await deleteItem(db, item.key);
        } catch (e) {
            console.log('[SW] 同期失敗:', e);
        }
    }
}

function openDB() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open('tasukaru-offline', 1);
        req.onupgradeneeded = e => e.target.result.createObjectStore('queue', { autoIncrement: true });
        req.onsuccess = e => resolve(e.target.result);
        req.onerror = reject;
    });
}

function getAllItems(db) {
    return new Promise((resolve, reject) => {
        const items = [];
        const tx = db.transaction('queue', 'readonly');
        const store = tx.objectStore('queue');
        const req = store.openCursor();
        req.onsuccess = e => {
            const cursor = e.target.result;
            if (cursor) { items.push({ key: cursor.key, data: cursor.value }); cursor.continue(); }
            else resolve(items);
        };
        req.onerror = reject;
    });
}

function deleteItem(db, key) {
    return new Promise((resolve, reject) => {
        const tx = db.transaction('queue', 'readwrite');
        tx.objectStore('queue').delete(key);
        tx.oncomplete = resolve;
        tx.onerror = reject;
    });
}

// ===== オフラインページ =====
function getOfflinePage() {
    return `<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>オフライン - TASUKARU</title>
<style>
body { font-family: sans-serif; display:flex; flex-direction:column; align-items:center; justify-content:center; min-height:100vh; margin:0; background:#f8f9fa; color:#202124; text-align:center; padding:20px; }
.icon { font-size:64px; margin-bottom:16px; }
h1 { font-size:1.4rem; margin-bottom:8px; }
p { color:#5f6368; font-size:0.9rem; line-height:1.6; }
button { margin-top:20px; padding:12px 24px; background:#1a73e8; color:#fff; border:none; border-radius:10px; font-size:1rem; cursor:pointer; }
</style>
</head>
<body>
<div class="icon">📵</div>
<h1>オフラインです</h1>
<p>インターネット接続がありません。<br>オフラインで保存した記録はネット接続後に自動送信されます。</p>
<button onclick="location.reload()">再接続を確認</button>
</body>
</html>`;
}
