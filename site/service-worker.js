const CACHE_NAME = 'tiantianle-ironlaw-20260620202140';
const APP_SHELL = ['index.html','prediction.html','review.html','prediction-history.html','latest_analysis.json','system_health_report.md','manifest.webmanifest','offline.html','icon-192.png','icon-512.png'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(APP_SHELL.map(url => url + '?v=20260620202140')).catch(() => cache.addAll(APP_SHELL))));
  self.skipWaiting();
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key)))));
  self.clients.claim();
});
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  const isFreshFile = url.pathname.endsWith('.html') || url.pathname.endsWith('.json') || url.pathname.endsWith('.md') || url.pathname.endsWith('service-worker.js') || url.pathname.endsWith('manifest.webmanifest') || url.pathname.endsWith('/');
  if (isFreshFile) {
    url.searchParams.set('v', '20260620202140');
    event.respondWith(fetch(url.toString(), { cache: 'no-store' }).then(response => {
      const copy = response.clone();
      caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy));
      return response;
    }).catch(() => caches.match(event.request).then(hit => hit || caches.match('offline.html'))));
    return;
  }
  event.respondWith(fetch(event.request).then(response => {
    const copy = response.clone();
    caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy));
    return response;
  }).catch(() => caches.match(event.request).then(hit => hit || caches.match('offline.html'))));
});
