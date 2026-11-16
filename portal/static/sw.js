/* Служебный воркер портала: оболочка доступна без сети, данные (API) никогда не кешируются. */
const V = 'createportal-v1';
const BASE = '__BASE__';
self.addEventListener('install', e => { self.skipWaiting(); });
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const r = e.request;
  if (r.method !== 'GET') return;
  const u = new URL(r.url);
  if (u.origin !== location.origin || u.pathname.startsWith(BASE + '/api/')) return;
  if (r.mode === 'navigate') {
    e.respondWith(fetch(r).then(res => { const c = res.clone(); caches.open(V).then(ca => ca.put(BASE + '/', c)); return res; })
      .catch(() => caches.match(BASE + '/').then(x => x || new Response('Нет сети', { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } }))));
    return;
  }
  if (u.pathname.startsWith(BASE + '/icons/')) {
    e.respondWith(caches.match(r).then(x => x || fetch(r).then(res => { const c = res.clone(); caches.open(V).then(ca => ca.put(r, c)); return res; })));
  }
});
