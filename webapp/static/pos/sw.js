/**
 * Service Worker SelfPOS — précache shell + sync ventes offline.
 *
 * Stratégie :
 * - Précache statique : CSS/JS de base + page caisse shell
 * - Pages caisse et assets statiques : network-first avec fallback cache
 * - Pour POST vente : si offline → 202 + queue côté client gère via LocalStorage
 *   (le SW n'intercepte pas le POST — le JS côté caisse détecte navigator.onLine)
 * - Background sync : déclenche flush quand connexion revient
 */

const CACHE_NAME = 'selfpos-v2';
const PRECACHE_URLS = [
  '/static/pos/manifest.json',
  '/static/pos/icon.svg',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  // POST → laisser passer, gestion offline côté JS caisse
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (!url.pathname.startsWith('/static/') && !url.pathname.startsWith('/pos/')) return;

  // network-first : la dernière version en ligne, le cache en secours hors ligne.
  // En cache-first, une mise à jour de l'app laisserait la caisse sur ses anciens fichiers.
  event.respondWith(
    fetch(request)
      .then((resp) => {
        if (resp.ok) {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then((c) => c.put(request, clone));
        }
        return resp;
      })
      .catch(() => caches.match(request).then((cached) => cached || new Response(
        '<h1>Hors ligne</h1><p>Cette page n\'est pas disponible hors connexion. Reviens en ligne pour la consulter.</p>',
        { headers: { 'Content-Type': 'text/html; charset=utf-8' }, status: 503 }
      )))
  );
});

// Background sync : déclenché quand le réseau revient
self.addEventListener('sync', (event) => {
  if (event.tag === 'flush-pos') {
    event.waitUntil(notifyClientsToFlush());
  }
});

async function notifyClientsToFlush() {
  const clients = await self.clients.matchAll({ type: 'window' });
  for (const client of clients) {
    client.postMessage({ type: 'flush-queue' });
  }
}
