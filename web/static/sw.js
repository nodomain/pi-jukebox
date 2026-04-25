// Jukebox Pi Service Worker — cache app shell for offline launch + offline fallback
const CACHE = 'jukebox-v2';
const SHELL = ['/', '/static/style.css', '/static/app.js', '/static/favicon.svg'];
const OFFLINE_PAGE = '/offline';

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => {
      // Cache the offline fallback page as raw HTML
      const offlineHtml = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0f1117">
<title>Jukebox — Offline</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; background: #0f1117; color: #e0e0e0; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; text-align: center; }
  h1 { font-size: 1.5em; margin-bottom: 8px; }
  p { color: #888; margin-bottom: 20px; }
  .spinner { width: 32px; height: 32px; border: 3px solid #2a2d37; border-top-color: #4a9eff; border-radius: 50%; animation: spin 1s linear infinite; margin-bottom: 16px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  button { background: #4a9eff; color: #fff; border: none; padding: 10px 24px; border-radius: 8px; cursor: pointer; font-size: 0.9em; }
  button:active { opacity: 0.7; }
  #status { color: #888; font-size: 0.8em; margin-top: 12px; }
</style>
</head>
<body>
  <div class="spinner"></div>
  <h1>Jukebox is offline</h1>
  <p>Waiting for connection...</p>
  <button onclick="location.reload()">Retry Now</button>
  <div id="status">Auto-retrying every 5 seconds</div>
  <script>
    let retryCount = 0;
    setInterval(function() {
      retryCount++;
      document.getElementById('status').textContent = 'Retry #' + retryCount + '...';
      fetch('/api/audio/status', { cache: 'no-store' }).then(function(r) {
        if (r.ok) location.replace('/');
      }).catch(function() {});
    }, 5000);
  </script>
</body>
</html>`;
      const offlineResponse = new Response(offlineHtml, {
        headers: { 'Content-Type': 'text/html' },
      });
      return Promise.all([
        c.addAll(SHELL),
        c.put(OFFLINE_PAGE, offlineResponse),
      ]);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // API calls: network-only, no caching (handled by app-level toast on failure)
  if (url.pathname.startsWith('/api/')) return;

  // Navigation requests: network-first with offline fallback page
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request).then(r => {
        if (r.ok) {
          const clone = r.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return r;
      }).catch(() =>
        caches.match(e.request).then(cached =>
          cached || caches.match(OFFLINE_PAGE)
        )
      )
    );
    return;
  }

  // Static assets: network-first, cache fallback
  e.respondWith(
    fetch(e.request).then(r => {
      if (r.ok) {
        const clone = r.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
      }
      return r;
    }).catch(() => caches.match(e.request))
  );
});
