const CACHE_NAME = 'tiantianle-ironlaw-20260624050745';
const APP_SHELL = ['index.html','prediction.html','review.html','prediction-history.html','latest_analysis.json','version.json','system_health_report.md','manifest.webmanifest','offline.html','reset.html','icon-192.png','icon-512.png'];
async function deleteAllCaches() {
  const keys = await caches.keys();
  await Promise.all(keys.map(key => caches.delete(key)));
}
async function deleteOldCaches() {
  const keys = await caches.keys();
  await Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key)));
}
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(APP_SHELL.map(url => url + '?v=20260624050745')).catch(() => cache.addAll(APP_SHELL))));
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
    url.searchParams.set('v', '20260624050745');
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
