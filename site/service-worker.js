const CACHE_NAME = 'tiantianle-ironlaw-20260627175519';
const APP_SHELL = ['index.html','首頁.html','prediction.html','下期預測.html','review.html','上期未命中檢討.html','prediction-history.html','預測歷史對比.html','latest_analysis.json','最新分析資料.json','version.json','版本.json','system_health_report.md','系統健康報告.md','manifest.webmanifest','offline.html','離線頁.html','reset.html','清除快取.html','icon-192.png','icon-512.png'];
async function deleteAllCaches() {
  const keys = await caches.keys();
  await Promise.all(keys.map(key => caches.delete(key)));
}
async function deleteOldCaches() {
  const keys = await caches.keys();
  await Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key)));
}
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(APP_SHELL.map(url => url + '?v=20260627175519')).catch(() => cache.addAll(APP_SHELL))));
  self.skipWaiting();
});
self.addEventListener('activate', event => {
  event.waitUntil(deleteOldCaches().then(() => caches.open(CACHE_NAME)));
  self.clients.claim();
});
self.addEventListener('message', event => {
  if (!event.data) return;
  if (event.data.type === 'SKIP_WAITING') self.skipWaiting();
  if (event.data.type === 'CLEAR_CACHE') event.waitUntil(deleteAllCaches());
});
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  const isFreshFile = url.pathname.endsWith('.html') || url.pathname.endsWith('.json') || url.pathname.endsWith('.md') || url.pathname.endsWith('service-worker.js') || url.pathname.endsWith('manifest.webmanifest') || url.pathname.endsWith('/');
  if (isFreshFile) {
    url.searchParams.set('v', '20260627175519');
    event.respondWith(fetch(url.toString(), { cache: 'no-store', headers: { 'Cache-Control': 'no-cache' } }).then(response => {
      return response;
    }).catch(() => caches.match(event.request).then(hit => hit || caches.match('offline.html'))));
    return;
  }
  event.respondWith(fetch(event.request, { cache: 'no-store' }).then(response => {
    const copy = response.clone();
    caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy));
    return response;
  }).catch(() => caches.match(event.request).then(hit => hit || caches.match('offline.html'))));
});
