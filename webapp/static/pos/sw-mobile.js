/**
 * Service Worker SelfPOS Mobile V0.3 — Précache shell + network-first (anti page noire).
 *
 * Garantit : la PWA boot offline TOTAL, même après reboot tablette.
 * Toutes les données métier sont en IndexedDB côté client, ne nécessitent aucun serveur.
 */

const CACHE_NAME = 'selfpos-mobile-v0.3.3';
const SHELL_URLS = [
  '/pos/mobile',
  '/static/pos/manifest-mobile.json',
  '/static/pos/icon.svg',
  '/static/img/selffarm/png/logo-badge-192.png',
  '/static/img/selffarm/png/logo-badge-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_URLS).catch((err) => {
        console.warn('[SW] addAll partial fail:', err);
        // Best-effort : cache ce qu'on peut, l'app marche quand même
      }))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
     // Reload silencieux des onglets ouverts → la nouvelle version s'applique
     // sans hard-clean (garde-fou PWA #3).
     .then(() => self.clients.matchAll({ type: 'window' }))
     .then((clients) => clients.forEach((c) => { try { c.navigate(c.url); } catch (e) {} }))
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);

  // Shell PWA + assets : cache-first
  if (url.pathname === '/pos/mobile' || url.pathname.startsWith('/static/pos/') || url.pathname.startsWith('/static/img/selffarm/')) {
    event.respondWith(
      // network-first : toujours la dernière version si en ligne, cache en secours
      // offline (évite les écrans figés/noirs après mise à jour — règle PWA anti hard-clean)
      fetch(request).then((resp) => {
        if (resp.ok) {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then((c) => c.put(request, clone));
        }
        return resp;
      }).catch(() => caches.match(request).then((cached) => cached || new Response(
        '<h1>Hors ligne</h1><p>Ressource non disponible. Reconnecte-toi une fois pour la mettre en cache.</p>',
        { headers: { 'Content-Type': 'text/html; charset=utf-8' }, status: 503 }
      )))
    );
    return;
  }

  // Reste : network-only par défaut (l'app mobile n'utilise pas d'API serveur en condition normale)
});
