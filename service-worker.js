const CACHE_NAME = 'tiantianle-ironlaw-20260701134042';
const APP_SHELL = ['index.html','首頁.html','prediction.html','下期預測.html','review.html','上期未命中檢討.html','tiantianle_low_probability_avoid.html','天天樂低機率精準暫避.html','低機率精準暫避.html','monthly_summary.html','每月總整理.html','六月總整理.html','prediction-history.html','預測歷史對比.html','complete_report.html','完整_report.html','完整戰報.html','天天樂完整戰報.html','reports/complete_report.html','reports/tiantianle_low_probability_avoid.html','reports/天天樂低機率精準暫避.html','reports/低機率精準暫避.html','reports/monthly_summary.html','reports/每月總整理.html','reports/六月總整理.html','reports/完整_report.html','reports/完整戰報.html','reports/天天樂完整戰報.html','reports/latest_battle_report.html','latest_analysis.json','最新分析資料.json','version.json','版本.json','system_health_report.md','系統健康報告.md','manifest.webmanifest','offline.html','離線頁.html','reset.html','清除快取.html','404.html','icon-192.png','icon-512.png'];
async function deleteAllCaches() {
  const keys = await caches.keys();
  await Promise.all(keys.map(key => caches.delete(key)));
}
async function deleteOldCaches() {
  const keys = await caches.keys();
  await Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key)));
}
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(APP_SHELL.map(url => url + '?v=20260701134042')).catch(() => cache.addAll(APP_SHELL))));
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
  const path = decodeURIComponent(url.pathname);
  const isReportShortcut = path.includes('complete_report') || path.includes('完整_report') || path.includes('完整戰報') || path.includes('latest_battle_report') || path.endsWith('/reports/');
  const stableReportUrl = new URL('reports/complete_report.html?v=20260701134042', self.registration.scope).toString();
  const isFreshFile = url.pathname.endsWith('.html') || url.pathname.endsWith('.json') || url.pathname.endsWith('.md') || url.pathname.endsWith('service-worker.js') || url.pathname.endsWith('manifest.webmanifest') || url.pathname.endsWith('/');
  if (isFreshFile) {
    url.searchParams.set('v', '20260701134042');
    event.respondWith(fetch(url.toString(), { cache: 'no-store', headers: { 'Cache-Control': 'no-cache' } }).then(response => {
      if (!response.ok && isReportShortcut) return fetch(stableReportUrl, { cache: 'no-store', headers: { 'Cache-Control': 'no-cache' } });
      return response;
    }).catch(() => {
      if (isReportShortcut) return fetch(stableReportUrl, { cache: 'no-store', headers: { 'Cache-Control': 'no-cache' } }).catch(() => caches.match('reports/complete_report.html').then(hit => hit || caches.match('complete_report.html') || caches.match('offline.html')));
      return caches.match(event.request).then(hit => hit || caches.match('offline.html'));
    }));
    return;
  }
  event.respondWith(fetch(event.request, { cache: 'no-store' }).then(response => {
    const copy = response.clone();
    caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy));
    return response;
  }).catch(() => caches.match(event.request).then(hit => hit || caches.match('offline.html'))));
});
